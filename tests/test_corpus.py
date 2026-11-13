import hashlib
import json

import pytest

from relay.corpus import PAPERS, Chunk, chunk_page, load_chunks, validate_pdf_version
from relay.retrieval import Retriever


def test_library_pins_exact_versions():
    assert [p.id for p in PAPERS] == ["1706.03762v7", "2410.00037v1", "2507.07955v2"]


def test_chunks_preserve_page_spans_and_cover_text():
    text = "Alpha beta gamma delta epsilon zeta eta theta iota kappa."
    chunks = chunk_page(PAPERS[0], 3, text, size=4, overlap=1)
    assert chunks[0].text == "Alpha beta gamma delta"
    assert chunks[1].text == "delta epsilon zeta eta"
    assert chunks[-1].text.endswith("kappa.")
    assert all(c.page == 3 and c.text == text[c.start : c.end] for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)


@pytest.mark.parametrize("size,overlap", [(0, 0), (4, 4), (4, -1)])
def test_chunker_rejects_non_progressing_windows(size, overlap):
    with pytest.raises(ValueError):
        chunk_page(PAPERS[0], 1, "some text", size=size, overlap=overlap)


def test_wrong_version_or_missing_identity_is_rejected():
    with pytest.raises(ValueError, match="version"):
        validate_pdf_version(PAPERS[1], "arXiv:2410.00037v2")
    with pytest.raises(ValueError, match="version"):
        validate_pdf_version(PAPERS[1], "unidentified PDF")
    validate_pdf_version(PAPERS[1], "arXiv:2410.00037v1 [cs.CL]")


def test_retrieval_ranks_evidence_and_returns_no_zero_score_passages():
    chunks = chunk_page(PAPERS[0], 1, "Attention uses queries keys and values.")
    chunks += chunk_page(PAPERS[1], 2, "Moshi supports full duplex speech dialogue.")
    hits = Retriever(chunks).search("Moshi speech dialogue", k=2)
    assert hits[0].chunk.paper_id == "2410.00037v1"
    assert len(hits) == 1
    assert Retriever(chunks).search("zqxwvu") == []


def test_load_detects_corrupt_index(tmp_path):
    chunk = Chunk(
        id="one", paper_id=PAPERS[0].id, title=PAPERS[0].title, page=1, start=0, end=4, text="test"
    )
    payload = (chunk.model_dump_json() + "\n").encode()
    (tmp_path / "chunks.jsonl").write_bytes(payload)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "chunks_sha256": hashlib.sha256(b"different").hexdigest(),
            }
        )
    )
    with pytest.raises(ValueError, match="integrity"):
        load_chunks(tmp_path)
