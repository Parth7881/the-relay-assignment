"""Single-process FIFO admission and transactional, persistent protective quotas.

The rolling 24-hour ledger is deliberately NOT a replica of Groq's reset algorithm.
Unknown token usage remains charged at its estimate. Crashed reservations expire after
24 hours; they are never automatically refunded on restart.
"""

import asyncio
import math
import random
import sqlite3
import time
from collections import deque
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from uuid import uuid4

from relay.config import Settings
from relay.provider import Model, ProviderError


def retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


class Admission:
    def __init__(self, concurrency: int, capacity: int, wait_seconds: float):
        self.concurrency, self.capacity, self.wait_seconds = concurrency, capacity, wait_seconds
        self.active = 0
        self.waiters: deque[asyncio.Future] = deque()

    def _release(self):
        self.active -= 1
        while self.waiters:
            waiter = self.waiters.popleft()
            if not waiter.done():
                self.active += 1
                waiter.set_result(None)
                break

    @asynccontextmanager
    async def enter(self, metrics: dict):
        start = time.perf_counter()
        metrics.update(queue_depth=len(self.waiters), queue_wait_ms=0, queue_outcome="admitted")
        if self.active < self.concurrency and not self.waiters:
            self.active += 1
        else:
            if len(self.waiters) >= self.capacity:
                metrics["queue_outcome"] = "full"
                raise ProviderError("rate_limited", "queue_full")
            future = asyncio.get_running_loop().create_future()
            self.waiters.append(future)
            try:
                async with asyncio.timeout(self.wait_seconds):
                    await asyncio.shield(future)
            except (TimeoutError, asyncio.CancelledError) as exc:
                if future in self.waiters:
                    self.waiters.remove(future)
                    future.cancel()
                elif future.done() and not future.cancelled():
                    self._release()  # cancellation raced with a granted permit
                metrics["queue_wait_ms"] = (time.perf_counter() - start) * 1000
                metrics["queue_outcome"] = (
                    "timeout" if isinstance(exc, TimeoutError) else "cancelled"
                )
                if isinstance(exc, TimeoutError):
                    raise ProviderError("timeout", "queue_timeout") from exc
                raise
        metrics["queue_wait_ms"] = (time.perf_counter() - start) * 1000
        try:
            yield
        finally:
            self._release()


