"""Part 5 load-measurement primitives; no provider is started or selected here."""

from __future__ import annotations

import asyncio
import csv
import json
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

MANDATORY_COLUMNS = (
    "request_id",
    "scenario",
    "source",
    "start_time",
    "first_token_ms",
    "total_ms",
    "status",
    "retries",
    "tokens_in",
    "tokens_out",
    "retrieval_setting",
    "answer_grade",
)

SUPPLEMENTARY_COLUMNS = (
    "run_id",
    "record_kind",
    "question_id",
    "grade_applicable",
    "outcome_reason",
    "disposition",
    "usage_known",
    "token_usage_source",
    "queue_depth_at_arrival",
    "peak_queue_length",
    "queue_ms",
    "working_ms",
    "retry_wait_ms",
    "provider_first_token_ms",
    "model_id",
    "limits_json",
    "limits_evidence_json",
)

SCENARIOS = {
    "steady",
    "burst",
    "sustained_overload",
    "minute_limit_halved",
    "daily_budget_exhausted",
}
SOURCES = {"real", "stand-in"}
STATUSES = {"ok", "rate_limited", "timeout", "error"}
ANSWER_GRADES = {"", "correct", "wrong", "refused_correctly", "refused_wrongly"}
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


async def preflight_target(client: httpx.AsyncClient, expected_source: str) -> dict[str, Any]:
    """Confirm the local API source before any measured question can be sent."""

    if expected_source not in SOURCES:
        raise ValueError(f"Invalid expected source: {expected_source}")
    response = await client.get("/health")
    response.raise_for_status()
    health = response.json()
    if not isinstance(health, dict) or health.get("source") != expected_source:
        observed = health.get("source") if isinstance(health, dict) else None
        raise ValueError(
            f"Relay target source {observed!r} did not match expected source {expected_source!r}"
        )
    return health


def enrich_row_from_server_trace(row: dict[str, Any], trace: dict[str, Any]) -> None:
    """Map observed server trace fields into reproducible CSV supplements."""

    queue = trace.get("queue") if isinstance(trace.get("queue"), dict) else {}
    attempts = trace.get("attempts") if isinstance(trace.get("attempts"), list) else []
    result = trace.get("result") if isinstance(trace.get("result"), dict) else {}
    queue_ms = queue.get("queue_wait_ms")
    server_total_ms = result.get("total_ms")
    row["queue_depth_at_arrival"] = queue.get("queue_depth")
    row["queue_ms"] = queue_ms
    row["working_ms"] = (
        max(0.0, server_total_ms - queue_ms)
        if isinstance(server_total_ms, (int, float)) and isinstance(queue_ms, (int, float))
        else None
    )
    row["retry_wait_ms"] = sum(
        attempt.get("retry_wait_ms", 0)
        for attempt in attempts
        if isinstance(attempt, dict) and isinstance(attempt.get("retry_wait_ms", 0), (int, float))
    )
    row["provider_first_token_ms"] = next(
        (
            attempt["first_token_ms"]
            for attempt in attempts
            if isinstance(attempt, dict) and isinstance(attempt.get("first_token_ms"), (int, float))
        ),
        None,
    )
    row["model_id"] = next(
        (
            attempt["model"]
            for attempt in attempts
            if isinstance(attempt, dict) and isinstance(attempt.get("model"), str)
        ),
        None,
    )
    row["disposition"] = result.get("disposition")
    usage_known = isinstance(row.get("tokens_in"), int) and isinstance(row.get("tokens_out"), int)
    row["usage_known"] = usage_known
    row["token_usage_source"] = "provider_response" if usage_known else "unknown"
    limit_evidence = []
    merged_limits: dict[str, str] = {}
    for attempt in attempts:
        if not isinstance(attempt, dict) or not isinstance(attempt.get("headers"), dict):
            continue
        headers = {
            key.lower(): value
            for key, value in attempt["headers"].items()
            if key.lower().startswith("x-ratelimit-")
        }
        if headers:
            merged_limits.update(headers)
            limit_evidence.append(
                {
                    "stage": attempt.get("stage"),
                    "attempt": attempt.get("attempt"),
                    "http_status": attempt.get("http_status"),
                    "headers": headers,
                }
            )
    row["limits_json"] = json.dumps(merged_limits, sort_keys=True) if merged_limits else ""
    row["limits_evidence_json"] = (
        json.dumps(limit_evidence, sort_keys=True) if limit_evidence else ""
    )


def server_trace_path(root: Path, request_id: object) -> Path | None:
    """Return a direct-child trace path only for a safe, bounded identifier."""

    if not isinstance(request_id, str) or not SAFE_REQUEST_ID.fullmatch(request_id):
        return None
    resolved_root = root.resolve()
    candidate = (resolved_root / f"{request_id}.json").resolve()
    return candidate if candidate.parent == resolved_root else None


