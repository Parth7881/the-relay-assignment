"""Versioned lexical, dense-hybrid and local reranked retrieval settings."""

import hashlib
import io
import json
import math
from collections import Counter
from pathlib import Path
from typing import Protocol

import numpy as np
from pydantic import BaseModel, Field

from relay.corpus import WORD, Chunk, Page, load_chunks, load_pages

LEXICAL = "lexical-word180-k4-v1"
HYBRID = "hybrid-minilm220-rrf-k4-v1"
HYBRID_RERANK = "hybrid-minilm220-rrf-rerank-k4-v1"
RETRIEVAL_SETTINGS = (LEXICAL, HYBRID, HYBRID_RERANK)
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
RERANK_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"

STOP = frozenset(
    "a an the is are was were be been being what which how does do did of to in on "
    "for and or with by from this that it its as about can paper say explain".split()
)


def terms(text: str) -> list[str]:
    return [m.group().casefold() for m in WORD.finditer(text) if m.group().casefold() not in STOP]


class Hit(BaseModel):
    chunk: Chunk
    score: float
    scores: dict[str, float] = Field(default_factory=dict)


class Searcher(Protocol):
    def search(
        self, question: str, *, k: int = 4, setting: str = LEXICAL, expanded: bool = False
    ) -> list[Hit]: ...


def _deduplicate(hits: list[Hit], k: int) -> list[Hit]:
    selected = []
    for hit in hits:
        duplicate = any(
            hit.chunk.paper_id == other.chunk.paper_id
            and hit.chunk.page == other.chunk.page
            and max(
                0,
                min(hit.chunk.end, other.chunk.end) - max(hit.chunk.start, other.chunk.start),
            )
            / min(hit.chunk.end - hit.chunk.start, other.chunk.end - other.chunk.start)
            > 0.5
            for other in selected
        )
        if not duplicate:
            selected.append(hit)
        if len(selected) == k:
            break
    return selected


class Retriever:
    def __init__(self, chunks: list[Chunk]):
        if not chunks:
            raise ValueError("Cannot index an empty corpus.")
        self.chunks = chunks
        self.counts = [Counter(terms(c.text)) for c in chunks]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.average = sum(self.lengths) / len(chunks) or 1.0
        self.df = Counter(t for count in self.counts for t in count)

    def search(
        self, question: str, *, k: int = 4, setting: str = LEXICAL, expanded: bool = False
    ) -> list[Hit]:
        if setting != LEXICAL:
            raise ValueError(f"Unsupported retrieval setting: {setting}")
        if not 1 <= k <= 12:
            raise ValueError("k must be between 1 and 12.")
        query = set(terms(question))
        scored = []
        for chunk, count, length in zip(self.chunks, self.counts, self.lengths, strict=True):
            score = 0.0
            for term in query:
                frequency = count[term]
                if not frequency:
                    continue
                idf = math.log(1 + (len(self.chunks) - self.df[term] + 0.5) / (self.df[term] + 0.5))
                score += (
                    idf
                    * frequency
                    * 2.5
                    / (frequency + 1.5 * (0.25 + 0.75 * length / self.average))
                )
            if score > 0:
                score = round(score, 6)
                scored.append(Hit(chunk=chunk, score=score, scores={"bm25": score}))
        scored.sort(key=lambda hit: (-hit.score, hit.chunk.id))
        return _deduplicate(scored, k)