class Budget:
    def __init__(self, path: Path, settings: Settings, *, clock=time.time):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.settings, self.clock = path, settings, clock
        with self._transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS charges "
                "(id TEXT PRIMARY KEY, created REAL, tokens INTEGER, kind TEXT)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS cooldown (id INTEGER PRIMARY KEY, until REAL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS ceilings (name TEXT PRIMARY KEY, amount INTEGER)"
            )

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=1)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _usage(self, db):
        now = self.clock()
        # Retain rows for auditing; all windows use epoch UTC, not local midnight.
        day = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(tokens),0) FROM charges WHERE created > ?",
            (now - 86400,),
        ).fetchone()
        minute = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(tokens),0) FROM charges "
            "WHERE created > ? AND kind='attempt'",
            (now - 60,),
        ).fetchone()
        return {
            "day_requests": day[0],
            "day_tokens": day[1],
            "minute_requests": minute[0],
            "minute_tokens": minute[1],
        }

    def usage(self):
        with self._transaction() as db:
            return self._usage(db)

    def minute_wait_seconds(self, tokens: int) -> float:
        """Return the earliest bounded wait after which one attempt can fit."""
        with self._transaction() as db:
            token_cap = self._cap(db, "tpm", self.settings.relay_tpm)
            if tokens > token_cap or self.settings.relay_rpm < 1:
                raise ProviderError("rate_limited", "request_exceeds_minute_budget")
            now = self.clock()
            rows = db.execute(
                "SELECT created,tokens FROM charges "
                "WHERE created > ? AND kind='attempt' ORDER BY created",
                (now - 60,),
            ).fetchall()
            count, total = len(rows), sum(row[1] for row in rows)
            if count + 1 <= self.settings.relay_rpm and total + tokens <= token_cap:
                return 0
            for created in sorted({row[0] for row in rows}):
                expired = [row for row in rows if row[0] == created]
                count -= len(expired)
                total -= sum(row[1] for row in expired)
                if count + 1 <= self.settings.relay_rpm and total + tokens <= token_cap:
                    return max(0, created + 60 - now) + 0.01
        raise ProviderError("rate_limited", "minute_budget_exhausted")

    def observe_headers(self, headers: dict):
        # Groq request ceiling is DAILY; token ceiling is MINUTELY. Never infer RPM here.
        with self._transaction() as db:
            for header, name in (
                ("x-ratelimit-limit-requests", "rpd"),
                ("x-ratelimit-limit-tokens", "tpm"),
            ):
                value = headers.get(header, "")
                if (
                    isinstance(value, str)
                    and value.isascii()
                    and value.isdigit()
                    and len(value) <= 9
                ):
                    db.execute(
                        "INSERT INTO ceilings VALUES(?,?) ON CONFLICT(name) DO UPDATE "
                        "SET amount=MIN(amount,excluded.amount)",
                        (name, int(value)),
                    )

    def _cap(self, db, name: str, configured: int) -> int:
        row = db.execute("SELECT amount FROM ceilings WHERE name=?", (name,)).fetchone()
        return min(configured, row[0]) if row else configured

    def reserve_pair(self, draft: int, verify: int) -> tuple[str, str]:
        return tuple(self._reserve([draft, verify]))

    def reserve_retry(self, tokens: int) -> str:
        return self._reserve([tokens])[0]

    def _reserve(self, tokens: list[int]) -> list[str]:
        with self._transaction() as db:
            usage = self._usage(db)
            if (
                usage["day_requests"] + len(tokens) > self._cap(db, "rpd", self.settings.relay_rpd)
                or usage["day_tokens"] + sum(tokens) > self.settings.relay_tpd
            ):
                raise ProviderError("rate_limited", "daily_budget_exhausted")
            ids = [uuid4().hex for _ in tokens]
            db.executemany(
                "INSERT INTO charges VALUES(?,?,?,'hold')",
                [(key, self.clock(), amount) for key, amount in zip(ids, tokens, strict=True)],
            )
            return ids

    def start(self, key: str, tokens: int):
        with self._transaction() as db:
            blocked = db.execute("SELECT until FROM cooldown WHERE id=1").fetchone()
            if blocked and blocked[0] > self.clock():
                raise ProviderError("rate_limited", "provider_cooldown")
            row = db.execute("SELECT tokens,kind FROM charges WHERE id=?", (key,)).fetchone()
            if not row or row[1] != "hold":
                raise ValueError("Invalid budget reservation")
            usage = self._usage(db)
            if usage["day_tokens"] - row[0] + tokens > self.settings.relay_tpd or usage[
                "day_requests"
            ] > self._cap(db, "rpd", self.settings.relay_rpd):
                raise ProviderError("rate_limited", "daily_budget_exhausted")
            if usage["minute_requests"] + 1 > self.settings.relay_rpm or usage[
                "minute_tokens"
            ] + tokens > self._cap(db, "tpm", self.settings.relay_tpm):
                raise ProviderError("rate_limited", "minute_budget_exhausted")
            db.execute(
                "UPDATE charges SET kind='attempt', created=?,tokens=? WHERE id=?",
                (self.clock(), tokens, key),
            )

    def settle(self, key: str, actual: int | None):
        if actual is not None:
            with self._transaction() as db:
                db.execute(
                    "UPDATE charges SET tokens=? WHERE id=? AND kind='attempt'", (actual, key)
                )

    def release(self, key: str):
        with self._transaction() as db:
            db.execute("DELETE FROM charges WHERE id=? AND kind='hold'", (key,))

    def cool_down(self, seconds: float):
        with self._transaction() as db:
            db.execute(
                "INSERT INTO cooldown VALUES(1,?) ON CONFLICT(id) DO UPDATE "
                "SET until=MAX(until,excluded.until)",
                (self.clock() + seconds,),
            )