def validate_load_target(base_url: str, *, source: str, allow_real: bool, count: int) -> None:
    """Keep the harness local and make hosted-provider use an explicit bounded choice."""

    parsed = urlparse(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Load target must be an http://127.0.0.1 or localhost service")
    if source not in SOURCES:
        raise ValueError(f"Invalid source: {source}")
    if count < 1:
        raise ValueError("count must be at least one")
    if source == "real" and not allow_real:
        raise ValueError("Real load runs require the explicit --allow-real flag")
    if source == "real" and count > 12:
        raise ValueError("Real load runs are capped at 12 requests")


def scenario_offsets(scenario: str, *, count: int, rate_per_minute: float) -> list[float]:
    """Return fixed dispatch offsets so completions cannot throttle offered load."""

    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    if count < 1:
        raise ValueError("count must be at least one")
    if rate_per_minute <= 0:
        raise ValueError("rate_per_minute must be positive")
    if scenario in {"burst", "daily_budget_exhausted"}:
        return [0.0] * count
    interval = 60.0 / rate_per_minute
    return [index * interval for index in range(count)]


def load_question_cases(path: Path) -> list[dict[str, str]]:
    """Load only the question set the user explicitly approved."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("review_status") != "approved_by_user":
        raise ValueError("Question set must have review_status=approved_by_user")
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("Approved question set is empty")
    cases = []
    for item in questions:
        question_id = item.get("id") if isinstance(item, dict) else None
        question = item.get("question") if isinstance(item, dict) else None
        if (
            not isinstance(question_id, str)
            or not isinstance(question, str)
            or not question.strip()
        ):
            raise ValueError("Each approved question requires an id and non-empty question")
        cases.append({"id": question_id, "question": question})
    return cases


def _validate_row(row: dict[str, Any]) -> None:
    missing = [name for name in MANDATORY_COLUMNS if name not in row]
    if missing:
        raise ValueError(f"Missing mandatory results columns: {', '.join(missing)}")
    if row["scenario"] not in SCENARIOS:
        raise ValueError(f"Invalid scenario: {row['scenario']}")
    if row["source"] not in SOURCES:
        raise ValueError(f"Invalid source: {row['source']}")
    if row["status"] not in STATUSES:
        raise ValueError(f"Invalid status: {row['status']}")
    grade = row["answer_grade"] if row["answer_grade"] is not None else ""
    if grade not in ANSWER_GRADES:
        raise ValueError(f"Invalid answer_grade: {grade}")


def write_results_csv(rows: list[dict[str, Any]], path: Path) -> None:
    """Write the mandatory PDF columns first, then reproducibility fields."""

    for row in rows:
        _validate_row(row)
    extras = sorted(
        {key for row in rows for key in row if key not in MANDATORY_COLUMNS + SUPPLEMENTARY_COLUMNS}
    )
    fieldnames = [*MANDATORY_COLUMNS, *SUPPLEMENTARY_COLUMNS, *extras]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


async def measure_request(
    client: httpx.AsyncClient,
    *,
    question_id: str,
    question: str,
    scenario: str,
    expected_source: str,
    retrieval_setting: str,
    run_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Measure first response content and completion at the load-client boundary."""

    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    if expected_source not in SOURCES:
        raise ValueError(f"Invalid expected source: {expected_source}")

    started_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    first_content_ms: float | None = None
    http_status: int | None = None
    response_headers: dict[str, str] = {}
    payload: dict[str, Any] = {}
    transport_error: str | None = None

    try:
        async with client.stream(
            "POST",
            "/api/ask",
            json={"question": question, "retrieval_setting": retrieval_setting},
        ) as response:
            http_status = response.status_code
            response_headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower().startswith(("retry-after", "x-ratelimit-"))
            }
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if chunk and first_content_ms is None:
                    first_content_ms = (time.perf_counter() - started) * 1000
                body.extend(chunk)
            if body:
                decoded = json.loads(body)
                if isinstance(decoded, dict):
                    payload = decoded
    except httpx.TimeoutException:
        transport_error = "client_timeout"
    except (httpx.HTTPError, json.JSONDecodeError):
        transport_error = "client_or_response_error"

    total_ms = (time.perf_counter() - started) * 1000
    if transport_error == "client_timeout":
        status = "timeout"
    elif transport_error or http_status is None:
        status = "error"
    elif http_status == 429:
        status = "rate_limited"
    elif http_status >= 400:
        status = "error"
    else:
        status = payload.get("status", "error")
        if status not in STATUSES:
            status = "error"

    returned_source = payload.get("source", expected_source)
    if returned_source != expected_source:
        raise ValueError(
            f"Response source {returned_source!r} did not match expected {expected_source!r}"
        )

    request_id = payload.get("request_id") or f"client-{uuid4().hex}"
    row = {
        "request_id": request_id,
        "scenario": scenario,
        "source": expected_source,
        "start_time": started_at,
        "first_token_ms": round(first_content_ms, 3) if first_content_ms is not None else None,
        "total_ms": round(total_ms, 3),
        "status": status,
        "retries": payload.get("retries", 0),
        "tokens_in": payload.get("tokens_in"),
        "tokens_out": payload.get("tokens_out"),
        "retrieval_setting": payload.get("retrieval_setting", retrieval_setting),
        "answer_grade": "",
        "run_id": run_id,
        "record_kind": "load",
        "question_id": question_id,
        "grade_applicable": status == "ok",
        "outcome_reason": payload.get("reason", transport_error or f"http_{http_status}"),
    }
    _validate_row(row)
    trace = {
        "schema_version": 1,
        "run_id": run_id,
        "question_id": question_id,
        "scenario": scenario,
        "source": expected_source,
        "request": {"question": question, "retrieval_setting": retrieval_setting},
        "client_timing": {
            "start_time": started_at,
            "first_content_ms": row["first_token_ms"],
            "total_ms": row["total_ms"],
        },
        "http_status": http_status,
        "response_headers": response_headers,
        "transport_error": transport_error,
        "response": payload,
    }
    return row, trace


