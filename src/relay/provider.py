"""Groq streaming boundary: no hidden retries, no unverified streaming to users."""

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel

from relay.config import Settings

Status = Literal["ok", "rate_limited", "timeout", "error"]
URL = "https://api.groq.com/openai/v1/chat/completions"


class ProviderError(Exception):
    def __init__(self, status: Status, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class ModelReply(BaseModel):
    text: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    first_token_ms: float | None = None
    total_ms: float
    model: str


class Model(Protocol):
    async def complete(
        self, messages: list[dict], *, stage: str, trace: list[dict]
    ) -> ModelReply: ...


class GroqProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        if settings.relay_source == "real":
            settings.require_key()
        self.settings = settings
        self.client = client

    async def complete(self, messages: list[dict], *, stage: str, trace: list[dict]) -> ModelReply:
        start = time.perf_counter()
        event = {
            "stage": stage,
            "source": self.settings.relay_source,
            "started_at": datetime.now(UTC).isoformat(),
            "model": self.settings.groq_model,
            "headers": {},
            "status": "error",
            "tokens_in": None,
            "tokens_out": None,
            "first_token_ms": None,
            "messages": messages,
            "attempt": 1,
            "chunk_arrivals_ms": [],
        }
        trace.append(event)
        payload = {
            "model": self.settings.groq_model,
            "messages": messages,
            "stream": True,
            "temperature": 0,
            "max_completion_tokens": self.settings.relay_max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        # Ask GPT-OSS to emit content without its separate reasoning stream.
        if self.settings.groq_model.startswith("openai/gpt-oss"):
            payload["reasoning_effort"] = "low"
            payload["include_reasoning"] = False
        text_parts, first, done, finish = [], None, False, None
        try:
            async with self.client.stream(
                "POST",
                URL
                if self.settings.relay_source == "real"
                else f"http://127.0.0.1:{self.settings.relay_simulator_port}/openai/v1/chat/completions",
                json=payload,
                headers={"Authorization": "Bearer " + self.settings.groq_api_key.get_secret_value()}
                if self.settings.relay_source == "real"
                else {},
                timeout=httpx.Timeout(10, connect=3, pool=3),
            ) as response:
                event["http_status"] = response.status_code
                event["headers"] = {
                    key: value
                    for key, value in response.headers.items()
                    if key.startswith("x-ratelimit-") or key in {"retry-after", "x-request-id"}
                }
                if response.status_code != 200:
                    # Classify bounded error text but never persist arbitrary error bodies.
                    raw_error = bytearray()
                    async for part in response.aiter_bytes():
                        raw_error.extend(part[: 8192 - len(raw_error)])
                        if len(raw_error) >= 8192:
                            break
                    error_text = raw_error.decode("utf-8", errors="replace").lower()
                    event["error_category"] = (
                        "json_mode_prompt"
                        if "json" in error_text and "must contain" in error_text
                        else "invalid_request"
                        if response.status_code == 400
                        else "provider_error"
                    )
                    daily = any(
                        term in error_text
                        for term in (
                            "tokens per day",
                            "requests per day",
                            "daily_budget",
                            "(tpd)",
                            "(rpd)",
                        )
                    )
                    event["limit_scope"] = "day" if daily else "unknown"
                    status: Status = "rate_limited" if response.status_code == 429 else "error"
                    raise ProviderError(
                        status,
                        "daily_budget_exhausted"
                        if daily
                        else f"Provider returned HTTP {response.status_code}.",
                        retryable=not daily and response.status_code in {429, 500, 502, 503, 504},
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        done = True
                        break
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        raise ProviderError("error", "Malformed stream event object.")
                    if data.get("error"):
                        raise ProviderError("error", "Groq stream reported an error.")
                    for field in ("model", "system_fingerprint"):
                        if isinstance(data.get(field), str):
                            event["returned_" + field] = data[field][:200]
                    metadata = data.get("x_groq")
                    if metadata is not None and not isinstance(metadata, dict):
                        raise ProviderError("error", "Malformed stream metadata.")
                    usage = data.get("usage")
                    if usage is None:
                        usage = (metadata or {}).get("usage")
                    if usage is not None:
                        if not isinstance(usage, dict):
                            raise ProviderError("error", "Malformed stream usage.")
                        for field in ("prompt_tokens", "completion_tokens"):
                            value = usage.get(field)
                            if value is not None and (type(value) is not int or value < 0):
                                raise ProviderError("error", "Invalid stream token count.")
                        event["tokens_in"] = usage.get("prompt_tokens")
                        event["tokens_out"] = usage.get("completion_tokens")
                    choices = data.get("choices", [])
                    if not isinstance(choices, list):
                        raise ProviderError("error", "Malformed stream choices.")
                    for choice in choices:
                        if not isinstance(choice, dict) or not isinstance(
                            choice.get("delta"), dict
                        ):
                            raise ProviderError("error", "Malformed stream content delta.")
                        finish = choice.get("finish_reason") or finish
                        content = choice["delta"].get("content")
                        if content is not None and not isinstance(content, str):
                            raise ProviderError("error", "Invalid stream content type.")
                        if content:
                            elapsed = (time.perf_counter() - start) * 1000
                            if first is None:
                                first = elapsed
                            event["chunk_arrivals_ms"].append(elapsed)
                            text_parts.append(content)
                            if sum(len(part) for part in text_parts) > 100_000:
                                raise ProviderError("error", "Model response exceeded size bound.")
                if not done or finish != "stop" or not text_parts:
                    raise ProviderError("error", "Incomplete or truncated model stream.")
            event["response"] = "".join(text_parts)
            reply = ModelReply(
                text=event["response"],
                tokens_in=event["tokens_in"],
                tokens_out=event["tokens_out"],
                first_token_ms=first,
                total_ms=(time.perf_counter() - start) * 1000,
                model=event.get("returned_model", self.settings.groq_model),
            )
            event["status"] = "ok"
            return reply
        except ProviderError as exc:
            event["status"] = exc.status
            raise
        except httpx.TimeoutException as exc:
            event["status"] = "timeout"
            raise ProviderError("timeout", "Groq request timed out.", retryable=True) from exc
        except httpx.TransportError as exc:
            raise ProviderError("error", "Provider transport failed.", retryable=True) from exc
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise ProviderError("error", "Groq connection or stream format failed.") from exc
        except asyncio.CancelledError:
            event["status"] = "timeout"
            raise
        finally:
            event["first_token_ms"] = first
            event["total_ms"] = (time.perf_counter() - start) * 1000
