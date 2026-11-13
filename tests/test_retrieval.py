import json

import numpy as np
import pytest

from relay.corpus import PAPERS, Page
from relay.retrieval import (
    HYBRID,
    HYBRID_RERANK,
    LEXICAL,
    AdvancedRetriever,
    Retriever,
    reciprocal_rank_fusion,
    token_chunks,
)


class WordTokenizer:
    model_max_length = 8
    name_or_path = "fixture-tokenizer"

    def num_special_tokens_to_add(self, pair=False):
        return 2

    def __call__(self, text, *, add_special_tokens, return_offsets_mapping, truncation):
        assert not add_special_tokens and return_offsets_mapping and not truncation
        import re

        offsets = [match.span() for match in re.finditer(r"\w+", text)]
        return {"input_ids": list(range(len(offsets))), "offset_mapping": offsets}


class Embedder:
    def encode(self, texts, **kwargs):
        values = []
        for text in texts if isinstance(texts, list) else [texts]:
            if "meaning" in text.casefold() or "semantic" in text.casefold():
                values.append([1.0, 0.0])
            else:
                values.append([0.0, 1.0])
        return np.asarray(values, dtype=np.float32)


class Reranker:
    def predict(self, pairs, **kwargs):
        return np.asarray([10.0 if "preferred" in passage else 0.0 for _, passage in pairs])


def pages():
    return [
        Page(
            paper_id=PAPERS[0].id,
            title=PAPERS[0].title,
            page=1,
            text="one two three four five six seven eight nine ten",
        ),
    ]


def test_token_chunks_preserve_exact_spans_and_never_cross_model_limit():
    chunks = token_chunks(pages(), WordTokenizer(), size=6, overlap=2)
    assert [chunk.text for chunk in chunks] == [
        "one two three four five six",
        "five six seven eight nine ten",
    ]
    assert all(chunk.text == pages()[0].text[chunk.start : chunk.end] for chunk in chunks)
    assert all(chunk.id.startswith(f"{PAPERS[0].id}:p1:t") for chunk in chunks)
    with pytest.raises(ValueError, match="model limit"):
        token_chunks(pages(), WordTokenizer(), size=7, overlap=2)


def test_rrf_is_deterministic_and_rewards_agreement():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]])
    assert [item[0] for item in fused[:2]] == ["a", "b"]
    assert fused[0][1] == fused[1][1]


def test_three_settings_have_distinct_retrieval_and_bounded_reranking():
    semantic = token_chunks(pages(), WordTokenizer(), size=6, overlap=2)
    lexical = Retriever(semantic)
    embeddings = np.asarray([[0.0, 1.0], [1.0, 0.0]], dtype=np.float32)
    advanced = AdvancedRetriever(lexical, semantic, Embedder(), embeddings, Reranker())

    lexical_hits = advanced.search("seven", setting=LEXICAL, k=1)
    hybrid_hits = advanced.search("semantic meaning", setting=HYBRID, k=1)
    reranked = advanced.search("semantic meaning", setting=HYBRID_RERANK, k=1)

    assert lexical_hits[0].chunk.text.startswith("five")
    assert hybrid_hits[0].scores.keys() >= {"rrf", "dense"}
    assert reranked[0].scores.keys() >= {"rrf", "rerank"}
    assert len(reranked) == 1
    with pytest.raises(ValueError, match="retrieval setting"):
        advanced.search("query", setting="invented", k=4)


def test_advanced_index_rejects_tampered_or_wrong_shaped_vectors(tmp_path):
    from relay.retrieval import load_advanced_index

    index = tmp_path / "retrieval"
    index.mkdir()
    chunks = token_chunks(pages(), WordTokenizer(), size=6, overlap=2)
    raw_chunks = "".join(chunk.model_dump_json() + "\n" for chunk in chunks).encode()
    (index / "chunks.jsonl").write_bytes(raw_chunks)
    np.save(index / "dense.npy", np.ones((1, 2), dtype=np.float32), allow_pickle=False)
    vectors = (index / "dense.npy").read_bytes()
    import hashlib

    (index / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "chunk_count": 2,
                "embedding_dimension": 2,
                "chunks_sha256": hashlib.sha256(raw_chunks).hexdigest(),
                "dense_sha256": hashlib.sha256(vectors).hexdigest(),
            }
        )
    )
    with pytest.raises(ValueError, match="shape"):
        load_advanced_index(tmp_path)
