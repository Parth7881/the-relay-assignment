import json

import httpx
import pytest

from relay.config import Settings
from relay.provider import GroqProvider, ProviderError


def settings():
    return Settings(_env_file=None, groq_api_key="fixture-secret-not-real")


async def test_stream_records_usage_headers_without_leaking_key():
    events = []
    body = "\n\n".join(
        [
            "data: " + json.dumps({"choices": [{"delta": {"content": '{"ok":'}}]}),
            "data: "
            + json.dumps(
                {
                    "choices": [{"delta": {"content": "true}"}, "finish_reason": "stop"}],
                    "x_groq": {"usage": {"prompt_tokens": 19, "completion_tokens": 6}},
                }
            ),
            "data: [DONE]",
            "",
        ]
    )

    def handle(request):
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert request.url.host == "api.groq.com"
        return httpx.Response(
            200,
            text=body,
            headers={
                "content-type": "text/event-stream",
                "x-ratelimit-remaining-tokens": "100",
                "set-cookie": "do-not-log",
                "authorization": "secret",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        model = GroqProvider(settings(), client)
        reply = await model.complete(
            [{"role": "user", "content": "JSON please"}], stage="draft", trace=events
        )
    assert reply.text == '{"ok":true}'
    assert (reply.tokens_in, reply.tokens_out) == (19, 6)
    assert reply.first_token_ms is not None
    assert events[0]["headers"] == {"x-ratelimit-remaining-tokens": "100"}
    assert "fixture-secret" not in json.dumps(events)


async def test_429_is_captured_without_hidden_retries():
    events, calls = [], []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            429, json={"error": {"message": "limited"}}, headers={"retry-after": "12"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError) as caught:
            await GroqProvider(settings(), client).complete([], stage="draft", trace=events)
    assert caught.value.status == "rate_limited"
    assert len(calls) == 1
    assert events[0]["headers"]["retry-after"] == "12"
    assert events[0]["http_status"] == 429


async def test_truncated_stream_cannot_become_complete_answer():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text='data: {"choices": []}\n\n')
        )
    ) as client:
        with pytest.raises(ProviderError, match="stream"):
            await GroqProvider(settings(), client).complete([], stage="draft", trace=[])


def test_missing_key_error_never_prints_secret():
    config = Settings(_env_file=None, groq_api_key="")
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        config.require_key()
    assert "fixture-secret" not in repr(settings())


async def test_json_mode_error_is_classified_without_saving_error_body():
    trace = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                400,
                json={"error": {"message": "messages must contain the word json. fixture-secret"}},
            )
        )
    ) as client:
        with pytest.raises(ProviderError) as caught:
            await GroqProvider(settings(), client).complete([], stage="calibrate", trace=trace)
    assert not caught.value.retryable
    assert trace[0]["error_category"] == "json_mode_prompt"
    assert "fixture-secret" not in json.dumps(trace)


@pytest.mark.parametrize(
    "event", [[], {"choices": [{"delta": None}]}, {"choices": [], "usage": [1]}]
)
async def test_wrong_shaped_sse_is_a_recorded_provider_error(event):
    events = []
    stream = "data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=stream))
    ) as client:
        with pytest.raises(ProviderError):
            await GroqProvider(settings(), client).complete([], stage="draft", trace=events)
    assert events[0]["status"] == "error"
    assert events[0]["total_ms"] >= 0


async def test_malformed_sse_keeps_terminal_pipeline_record(tmp_path):
    from relay.corpus import PAPERS, chunk_page
    from relay.pipeline import Pipeline
    from relay.retrieval import Retriever

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="data: []\n\n"))
    ) as client:
        result = await Pipeline(
            Retriever(chunk_page(PAPERS[0], 1, "Attention uses queries keys and values.")),
            GroqProvider(settings(), client),
            tmp_path,
        ).ask("What does attention use?")
    assert result.status == "error"
    record = json.loads((tmp_path / f"{result.request_id}.json").read_text())
    assert record["attempts"][0]["status"] == "error"
    assert record["result"]["disposition"] == "unavailable"


async def test_invalid_usage_does_not_mark_attempt_successful():
    stream = (
        'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":[],"completion_tokens":2}}\n\ndata: [DONE]\n\n'
    )
    events = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=stream))
    ) as client:
        with pytest.raises(ProviderError):
            await GroqProvider(settings(), client).complete([], stage="draft", trace=events)
    assert events[0]["status"] == "error"
