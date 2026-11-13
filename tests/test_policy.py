import asyncio

import pytest

from relay.config import Settings
from relay.policy import Admission, Budget, ManagedModel, retry_after
from relay.provider import ModelReply, ProviderError


def config(**kwargs):
    return Settings(_env_file=None, groq_api_key="fixture", **kwargs)


def test_budget_reserves_verification_and_survives_restart(tmp_path):
    path = tmp_path / "budget.sqlite3"
    settings = config(relay_rpd=2, relay_tpd=1000, relay_tpm=1000)
    budget = Budget(path, settings)
    draft, verify = budget.reserve_pair(100, 200)
    budget.start(draft, 100)
    budget.settle(draft, 80)
    restarted = Budget(path, settings)
    with pytest.raises(ProviderError, match="daily"):
        restarted.reserve_pair(100, 100)
    restarted.start(verify, 200)
    restarted.settle(verify, 150)
    assert restarted.usage()["day_requests"] == 2
    assert restarted.usage()["day_tokens"] == 230


def test_minute_rejection_does_not_consume_verifier_hold(tmp_path):
    budget = Budget(tmp_path / "b.db", config(relay_rpm=1))
    draft, verify = budget.reserve_pair(100, 100)
    budget.start(draft, 100)
    with pytest.raises(ProviderError, match="minute"):
        budget.start(verify, 100)
    budget.release(verify)
    assert budget.usage()["day_requests"] == 1


async def test_fifo_queue_overflow_and_cancel_cleanup():
    gate = Admission(concurrency=1, capacity=1, wait_seconds=0.1)
    order = []
    async with gate.enter({}):

        async def waiter():
            async with gate.enter({}):
                order.append("second")

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        with pytest.raises(ProviderError, match="queue_full"):
            async with gate.enter({}):
                pass
    await task
    assert order == ["second"]
    async with gate.enter({}):
        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert gate.active == 0 and not gate.waiters


async def test_retry_is_bounded_and_charged(tmp_path):
    class Flaky:
        async def complete(self, messages, *, stage, trace):
            trace.append({"status": "error", "http_status": 503, "headers": {}})
            raise ProviderError("error", "unavailable", retryable=True)

    budget = Budget(tmp_path / "b.db", config())
    model = ManagedModel(Flaky(), budget, config(), sleep=lambda _: asyncio.sleep(0))
    trace = []
    with pytest.raises(ProviderError):
        await model.complete([{"content": "hi"}], stage="draft", trace=trace)
    model.close()
    assert len(trace) == 2
    assert model.retries == 1
    assert budget.usage()["day_requests"] == 2


async def test_daily_limit_never_retries(tmp_path):
    class Limited:
        async def complete(self, messages, *, stage, trace):
            trace.append({"status": "rate_limited", "headers": {}})
            raise ProviderError("rate_limited", "daily_budget", retryable=False)

    model = ManagedModel(Limited(), Budget(tmp_path / "b.db", config()), config())
    trace = []
    with pytest.raises(ProviderError):
        await model.complete([], stage="draft", trace=trace)
    model.close()
    assert len(trace) == 1


def test_retry_after_parsing():
    assert retry_after("2.5") == 2.5
    assert retry_after("garbage") is None
    assert retry_after("-3") is None


def test_rolling_windows_and_shared_connection_atomic_reservation(tmp_path):
    now = [100000.0]
    settings = config(relay_rpd=2, relay_rpm=1)
    first = Budget(tmp_path / "shared.db", settings, clock=lambda: now[0])
    other = Budget(tmp_path / "shared.db", settings, clock=lambda: now[0])
    draft, verify = first.reserve_pair(50, 50)
    with pytest.raises(ProviderError):
        other.reserve_retry(1)
    first.start(draft, 50)
    now[0] += 61
    other.start(verify, 50)
    assert other.usage()["minute_requests"] == 1
    now[0] += 86401
    assert other.usage()["day_requests"] == 0


async def test_queue_timeout_releases_waiter():
    gate = Admission(1, 1, 0.01)
    metrics = {}
    async with gate.enter({}):
        with pytest.raises(ProviderError, match="queue_timeout"):
            async with gate.enter(metrics):
                pass
    assert gate.active == 0 and not gate.waiters
    assert metrics["queue_outcome"] == "timeout"


def test_observed_lower_provider_limits_are_persistent_caps(tmp_path):
    settings = config()
    budget = Budget(tmp_path / "b.db", settings)
    budget.observe_headers({"x-ratelimit-limit-tokens": "80", "x-ratelimit-limit-requests": "1"})
    restarted = Budget(tmp_path / "b.db", settings)
    with pytest.raises(ProviderError, match="daily"):
        restarted.reserve_pair(10, 10)
    key = restarted.reserve_retry(90)
    with pytest.raises(ProviderError, match="minute"):
        restarted.start(key, 90)


