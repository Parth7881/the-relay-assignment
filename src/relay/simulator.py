"""Loopback-only streaming stand-in. Synthetic responses are never quality evidence."""

import asyncio
import json
import math
import random
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware


class Simulation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: int = 42
    first_token_ms: float = Field(default=600, ge=0, le=120000)
    tail_ms: float = Field(default=20, ge=0, le=120000)
    load_ms: float = Field(default=100, ge=0, le=10000)
    fail_every: int = Field(default=0, ge=0)
    rate_limit_every: int = Field(default=0, ge=0)
    retry_after_seconds: float = Field(default=1, ge=0, le=86400)
    rpm: int = Field(default=30, ge=1)
    tpm: int = Field(default=8000, ge=1)
    rpd: int = Field(default=1000, ge=0)
    tpd: int = Field(default=200000, ge=0)


def create_simulator(
    config: Simulation, *, profile: Path | None = None, replay: Path | None = None
) -> FastAPI:
    samples = []
    if profile:
        document = json.loads(profile.read_text(encoding="utf-8"))
        samples = document["samples"]
        if not samples or any(
            not isinstance(s, dict)
            or not all(
                type(s.get(k)) in (int, float) and math.isfinite(s[k]) and 0 <= s[k] <= 120000
                for k in ("first_token_ms", "tail_ms")
            )
            for s in samples
        ):
            raise ValueError("Invalid calibration samples")
    replies = {}
    if replay:
        record = json.loads(replay.read_text(encoding="utf-8"))
        replies = {
            a["stage"]: a["response"]
            for a in record["attempts"]
            if a.get("status") == "ok" and "response" in a
        }
    rng = random.Random(config.seed)
    app = FastAPI(title="Relay stand-in (synthetic)")
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )
    app.state.active = 0
    app.state.authorized_requests = 0
    calls = 0
    history: deque[tuple[float, int]] = deque()

    @app.get("/health")
    async def health():
        return {
            "source": "stand-in",
            "calibrated": bool(samples),
            "samples": len(samples),
            "config": config.model_dump(),
            "response_mode": "replay" if replies else "refusal",
        }

    @app.post("/openai/v1/chat/completions")
    async def complete(request: Request):
        nonlocal calls
        if request.headers.get("authorization"):
            app.state.authorized_requests += 1
            return JSONResponse({"error": {"message": "Do not send credentials to stand-in"}}, 400)
        media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if media_type != "application/json":
            return JSONResponse({"error": {"message": "application/json required"}}, 415)
        raw = bytearray()
        async for piece in request.stream():
            raw.extend(piece)
            if len(raw) > 128000:
                return JSONResponse({"error": {"message": "body too large"}}, 413)
        try:
            body = json.loads(raw)
            messages = body["messages"]
            if not isinstance(messages, list) or len(messages) > 16:
                raise ValueError
            if any(
                not isinstance(m, dict) or not isinstance(m.get("content"), str) for m in messages
            ):
                raise ValueError
            output_cap = body.get("max_completion_tokens", 1200)
            if type(output_cap) is not int or not 1 <= output_cap <= 4096:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            return JSONResponse({"error": {"message": "invalid request"}}, 400)
        now = time.monotonic()
        while history and history[0][0] <= now - 86400:
            history.popleft()
        minute = [(stamp, tokens) for stamp, tokens in history if stamp > now - 60]
        minute_tokens, day_tokens = sum(t for _, t in minute), sum(t for _, t in history)
        tokens_in = math.ceil(
            sum(len(m["content"].encode("utf-8")) for m in messages) / 3
        ) + 32 * len(messages)
        headers = {
            "x-ratelimit-limit-requests": str(config.rpd),
            "x-ratelimit-limit-tokens": str(config.tpm),
        }

        def limited(scope, delay):
            return JSONResponse(
                {"error": {"message": scope}}, 429, headers={**headers, "retry-after": str(delay)}
            )

        calls += 1
        if len(history) >= config.rpd or day_tokens + tokens_in + output_cap > config.tpd:
            return limited("daily_budget exhausted", 86400)
        if len(minute) >= config.rpm or minute_tokens + tokens_in + output_cap > config.tpm:
            return limited(
                "minute_budget exhausted", max(0.01, 60 - (now - minute[0][0])) if minute else 60
            )
        if config.rate_limit_every and calls % config.rate_limit_every == 0:
            return limited("injected rate limit", config.retry_after_seconds)
        if config.fail_every and calls % config.fail_every == 0:
            history.append((now, tokens_in + output_cap))
            return JSONResponse({"error": {"message": "injected outage"}}, 503, headers=headers)
        stage = (
            "verify"
            if messages and messages[0]["content"].startswith("Independently check")
            else "draft"
        )
        reply = replies.get(
            stage,
            '{"refused":true,"claims":[]}'
            if stage == "draft"
            else (
                '{"supported":false,"addresses_question":false,'
                '"unsupported_claims":[],"reason":"Synthetic stand-in"}'
            ),
        )
        tokens_out = math.ceil(len(reply.encode("utf-8")) / 3)
        truncated = tokens_out > output_cap
        if truncated:
            reply, tokens_out = reply[: output_cap * 3], output_cap
        # Reserve full output allowance immediately; settle only on a completed stream.
        reservation = (now, tokens_in + output_cap)
        history.append(reservation)
        app.state.active += 1
        sample = (
            rng.choice(samples)
            if samples
            else {"first_token_ms": config.first_token_ms, "tail_ms": config.tail_ms}
        )
        first = sample["first_token_ms"] + config.load_ms * max(0, app.state.active - 1)
        headers.update(
            {
                # Configured delay, not a measured client latency; useful for reproducibility.
                "x-relay-simulated-first-delay-ms": str(first),
                "x-ratelimit-remaining-requests": str(max(0, config.rpd - len(history))),
                "x-ratelimit-remaining-tokens": str(
                    max(0, config.tpm - minute_tokens - tokens_in - output_cap)
                ),
            }
        )

        async def stream():
            try:
                await asyncio.sleep(first / 1000)
                size = max(1, math.ceil(len(reply) / 8))
                pieces = [reply[i : i + size] for i in range(0, len(reply), size)]
                for i, piece in enumerate(pieces):
                    if i:
                        await asyncio.sleep(sample["tail_ms"] / max(1, len(pieces) - 1) / 1000)
                    event = {
                        "model": "relay-stand-in",
                        "choices": [{"delta": {"content": piece}, "finish_reason": None}],
                    }
                    yield "data: " + json.dumps(event) + "\n\n"
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "model": "relay-stand-in",
                            "choices": [
                                {"delta": {}, "finish_reason": "length" if truncated else "stop"}
                            ],
                            "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
                        }
                    )
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"
                if reservation in history:
                    index = history.index(reservation)
                    history[index] = (now, tokens_in + tokens_out)
            finally:
                app.state.active -= 1

        return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)

    return app