async def run_load_experiment(
    client: httpx.AsyncClient,
    *,
    cases: list[dict[str, str]],
    scenario: str,
    source: str,
    retrieval_setting: str,
    count: int,
    rate_per_minute: float,
    output_root: Path,
    server_runs_dir: Path | None = None,
) -> dict[str, Any]:
    """Dispatch a fixed open-loop schedule and retain raw evidence plus results.csv."""

    if not cases:
        raise ValueError("At least one approved question is required")
    offsets = scenario_offsets(scenario, count=count, rate_per_minute=rate_per_minute)
    run_id = uuid4().hex
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    raw_path = run_dir / "raw.jsonl"
    started_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    write_lock = asyncio.Lock()

    async def one(index: int, offset: float):
        delay = offset - (time.perf_counter() - started)
        if delay > 0:
            await asyncio.sleep(delay)
        dispatched = time.perf_counter()
        case = cases[index % len(cases)]
        row, trace = await measure_request(
            client,
            question_id=case["id"],
            question=case["question"],
            scenario=scenario,
            expected_source=source,
            retrieval_setting=retrieval_setting,
            run_id=run_id,
        )
        if server_runs_dir is not None:
            observed_trace_path = server_trace_path(server_runs_dir, row["request_id"])
            if observed_trace_path is not None and observed_trace_path.is_file():
                server_trace = json.loads(observed_trace_path.read_text(encoding="utf-8"))
                enrich_row_from_server_trace(row, server_trace)
                retained_dir = run_dir / "server-traces"
                retained_dir.mkdir(exist_ok=True)
                retained_path = retained_dir / observed_trace_path.name
                shutil.copy2(observed_trace_path, retained_path)
                trace["server_trace_path"] = str(retained_path.relative_to(run_dir))
        trace["schedule"] = {
            "index": index,
            "offset_seconds": offset,
            "dispatch_lag_ms": round(max(0.0, dispatched - started - offset) * 1000, 3),
        }
        async with write_lock:
            with raw_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(trace, ensure_ascii=False) + "\n")
                handle.flush()
        return index, row

    scheduled = [asyncio.create_task(one(index, offset)) for index, offset in enumerate(offsets)]
    indexed_rows = await asyncio.gather(*scheduled)
    rows = [row for _, row in sorted(indexed_rows, key=lambda item: item[0])]
    duration = time.perf_counter() - started
    peak_queue = max(
        (
            row["queue_depth_at_arrival"]
            for row in rows
            if isinstance(row.get("queue_depth_at_arrival"), int)
        ),
        default=0,
    )
    for row in rows:
        row["run_duration_s"] = round(duration, 3)
        row["offered_count"] = count
        row["offered_rate_per_min"] = rate_per_minute
        row["peak_queue_length"] = peak_queue
    results_path = run_dir / "results.csv"
    write_results_csv(rows, results_path)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "scenario": scenario,
        "source": source,
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "requests": count,
        "rate_per_minute": rate_per_minute,
        "duration_seconds": round(duration, 3),
        "retrieval_setting": retrieval_setting,
        "results_csv": results_path.name,
        "raw_traces": raw_path.name,
        "answer_grading": "pending_user",
    }
    (run_dir / "run.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