async def test_rate_limit_retry_after_and_terminal_cooldown(tmp_path):
    now = [100.0]
    waits = []
    budget = Budget(tmp_path / "b.db", config(), clock=lambda: now[0])

    class Limited:
        async def complete(self, messages, *, stage, trace):
            trace.append(
                {"status": "rate_limited", "http_status": 429, "headers": {"retry-after": "3"}}
            )
            raise ProviderError("rate_limited", "limited", retryable=True)

    async def advance(delay):
        waits.append(delay)
        now[0] += delay

    model = ManagedModel(Limited(), budget, config(), sleep=advance)
    trace = []
    with pytest.raises(ProviderError):
        await model.complete([], stage="draft", trace=trace)
    model.close()
    assert waits == [3] and len(trace) == 2
    key = budget.reserve_retry(10)
    with pytest.raises(ProviderError, match="cooldown"):
        budget.start(key, 10)


async def test_deadline_cancels_retry_sleep_and_releases_unused_hold(tmp_path):
    class Limited:
        async def complete(self, messages, *, stage, trace):
            trace.append(
                {"status": "rate_limited", "http_status": 429, "headers": {"retry-after": "100"}}
            )
            raise ProviderError("rate_limited", "limited", retryable=True)

    budget = Budget(tmp_path / "b.db", config())
    model = ManagedModel(Limited(), budget, config())
    trace = []
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await model.complete([], stage="draft", trace=trace)
    model.close()
    assert len(trace) == 1 and budget.usage()["day_requests"] == 1


async def test_success_reconciles_usage_releases_unused_verifier(tmp_path):
    class Model:
        async def complete(self, messages, *, stage, trace):
            trace.append({"status": "ok", "tokens_in": 10, "tokens_out": 5})
            return ModelReply(text="{}", total_ms=1, model="fixture", tokens_in=10, tokens_out=5)

    budget = Budget(tmp_path / "b.db", config())
    model = ManagedModel(Model(), budget, config())
    await model.complete([], stage="draft", trace=[])
    model.close()
    assert budget.usage()["day_tokens"] == 15
    assert budget.usage()["day_requests"] == 1


async def test_second_draft_releases_abandoned_verifier_hold(tmp_path):
    class Model:
        async def complete(self, messages, *, stage, trace):
            trace.append({"status": "ok", "tokens_in": 10, "tokens_out": 5})
            return ModelReply(
                text='{"refused":true,"claims":[]}',
                total_ms=1,
                model="fixture",
                tokens_in=10,
                tokens_out=5,
            )

    settings = config(relay_rpd=3, relay_tpd=100000)
    budget = Budget(tmp_path / "b.db", settings)
    model = ManagedModel(Model(), budget, settings)
    await model.complete([], stage="draft", trace=[])
    # First draft refused, so Pipeline never consumes its reserved verifier.
    await model.complete([], stage="draft", trace=[])
    assert budget.usage()["day_requests"] == 3  # 2 attempts + current verifier hold
    model.close()
    assert budget.usage()["day_requests"] == 2


async def test_evaluation_model_waits_once_for_minute_capacity(tmp_path):
    now = [1000.0]
    waits = []
    settings = config(relay_tpm=1000, relay_max_output_tokens=128)
    budget = Budget(tmp_path / "b.db", settings, clock=lambda: now[0])
    existing = budget.reserve_retry(900)
    budget.start(existing, 900)

    class Model:
        async def complete(self, messages, *, stage, trace):
            trace.append({"status": "ok", "tokens_in": 10, "tokens_out": 5})
            return ModelReply(
                text='{"refused":true,"claims":[]}',
                total_ms=1,
                model="fixture",
                tokens_in=10,
                tokens_out=5,
            )

    async def advance(delay):
        waits.append(delay)
        now[0] += delay

    trace = []
    model = ManagedModel(Model(), budget, settings, sleep=advance, wait_for_minute_capacity=True)
    await model.complete([{"content": "small"}], stage="draft", trace=trace)
    model.close()
    assert 60 <= waits[0] < 61
    assert trace[0]["capacity_wait_ms"] == pytest.approx(waits[0] * 1000)
    assert budget.usage()["minute_requests"] == 1


async def test_evaluation_model_recomputes_capacity_after_reset_boundary_race(tmp_path):
    now = [1000.0]
    waits = []
    settings = config(relay_tpm=1000, relay_max_output_tokens=128)
    budget = Budget(tmp_path / "b.db", settings, clock=lambda: now[0])
    existing = budget.reserve_retry(900)
    budget.start(existing, 900)

    class Model:
        async def complete(self, messages, *, stage, trace):
            trace.append({"status": "ok", "tokens_in": 10, "tokens_out": 5})
            return ModelReply(text="{}", total_ms=1, model="fixture", tokens_in=10, tokens_out=5)

    async def undershoot_first_boundary(delay):
        waits.append(delay)
        now[0] += delay - 0.02 if len(waits) == 1 else delay

    trace = []
    model = ManagedModel(
        Model(),
        budget,
        settings,
        sleep=undershoot_first_boundary,
        wait_for_minute_capacity=True,
    )
    await model.complete([{"content": "small"}], stage="draft", trace=trace)
    model.close()
    assert len(waits) == 2
    assert trace[0]["capacity_wait_ms"] == pytest.approx(sum(waits) * 1000)