def token_chunks(
    pages: list[Page],
    tokenizer,
    *,
    size: int = 220,
    overlap: int = 40,
    model_limit: int | None = None,
) -> list[Chunk]:
    if size < 1 or not 0 <= overlap < size:
        raise ValueError("Require size > overlap >= 0.")
    special = tokenizer.num_special_tokens_to_add(pair=False)
    effective_limit = min(tokenizer.model_max_length, model_limit or tokenizer.model_max_length)
    if size + special > effective_limit:
        raise ValueError("Chunk size exceeds tokenizer model limit with special tokens.")
    chunks = []
    for page in pages:
        encoded = tokenizer(
            page.text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        offsets = encoded["offset_mapping"]
        ids = encoded["input_ids"]
        if len(ids) != len(offsets):
            raise ValueError("Tokenizer did not return one offset per content token.")
        for offset in range(0, len(ids), size - overlap):
            end_index = min(offset + size, len(ids))
            if offset >= end_index:
                break
            start, end = offsets[offset][0], offsets[end_index - 1][1]
            chunks.append(
                Chunk(
                    id=f"{page.paper_id}:p{page.page}:t{offset}",
                    paper_id=page.paper_id,
                    title=page.title,
                    page=page.page,
                    start=start,
                    end=end,
                    text=page.text[start:end],
                )
            )
            if end_index == len(ids):
                break
    if not chunks:
        raise ValueError("Tokenizer produced no chunks.")
    return chunks


def reciprocal_rank_fusion(rankings: list[list[str]], *, constant: int = 60):
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1 / (constant + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


class AdvancedRetriever:
    def __init__(self, lexical: Retriever, chunks: list[Chunk], embedder, embeddings, reranker):
        vectors = np.asarray(embeddings, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(chunks) or not np.isfinite(vectors).all():
            raise ValueError("Dense index shape or values do not match chunks.")
        self.lexical = lexical
        self.chunks = chunks
        self.hybrid_lexical = Retriever(chunks)
        self.embedder = embedder
        self.embeddings = vectors
        self.reranker = reranker
        self.by_id = {chunk.id: chunk for chunk in chunks}
        self.dense_index = {chunk.id: index for index, chunk in enumerate(chunks)}

    @staticmethod
    def _ensure_fits(model, first: str, second: str | None = None) -> None:
        tokenizer = getattr(model, "tokenizer", None)
        limit = getattr(model, "max_seq_length", None) or getattr(model, "max_length", None)
        if tokenizer is None or not isinstance(limit, int):
            return
        encoded = tokenizer(
            first,
            second,
            add_special_tokens=True,
            truncation=False,
        )
        if len(encoded["input_ids"]) > limit:
            raise ValueError("Question or rerank pair exceeds the pinned model token limit.")

    def search(
        self, question: str, *, k: int = 4, setting: str = LEXICAL, expanded: bool = False
    ) -> list[Hit]:
        if setting == LEXICAL:
            return self.lexical.search(question, k=k)
        if setting not in (HYBRID, HYBRID_RERANK):
            raise ValueError(f"Unsupported retrieval setting: {setting}")
        if not 1 <= k <= 12:
            raise ValueError("k must be between 1 and 12.")
        candidate_limit = min(len(self.chunks), 24 if expanded else 12)
        lexical = self.hybrid_lexical.search(question, k=min(12, candidate_limit))
        self._ensure_fits(self.embedder, question)
        query = np.asarray(
            self.embedder.encode(
                [question],
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )
        if query.shape != (1, self.embeddings.shape[1]) or not np.isfinite(query).all():
            raise ValueError("Query embedding has unexpected shape or values.")
        dense_scores = self.embeddings @ query[0]
        dense_order = sorted(
            range(len(self.chunks)),
            key=lambda index: (-float(dense_scores[index]), self.chunks[index].id),
        )[:candidate_limit]
        dense_ids = [self.chunks[index].id for index in dense_order]
        fused = reciprocal_rank_fusion([[hit.chunk.id for hit in lexical], dense_ids])
        candidates = []
        for chunk_id, rrf in fused[:candidate_limit]:
            dense = float(dense_scores[self.dense_index[chunk_id]])
            candidates.append(
                Hit(
                    chunk=self.by_id[chunk_id],
                    score=round(rrf, 8),
                    scores={"rrf": round(rrf, 8), "dense": round(dense, 8)},
                )
            )
        if setting == HYBRID_RERANK:
            if self.reranker is None:
                raise ValueError("Reranker model is not loaded.")
            pairs = [(question, hit.chunk.text) for hit in candidates]
            for query, passage in pairs:
                self._ensure_fits(self.reranker, query, passage)
            scores = np.asarray(self.reranker.predict(pairs, show_progress_bar=False)).reshape(-1)
            if scores.shape != (len(candidates),) or not np.isfinite(scores).all():
                raise ValueError("Reranker returned invalid scores.")
            for hit, score in zip(candidates, scores, strict=True):
                hit.scores["rerank"] = round(float(score), 8)
                hit.score = round(float(score), 8)
            candidates.sort(key=lambda hit: (-hit.score, hit.chunk.id))
        return _deduplicate(candidates, k)


def load_advanced_index(data_dir: Path) -> tuple[list[Chunk], np.ndarray, dict]:
    root = data_dir / "retrieval"
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        chunk_data = (root / "chunks.jsonl").read_bytes()
        vector_data = (root / "dense.npy").read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("Advanced retrieval index missing. Run: uv run relay index") from exc
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported advanced retrieval index schema.")
    if hashlib.sha256(chunk_data).hexdigest() != manifest.get("chunks_sha256"):
        raise ValueError("Advanced chunk index integrity mismatch.")
    if hashlib.sha256(vector_data).hexdigest() != manifest.get("dense_sha256"):
        raise ValueError("Dense index integrity mismatch.")
    chunks = [Chunk.model_validate_json(line) for line in chunk_data.decode().splitlines()]
    vectors = np.load(root / "dense.npy", allow_pickle=False)
    expected = (manifest.get("chunk_count"), manifest.get("embedding_dimension"))
    if vectors.shape != expected or len(chunks) != expected[0] or not np.isfinite(vectors).all():
        raise ValueError("Dense index shape or values do not match manifest.")
    return chunks, np.asarray(vectors, dtype=np.float32), manifest


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _embedding_model(*, local_files_only: bool):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        EMBEDDING_MODEL,
        revision=EMBEDDING_REVISION,
        trust_remote_code=False,
        device="cpu",
        local_files_only=local_files_only,
    )


def _reranker_model(*, local_files_only: bool):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(
        RERANK_MODEL,
        revision=RERANK_REVISION,
        trust_remote_code=False,
        device="cpu",
        max_length=256,
        local_files_only=local_files_only,
    )


def build_advanced_index(data_dir: Path, *, embedder=None) -> dict:
    """Build deterministic token chunks and normalized local embeddings; manifest last."""
    model = embedder or _embedding_model(local_files_only=False)
    limit = getattr(model, "max_seq_length", None)
    if not isinstance(limit, int):
        raise ValueError("Embedding model does not expose a finite sequence limit.")
    chunks = token_chunks(load_pages(data_dir), model.tokenizer, model_limit=limit)
    vectors = np.asarray(
        model.encode(
            [chunk.text for chunk in chunks],
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=True,
        ),
        dtype=np.float32,
    )
    if vectors.ndim != 2 or vectors.shape[0] != len(chunks) or not np.isfinite(vectors).all():
        raise ValueError("Embedding model returned invalid vectors.")
    chunk_data = "".join(chunk.model_dump_json() + "\n" for chunk in chunks).encode("utf-8")
    buffer = io.BytesIO()
    np.save(buffer, vectors, allow_pickle=False)
    vector_data = buffer.getvalue()
    root = data_dir / "retrieval"
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "setting_chunks": {HYBRID: len(chunks), HYBRID_RERANK: len(chunks)},
        "chunk_count": len(chunks),
        "chunk_size": 220,
        "overlap": 40,
        "tokenizer": getattr(model.tokenizer, "name_or_path", EMBEDDING_MODEL),
        "model_max_sequence_length": limit,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_revision": EMBEDDING_REVISION,
        "rerank_model": RERANK_MODEL,
        "rerank_revision": RERANK_REVISION,
        "embedding_dimension": vectors.shape[1],
        "chunks_sha256": hashlib.sha256(chunk_data).hexdigest(),
        "dense_sha256": hashlib.sha256(vector_data).hexdigest(),
    }
    _atomic_write(root / "chunks.jsonl", chunk_data)
    _atomic_write(root / "dense.npy", vector_data)
    _atomic_write(root / "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
    return manifest


def load_retriever(data_dir: Path, setting: str = LEXICAL) -> Searcher:
    lexical = Retriever(load_chunks(data_dir))
    if setting == LEXICAL:
        return lexical
    if setting not in (HYBRID, HYBRID_RERANK):
        raise ValueError(f"Unsupported retrieval setting: {setting}")
    chunks, vectors, manifest = load_advanced_index(data_dir)
    if (
        manifest.get("embedding_model") != EMBEDDING_MODEL
        or manifest.get("embedding_revision") != EMBEDDING_REVISION
        or manifest.get("rerank_model") != RERANK_MODEL
        or manifest.get("rerank_revision") != RERANK_REVISION
    ):
        raise ValueError("Advanced retrieval model revisions do not match this build.")
    return AdvancedRetriever(
        lexical,
        chunks,
        _embedding_model(local_files_only=True),
        vectors,
        _reranker_model(local_files_only=True) if setting == HYBRID_RERANK else None,
    )


def prepare_models() -> None:
    """Download and validate pinned snapshots only from the explicit index command."""
    _embedding_model(local_files_only=False)
    _reranker_model(local_files_only=False)
