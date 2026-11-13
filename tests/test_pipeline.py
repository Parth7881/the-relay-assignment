import json

import pytest

from relay.corpus import PAPERS, chunk_page
from relay.pipeline import Pipeline
from relay.provider import ModelReply, ProviderError
from relay.retrieval import Retriever


class ScriptedModel:
    """External model boundary only; never used by production or quality runs."""

    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    async def complete(self, messages, *, stage, trace):
        self.calls.append(stage)
        value = next(self.replies)
        if isinstance(value, Exception):
            raise value
        return ModelReply(
            text=json.dumps(value),
            tokens_in=10,
            tokens_out=5,
            first_token_ms=1,
            total_ms=2,
            model="test-fixture",
        )


def make_pipeline(replies, tmp_path):
    chunks = chunk_page(PAPERS[0], 3, "Attention uses queries, keys and values.")
    model = ScriptedModel(replies)
    return Pipeline(Retriever(chunks), model, tmp_path), model, chunks[0].id


def draft(cid):
    return {
        "refused": False,
        "claims": [
            {
                "text": "Attention uses queries, keys and values.",
                "citations": [{"chunk_id": cid, "quote": "queries, keys and values"}],
            }
        ],
    }


async def test_supported_answer_has_resolvable_citations_and_four_stage_trace(tmp_path):
    pipe, model, cid = make_pipeline([], tmp_path)
    model.replies = iter(
        [
            draft(cid),
            {
                "supported": True,
                "addresses_question": True,
                "unsupported_claims": [],
                "reason": "Explicit passage.",
            },
        ]
    )
    result = await pipe.ask("What does attention use?")
    assert result.status == "ok" and result.disposition == "answered"
    assert result.evidence[0].chunk.id == cid
    assert f"[{cid}]" in result.answer
    assert model.calls == ["draft", "verify"]
    saved = json.loads((tmp_path / f"{result.request_id}.json").read_text())
    assert saved["result"]["tokens_in"] == 20
    assert [e["stage"] for e in saved["events"]] == ["interpret", "retrieve", "draft", "verify"]


async def test_invented_citation_never_reaches_user(tmp_path):
    pipe, model, _ = make_pipeline([draft("invented"), draft("invented")], tmp_path)
    result = await pipe.ask("What does attention use?")
    assert result.disposition == "refused"
    assert "Attention uses queries" not in result.answer
    assert result.evidence == []


async def test_negative_semantic_verifier_withholds_draft(tmp_path):
    pipe, model, cid = make_pipeline([], tmp_path)
    rejected = {
        "supported": False,
        "addresses_question": False,
        "unsupported_claims": [0],
        "reason": "Not supported.",
    }
    model.replies = iter([draft(cid), rejected, draft(cid), rejected])
    result = await pipe.ask("What does attention use?")
    assert result.disposition == "refused"
    assert "queries, keys" not in result.answer


async def test_no_lexical_evidence_refuses_without_calling_provider(tmp_path):
    pipe, model, _ = make_pipeline([], tmp_path)
    result = await pipe.ask("zqxwvu")
    assert result.disposition == "refused"
    assert model.calls == []
    assert result.tokens_in == 0


async def test_provider_failure_is_not_an_evidence_refusal(tmp_path):
    pipe, model, _ = make_pipeline([ProviderError("rate_limited", "Rate limited.")], tmp_path)
    result = await pipe.ask("What does attention use?")
    assert result.status == "rate_limited"
    assert result.disposition == "unavailable"
    assert result.tokens_in is None


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
async def test_invalid_question_is_rejected_before_provider(tmp_path, question):
    pipe, model, _ = make_pipeline([], tmp_path)
    with pytest.raises(ValueError):
        await pipe.ask(question)
    assert not model.calls


async def test_fabricated_quote_is_rejected_even_when_citation_id_exists(tmp_path):
    pipe, model, cid = make_pipeline([], tmp_path)
    answer = draft(cid)
    answer["claims"][0]["citations"][0]["quote"] = "this quotation is invented"
    model.replies = iter([answer, answer])
    result = await pipe.ask("What does attention use?")
    assert result.disposition == "refused"
    assert result.reason == "invalid_citations"


async def test_whitespace_quote_cannot_support_a_claim(tmp_path):
    pipe, model, cid = make_pipeline([], tmp_path)
    answer = draft(cid)
    answer["claims"][0]["citations"][0]["quote"] = "    "
    model.replies = iter([answer, answer])
    result = await pipe.ask("What does attention use?")
    assert result.disposition == "refused"
    assert result.reason == "invalid_citations"


async def test_whitespace_claim_cannot_be_a_verified_answer(tmp_path):
    pipe, model, cid = make_pipeline([], tmp_path)
    answer = draft(cid)
    answer["claims"][0]["text"] = "   "
    model.replies = iter([answer, answer])
    result = await pipe.ask("What does attention use?")
    assert result.disposition == "refused"


async def test_deadline_cancels_slow_model_and_keeps_terminal_trace(tmp_path):
    import asyncio

    class SlowModel:
        async def complete(self, messages, *, stage, trace):
            await asyncio.sleep(60)

    pipe, _, _ = make_pipeline([], tmp_path)
    pipe.model = SlowModel()
    pipe.deadline = 0.02
    result = await pipe.ask("What does attention use?")
    assert result.status == "timeout"
    assert result.tokens_in is None
    assert (tmp_path / f"{result.request_id}.json").exists()


async def test_verifier_rejection_triggers_one_bounded_retrieval_expansion(tmp_path):
    class SearchSpy:
        def __init__(self, hits):
            self.hits = hits
            self.calls = []

        def search(self, question, *, k, setting, expanded=False):
            self.calls.append((setting, expanded, k))
            return self.hits

    base, model, cid = make_pipeline([], tmp_path)
    search = SearchSpy(base.retriever.search("attention", k=1))
    base.retriever = search
    base.retrieval_setting = "hybrid-minilm220-rrf-k4-v1"
    model.replies = iter(
        [
            draft(cid),
            {
                "supported": False,
                "addresses_question": False,
                "unsupported_claims": [0],
                "reason": "Needs broader evidence.",
            },
            draft(cid),
            {
                "supported": True,
                "addresses_question": True,
                "unsupported_claims": [],
                "reason": "Supported.",
            },
        ]
    )
    result = await base.ask("What does attention use?")
    assert result.disposition == "answered"
    assert search.calls == [
        ("hybrid-minilm220-rrf-k4-v1", False, 4),
        ("hybrid-minilm220-rrf-k4-v1", True, 6),
    ]
    assert model.calls == ["draft", "verify", "draft", "verify"]
    record = json.loads((tmp_path / f"{result.request_id}.json").read_text())
    assert [e["stage"] for e in record["events"]].count("retrieve") == 2
