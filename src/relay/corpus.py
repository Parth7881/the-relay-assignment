"""Pinned corpus ingestion and page-preserving lexical chunks.

The first baseline uses Unicode word spans, NOT an LLM or embedding tokenizer.
Its sizes must not be presented as provider tokens or the final dense settings.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader

WORD = re.compile(r"\w+(?:[-']\w+)*", re.UNICODE)


class Paper(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    title: str

    @property
    def url(self) -> str:
        return f"https://arxiv.org/pdf/{self.id}"


PAPERS = (
    Paper(id="1706.03762v7", title="Attention Is All You Need"),
    Paper(id="2410.00037v1", title="Moshi: a speech-text foundation model for real-time dialogue"),
    Paper(
        id="2507.07955v2", title="Dynamic Chunking for End-to-End Hierarchical Sequence Modeling"
    ),
)


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    paper_id: str
    title: str
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @property
    def url(self) -> str:
        return f"https://arxiv.org/pdf/{self.paper_id}#page={self.page}"


class Page(BaseModel):
    model_config = ConfigDict(frozen=True)
    paper_id: str
    title: str
    page: int = Field(ge=1)
    text: str


def chunk_page(
    paper: Paper, page: int, text: str, *, size: int = 180, overlap: int = 30
) -> list[Chunk]:
    if size < 1 or not 0 <= overlap < size:
        raise ValueError("Require size > overlap >= 0.")
    spans = list(WORD.finditer(text))
    chunks = []
    for offset in range(0, len(spans), size - overlap):
        end_index = min(offset + size, len(spans))
        start = spans[offset].start()
        end = spans[end_index].start() if end_index < len(spans) else len(text)
        while end > start and text[end - 1].isspace():
            end -= 1
        chunks.append(
            Chunk(
                id=f"{paper.id}:p{page}:w{offset}",
                paper_id=paper.id,
                title=paper.title,
                page=page,
                start=start,
                end=end,
                text=text[start:end],
            )
        )
        if end_index == len(spans):
            break
    return chunks


def validate_pdf_version(paper: Paper, first_page_text: str) -> None:
    if not re.search(rf"arXiv\s*:\s*{re.escape(paper.id)}\b", first_page_text):
        raise ValueError(f"PDF version identity mismatch: expected {paper.id}.")


def _write_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def ingest(data_dir: Path) -> dict:
    """Fetch only allowlisted versions; cache validated PDFs, rebuild deterministic index."""
    data_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = data_dir / "papers"
    pdf_dir.mkdir(exist_ok=True)
    old_manifest = {}
    manifest_path = data_dir / "manifest.json"
    if manifest_path.exists():
        old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    old_papers = {p["id"]: p for p in old_manifest.get("papers", [])}
    entries, chunks, pages = [], [], []
    # No browser credentials, alternate providers or arbitrary URLs are used.
    with httpx.Client(
        timeout=60, follow_redirects=True, headers={"User-Agent": "TheRelay-assignment/0.1"}
    ) as client:
        for paper in PAPERS:
            path = pdf_dir / f"{paper.id}.pdf"
            downloaded = not path.exists()
            if downloaded:
                with client.stream("GET", paper.url) as response:
                    response.raise_for_status()
                    parts, count = [], 0
                    for part in response.iter_bytes():
                        count += len(part)
                        if count > 30 * 1024 * 1024:
                            raise ValueError("PDF exceeds the 30 MB download bound.")
                        parts.append(part)
                    raw = b"".join(parts)
                if not raw.startswith(b"%PDF"):
                    raise ValueError(f"Expected PDF bytes for {paper.id}.")
                # Validate the candidate before replacing any local artifact.
                from io import BytesIO

                reader = PdfReader(BytesIO(raw))
            else:
                raw = path.read_bytes()
                reader = PdfReader(path)
            digest = hashlib.sha256(raw).hexdigest()
            previous = old_papers.get(paper.id)
            if previous and previous["sha256"] != digest:
                raise ValueError(f"Cached PDF integrity mismatch for {paper.id}.")
            if not 1 <= len(reader.pages) <= 200:
                raise ValueError("Unexpected PDF page count.")
            extracted = [page.extract_text() or "" for page in reader.pages]
            validate_pdf_version(paper, extracted[0])
            if downloaded:
                _write_atomic(path, raw)
            low_text_pages = []
            for number, text in enumerate(extracted, start=1):
                pages.append(
                    {"paper_id": paper.id, "title": paper.title, "page": number, "text": text}
                )
                if len(WORD.findall(text)) < 20:
                    low_text_pages.append(number)
                chunks.extend(chunk_page(paper, number, text))
            entries.append(
                {
                    **paper.model_dump(),
                    "url": paper.url,
                    "sha256": digest,
                    "page_count": len(extracted),
                    "bytes": len(raw),
                    "downloaded_at": (
                        datetime.now(UTC).isoformat()
                        if downloaded
                        else (previous or {}).get("downloaded_at")
                    ),
                    "low_text_pages": low_text_pages,
                }
            )
    if not chunks:
        raise ValueError("No readable text was extracted.")
    chunk_data = "".join(c.model_dump_json() + "\n" for c in chunks).encode("utf-8")
    page_data = "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pages).encode("utf-8")
    manifest = {
        "schema_version": 1,
        "built_at": datetime.now(UTC).isoformat(),
        "papers": entries,
        "chunk_count": len(chunks),
        "chunker": "unicode-word-v1",
        "chunk_size": 180,
        "overlap": 30,
        "extraction": "pypdf-plain",
        "chunks_sha256": hashlib.sha256(chunk_data).hexdigest(),
        "pages_sha256": hashlib.sha256(page_data).hexdigest(),
    }
    _write_atomic(data_dir / "pages.jsonl", page_data)
    _write_atomic(data_dir / "chunks.jsonl", chunk_data)
    _write_atomic(manifest_path, json.dumps(manifest, indent=2).encode("utf-8"))
    return manifest


def load_chunks(data_dir: Path) -> list[Chunk]:
    try:
        manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
        raw = (data_dir / "chunks.jsonl").read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("Corpus not ready. Run: uv run relay ingest") from exc
    if hashlib.sha256(raw).hexdigest() != manifest.get("chunks_sha256"):
        raise ValueError("Chunk index integrity mismatch; re-run ingestion.")
    chunks = [Chunk.model_validate_json(line) for line in raw.decode("utf-8").splitlines()]
    allowed = {p.id for p in PAPERS}
    if not chunks or any(c.paper_id not in allowed for c in chunks):
        raise ValueError("Index contains documents outside the pinned library.")
    return chunks


def load_pages(data_dir: Path) -> list[Page]:
    try:
        manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
        raw = (data_dir / "pages.jsonl").read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("Corpus not ready. Run: uv run relay ingest") from exc
    if hashlib.sha256(raw).hexdigest() != manifest.get("pages_sha256"):
        raise ValueError("Page index integrity mismatch; re-run ingestion.")
    titles = {paper.id: paper.title for paper in PAPERS}
    pages = []
    for line in raw.decode("utf-8").splitlines():
        value = json.loads(line)
        paper_id = value.get("paper_id")
        if paper_id not in titles:
            raise ValueError("Page index contains documents outside the pinned library.")
        value.setdefault("title", titles[paper_id])
        pages.append(Page.model_validate(value))
    if not pages:
        raise ValueError("Page index is empty; re-run ingestion.")
    return pages
