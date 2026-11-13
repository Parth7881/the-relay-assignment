import json

import httpx
import pytest

from relay.config import Settings
from relay.provider import GroqProvider, ProviderError
from relay.simulator import Simulation, create_simulator


async def test_standin_streams_without_forwarding_key():
    app = create_simulator(Simulation(first_token_ms=0, tail_ms=0))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        trace = []
        model = GroqProvider(
            Settings(_env_file=None, groq_api_key="secret-test", relay_source="stand-in"), client
        )
        reply = await model.complete(
            [{"role": "user", "content": "question"}], stage="draft", trace=trace
        )
    assert json.loads(reply.text)["refused"] is True
    assert trace[0]["source"] == "stand-in"
    assert len(trace[0]["chunk_arrivals_ms"]) > 1
    assert reply.model == "relay-stand-in"
    assert app.state.authorized_requests == 0


@pytest.mark.parametrize(
    "options,expected",
    [({"fail_every": 1}, 503), ({"rate_limit_every": 1}, 429), ({"rpd": 0}, 429)],
)
async def test_failure_controls(options, expected):
    app = create_simulator(Simulation(**options))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        trace = []
        with pytest.raises(ProviderError) as caught:
            await GroqProvider(Settings(_env_file=None, relay_source="stand-in"), client).complete(
                [], stage="draft", trace=trace
            )
    assert trace[0]["http_status"] == expected
    if options.get("rpd") == 0:
        assert not caught.value.retryable


async def test_minute_token_limit_and_retry_after():
    app = create_simulator(Simulation(tpm=10))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/openai/v1/chat/completions",
            json={"messages": [{"content": "long " * 100}], "max_completion_tokens": 100},
        )
    assert response.status_code == 429
    assert float(response.headers["retry-after"]) > 0


async def test_standin_rejects_non_json_browser_simple_requests_without_mutating_quota():
    app = create_simulator(Simulation(rpd=1, first_token_ms=0, tail_ms=0))
    payload = json.dumps({"messages": [], "max_completion_tokens": 1}).encode()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        rejected = await client.post(
            "/openai/v1/chat/completions",
            content=payload,
            headers={"content-type": "text/plain"},
        )
        accepted = await client.post(
            "/openai/v1/chat/completions",
            json={"messages": [], "max_completion_tokens": 1},
        )

    assert rejected.status_code == 415
    assert accepted.status_code == 200


async def test_load_increases_latency_and_cancel_releases_active_stream():
    import asyncio

    app = create_simulator(Simulation(first_token_ms=1, tail_ms=1, load_ms=100))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:

        async def call():
            response = await client.post("/openai/v1/chat/completions", json={"messages": []})
            assert response.status_code == 200
            return float(response.headers["x-relay-simulated-first-delay-ms"])

        # Windows timer coalescing can obscure wall-time differences across short streams.
        # Check the actual scheduled delays; the live socket test separately checks delivery.
        delays = await asyncio.gather(call(), call())
        assert sorted(delays) == [1, 101]
    assert app.state.active == 0
    slow = create_simulator(Simulation(first_token_ms=1000))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=slow), base_url="http://localhost"
    ) as client:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.02):
                await client.post("/openai/v1/chat/completions", json={"messages": []})
    assert slow.state.active == 0


async def test_live_http_streaming_and_transient_recovery(tmp_path):
    import asyncio
    import socket
    import subprocess
    import sys

    from relay.policy import Budget, ManagedModel

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # Real loopback sockets are necessary: HTTPX ASGITransport buffers entire streams.
    code = (
        "import uvicorn; from relay.simulator import Simulation, create_simulator; "
        "uvicorn.run(create_simulator(Simulation(first_token_ms=20,tail_ms=120,fail_every=2)),"
        f"host='127.0.0.1',port={port},log_level='error')"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        code,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(100):
                try:
                    health = await client.get(f"http://127.0.0.1:{port}/health", timeout=0.2)
                    if health.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.05)
            else:
                pytest.fail("Local stand-in did not start")
            settings = Settings(_env_file=None, relay_source="stand-in", relay_simulator_port=port)
            provider = GroqProvider(settings, client)
            trace = []
            first = await provider.complete([], stage="probe", trace=trace)
            assert first.first_token_ms is not None
            assert first.total_ms - first.first_token_ms >= 70
            assert len(trace[0]["chunk_arrivals_ms"]) > 1
            managed = ManagedModel(provider, Budget(tmp_path / "budget.db", settings), settings)
            retry_trace = []
            reply = await managed.complete([], stage="probe", trace=retry_trace)
            managed.close()
            assert reply.text and [a["http_status"] for a in retry_trace] == [503, 200]
            assert [a["attempt"] for a in retry_trace] == [1, 2]
            assert retry_trace[0]["retry_wait_ms"] >= 490
    finally:
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=5)