class ManagedModel:
    """One request's model session; all sessions share the same Budget ledger."""

    def __init__(
        self,
        model: Model,
        budget: Budget,
        settings: Settings,
        *,
        sleep=asyncio.sleep,
        max_attempts: int = 2,
        wait_for_minute_capacity: bool = False,
    ):
        self.model, self.budget, self.settings, self.sleep = model, budget, settings, sleep
        self.holds: list[str] = []
        self.verify: str | None = None
        self.retries = 0
        self.max_attempts = max_attempts
        self.wait_for_minute_capacity = wait_for_minute_capacity

    def estimate(self, messages: list[dict]) -> int:
        # Explicit heuristic, NOT tokenizer measurement. Non-ASCII gets a larger byte count.
        size = sum(len(m.get("content", "").encode("utf-8")) for m in messages)
        return math.ceil(size / 3) + 32 * len(messages) + self.settings.relay_max_output_tokens

    async def complete(self, messages: list[dict], *, stage: str, trace: list[dict]):
        estimate = self.estimate(messages)
        if stage == "draft":
            # A refused or invalid draft never consumes its reserved verifier.
            # Release that abandoned hold before reserving the one repair pair.
            if self.verify:
                self.budget.release(self.verify)
                self.verify = None
            key, self.verify = self.budget.reserve_pair(
                estimate, estimate + 2 * self.settings.relay_max_output_tokens + 512
            )
            self.holds.extend([key, self.verify])
        elif stage == "verify" and self.verify:
            key, self.verify = self.verify, None
        else:
            key = self.budget.reserve_retry(estimate)
            self.holds.append(key)
        for attempt in range(self.max_attempts):
            capacity_wait = 0.0
            for capacity_attempt in range(3):
                try:
                    self.budget.start(key, estimate)
                    break
                except ProviderError as exc:
                    may_wait = (
                        self.wait_for_minute_capacity
                        and str(exc) == "minute_budget_exhausted"
                        and capacity_attempt < 2
                    )
                    if not may_wait:
                        raise
                    delay = self.budget.minute_wait_seconds(estimate)
                    capacity_wait += delay
                    await self.sleep(delay)
            before = len(trace)
            failure = None
            try:
                return await self.model.complete(messages, stage=stage, trace=trace)
            except ProviderError as exc:
                failure = exc
                if not exc.retryable or attempt + 1 == self.max_attempts or self.retries >= 2:
                    raise
            finally:
                if len(trace) > before:
                    event = trace[-1]
                    event.update(
                        attempt=attempt + 1,
                        reserved_tokens=estimate,
                        charge_id=key,
                        capacity_wait_ms=capacity_wait * 1000,
                    )
                    self.budget.observe_headers(event.get("headers", {}))
                    used = [event.get("tokens_in"), event.get("tokens_out")]
                    self.budget.settle(
                        key, sum(used) if all(type(v) is int for v in used) else None
                    )
                    if event.get("http_status") == 429:
                        wait = retry_after(event.get("headers", {}).get("retry-after"))
                        self.budget.cool_down(
                            86400
                            if event.get("limit_scope") == "day"
                            else (wait if wait is not None else 1)
                        )
            delay = (
                retry_after(trace[-1].get("headers", {}).get("retry-after"))
                if len(trace) > before
                else None
            )
            if delay is None:
                delay = 0.5 * (2**attempt) + random.uniform(0, 0.25)
            if failure and failure.status == "rate_limited":
                # Match the shared one-second fallback used when 429 has no Retry-After.
                if retry_after(trace[-1].get("headers", {}).get("retry-after")) is None:
                    delay = max(1, delay)
                self.budget.cool_down(delay)
            trace[-1]["retry_delay_ms"] = delay * 1000
            wait_start = time.perf_counter()
            try:
                await self.sleep(delay)
            finally:
                trace[-1]["retry_wait_ms"] = (time.perf_counter() - wait_start) * 1000
            key = self.budget.reserve_retry(estimate)
            self.holds.append(key)
            self.retries += 1
        raise AssertionError("unreachable")

    def close(self):
        for key in self.holds:
            self.budget.release(key)
