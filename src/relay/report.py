"""Recompute assignment tables from measured CSV rows without filling missing evidence."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from relay.load import MANDATORY_COLUMNS, write_results_csv

VALID_GRADES = {"correct", "wrong", "refused_correctly", "refused_wrongly"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _json_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _usage_efficiency(
    rows: list[dict[str, Any]], delivered_answers: int
) -> tuple[float | None, float, float | None]:
    """Charge all known work to delivered answers without hiding failed attempts."""

    known_tokens = []
    for row in rows:
        tokens_in = _number(row.get("tokens_in"))
        tokens_out = _number(row.get("tokens_out"))
        if tokens_in is not None and tokens_out is not None:
            known_tokens.append(tokens_in + tokens_out)
    coverage = _percentage(len(known_tokens), len(rows))
    tokens_per_answer = (
        round(sum(known_tokens) / delivered_answers, 1)
        if delivered_answers and len(known_tokens) == len(rows)
        else None
    )
    costs = [value for row in rows if (value := _number(row.get("cost_usd"))) is not None]
    cost_per_1000_answers = (
        round(sum(costs) / delivered_answers * 1000, 6)
        if delivered_answers and len(costs) == len(rows)
        else None
    )
    return tokens_per_answer, coverage, cost_per_1000_answers


def percentile(values: list[float], fraction: float) -> float | None:
    """Linear interpolation over observed values, including small samples."""

    if not values:
        return None
    if not 0 <= fraction <= 1:
        raise ValueError("percentile fraction must be between zero and one")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    interpolated = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(interpolated, 1)


def _percentage(count: int, total: int) -> float:
    return round(count * 100 / total, 1) if total else 0.0


def scenario_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the latency/outcome table at one row per measured run."""

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("record_kind", "") not in {"", "load"}:
            continue
        grouped[(row.get("run_id", ""), row.get("scenario", ""), row.get("source", ""))].append(row)

    summaries = []
    for (run_id, scenario, source), group in sorted(grouped.items()):
        count = len(group)
        first_tokens = [
            value for row in group if (value := _number(row.get("first_token_ms"))) is not None
        ]
        totals = [value for row in group if (value := _number(row.get("total_ms"))) is not None]
        retries = [value for row in group if (value := _number(row.get("retries"))) is not None]
        delivered_answers = sum(
            row.get("status") == "ok" and row.get("disposition") == "answered" for row in group
        )
        tokens_per_answer, usage_coverage, cost_per_1000_answers = _usage_efficiency(
            group, delivered_answers
        )
        durations = [
            value for row in group if (value := _number(row.get("run_duration_s"))) is not None
        ]
        offered_rates = [
            value
            for row in group
            if (value := _number(row.get("offered_rate_per_min"))) is not None
        ]
        queue_peaks = [
            value for row in group if (value := _number(row.get("peak_queue_length"))) is not None
        ]
        timeout_or_given_up = sum(
            row.get("status") in {"timeout", "error"} or _truthy(row.get("given_up"))
            for row in group
        )
        summaries.append(
            {
                "run_id": run_id,
                "scenario": scenario,
                "source": source,
                "count": count,
                "duration_s": round(max(durations), 3) if durations else None,
                "offered_rate_per_min": round(max(offered_rates), 3) if offered_rates else None,
                "ttft_p50_ms": percentile(first_tokens, 0.50),
                "ttft_p95_ms": percentile(first_tokens, 0.95),
                "ttft_p99_ms": percentile(first_tokens, 0.99),
                "total_p50_ms": percentile(totals, 0.50),
                "total_p95_ms": percentile(totals, 0.95),
                "total_p99_ms": percentile(totals, 0.99),
                "success_pct": _percentage(sum(row.get("status") == "ok" for row in group), count),
                "rate_limited_pct": _percentage(
                    sum(row.get("status") == "rate_limited" for row in group), count
                ),
                "timeout_or_given_up_pct": _percentage(timeout_or_given_up, count),
                "retries_per_request": round(sum(retries) / count, 2) if retries else 0.0,
                "peak_queue_length": int(max(queue_peaks)) if queue_peaks else None,
                "delivered_answers": delivered_answers,
                "tokens_per_answer": tokens_per_answer,
                "token_usage_coverage_pct": usage_coverage,
                "cost_per_1000_answers_usd": cost_per_1000_answers,
            }
        )
    return summaries


def retrieval_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build retrieval-quality rows only from explicit human grades."""

    quality = [row for row in rows if row.get("record_kind") == "quality"]
    if not quality:
        quality = rows
    graded = [row for row in quality if row.get("answer_grade") in VALID_GRADES]
    if not graded:
        raise ValueError("No human-graded answer rows are available")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in quality:
        grouped[row.get("retrieval_setting", "")].append(row)

    summaries = []
    for setting, group in sorted(grouped.items()):
        graded_group = [row for row in group if row.get("answer_grade") in VALID_GRADES]
        if not graded_group:
            continue
        total = len(graded_group)
        first_tokens = [
            value
            for row in graded_group
            if (value := _number(row.get("first_token_ms"))) is not None
        ]
        totals = [
            value for row in graded_group if (value := _number(row.get("total_ms"))) is not None
        ]
        delivered_answers = sum(
            _truthy(row.get("grade_applicable")) or row.get("answer_grade") in VALID_GRADES
            for row in group
        )
        tokens_per_answer, usage_coverage, _ = _usage_efficiency(group, delivered_answers)
        summaries.append(
            {
                "retrieval_setting": setting,
                "questions": len({row.get("question_id") for row in graded_group}),
                "questions_attempted": len({row.get("question_id") for row in group}),
                "responses_graded": total,
                "correct_and_cited_pct": _percentage(
                    sum(row.get("answer_grade") == "correct" for row in graded_group), total
                ),
                "wrong_pct": _percentage(
                    sum(
                        row.get("answer_grade") in {"wrong", "refused_wrongly"}
                        for row in graded_group
                    ),
                    total,
                ),
                "correctly_refused_pct": _percentage(
                    sum(row.get("answer_grade") == "refused_correctly" for row in graded_group),
                    total,
                ),
                "wrong_refusal_count": sum(
                    row.get("answer_grade") == "refused_wrongly" for row in graded_group
                ),
                "tokens_per_answer": tokens_per_answer,
                "token_usage_coverage_pct": usage_coverage,
                "ttft_p50_ms": percentile(first_tokens, 0.50),
                "ttft_p95_ms": percentile(first_tokens, 0.95),
                "total_p50_ms": percentile(totals, 0.50),
                "total_p95_ms": percentile(totals, 0.95),
            }
        )
    return summaries


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_No measured rows available._\n"
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| "
        + " | ".join("—" if row.get(column) is None else str(row.get(column)) for column in columns)
        + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body]) + "\n"


def _read_document(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON artifact: {path}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"JSON artifact must contain an object: {path}")
    return document


def calibration_rows(path: Path, service_facts_path: Path | None = None) -> list[dict[str, Any]]:
    """Convert retained real calibration attempts into mandatory CSV rows offline."""

    document = _read_document(path)
    records = document.get("records")
    if not isinstance(records, list):
        raise ValueError("Calibration artifact requires a records list")
    if document.get("source") != "real":
        raise ValueError("Calibration artifact source must be real")
    documented_limits = ""
    fact_sources = ""
    if service_facts_path is not None:
        facts = _read_document(service_facts_path)
        documentation = facts.get("documentation")
        if not isinstance(documentation, dict):
            raise ValueError("Service facts require a documentation object")
        documented_limits = json.dumps(documentation, sort_keys=True)
        fact_sources = json.dumps(documentation.get("sources", []), sort_keys=True)

    rows = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("attempts"), list):
            raise ValueError("Calibration records require an attempts list")
        for index, attempt in enumerate(record["attempts"], start=1):
            if not isinstance(attempt, dict):
                raise ValueError("Calibration attempts must be objects")
            headers = attempt.get("headers") if isinstance(attempt.get("headers"), dict) else {}
            limits = {
                key.lower(): value
                for key, value in headers.items()
                if isinstance(key, str) and key.lower().startswith("x-ratelimit-")
            }
            request_id = headers.get("x-request-id")
            if not isinstance(request_id, str) or not request_id:
                request_id = f"{path.stem}-{record.get('sample_id', 'unknown')}-{index}"
            status = attempt.get("status")
            if status not in {"ok", "rate_limited", "timeout", "error"}:
                status = "error"
            tokens_in, tokens_out = attempt.get("tokens_in"), attempt.get("tokens_out")
            rows.append(
                {
                    "request_id": request_id,
                    "scenario": "steady",
                    "source": "real",
                    "start_time": attempt.get("started_at", ""),
                    "first_token_ms": attempt.get("first_token_ms"),
                    "total_ms": attempt.get("total_ms"),
                    "status": status,
                    "retries": max(0, int(attempt.get("attempt", 1)) - 1),
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "retrieval_setting": "",
                    "answer_grade": "",
                    "run_id": path.stem,
                    "record_kind": "calibration",
                    "question_id": f"calibration-{record.get('sample_id', 'unknown')}",
                    "grade_applicable": False,
                    "outcome_reason": f"http_{attempt.get('http_status')}",
                    "disposition": "measurement",
                    "usage_known": type(tokens_in) is int and type(tokens_out) is int,
                    "token_usage_source": "provider_response"
                    if type(tokens_in) is int and type(tokens_out) is int
                    else "unknown",
                    "model_id": attempt.get("returned_model") or attempt.get("model"),
                    "limits_json": json.dumps(limits, sort_keys=True) if limits else "",
                    "limits_evidence_json": json.dumps(
                        {
                            "http_status": attempt.get("http_status"),
                            "headers": limits,
                        },
                        sort_keys=True,
                    )
                    if limits
                    else "",
                    "documented_limits_json": documented_limits,
                    "service_fact_sources_json": fact_sources,
                    "calibration_concurrency": record.get("concurrency"),
                    "calibration_input_size": record.get("input_size"),
                    "http_status": attempt.get("http_status"),
                }
            )
    return rows


def grading_decisions(path: Path) -> dict[str, tuple[str, str]]:
    """Load an explicit user-approved grading overlay keyed by immutable request ID."""

    document = _read_document(path)
    if document.get("review_status") != "approved_by_user":
        raise ValueError("Grading decisions require review_status=approved_by_user")
    groups = document.get("grade_groups")
    if not isinstance(groups, list):
        raise ValueError("Grading decisions require a grade_groups list")
    decisions: dict[str, tuple[str, str]] = {}
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Grade groups must be objects")
        grade = group.get("answer_grade")
        rationale = group.get("grading_rationale")
        request_ids = group.get("request_ids")
        if grade not in VALID_GRADES or not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("Each grade group requires a valid grade and rationale")
        if not isinstance(request_ids, list) or not request_ids:
            raise ValueError("Each grade group requires request_ids")
        for request_id in request_ids:
            if not isinstance(request_id, str) or not request_id or request_id in decisions:
                raise ValueError("Grading request IDs must be unique non-empty strings")
            decisions[request_id] = (grade, rationale)
    return decisions


def quality_rows(path: Path, grades_path: Path | None = None) -> list[dict[str, Any]]:
    """Convert retained answer-quality attempts into mandatory CSV rows offline."""

    document = _read_document(path)
    if document.get("kind") != "answer_quality":
        raise ValueError("Quality artifact kind must be answer_quality")
    records = document.get("records")
    if not isinstance(records, list):
        raise ValueError("Quality artifact requires a records list")
    decisions = grading_decisions(grades_path) if grades_path is not None else {}
    applied_decisions: set[str] = set()
    rows = []
    for record in records:
        answer = record.get("answer") if isinstance(record, dict) else None
        if not isinstance(answer, dict):
            raise ValueError("Quality records require an answer object")
        request_id = answer.get("request_id")
        grade = record.get("answer_grade") or ""
        rationale = record.get("grading_rationale")
        if request_id in decisions:
            if grade and grade != decisions[request_id][0]:
                raise ValueError(f"Grading overlay conflicts with retained grade: {request_id}")
            grade, rationale = decisions[request_id]
            applied_decisions.add(request_id)
        tokens_in, tokens_out = answer.get("tokens_in"), answer.get("tokens_out")
        rows.append(
            {
                "request_id": request_id,
                "scenario": "steady",
                "source": answer.get("source"),
                "start_time": answer.get("start_time", ""),
                "first_token_ms": answer.get("first_token_ms"),
                "total_ms": answer.get("total_ms"),
                "status": answer.get("status"),
                "retries": answer.get("retries", 0),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "retrieval_setting": answer.get("retrieval_setting", ""),
                "answer_grade": grade,
                "run_id": path.stem,
                "record_kind": "quality",
                "question_id": record.get("question_id"),
                "grade_applicable": bool(record.get("case_complete")),
                "outcome_reason": answer.get("reason", ""),
                "disposition": answer.get("disposition"),
                "usage_known": type(tokens_in) is int and type(tokens_out) is int,
                "token_usage_source": "provider_response"
                if type(tokens_in) is int and type(tokens_out) is int
                else "unknown",
                "grading_rationale": rationale,
                "question": record.get("question"),
            }
        )
    unused = set(decisions) - applied_decisions
    if unused:
        raise ValueError(f"Grading decisions reference unknown requests: {sorted(unused)}")
    return rows


def calibration_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    calibration = [row for row in rows if row.get("record_kind") == "calibration"]
    first_tokens = [
        value for row in calibration if (value := _number(row.get("first_token_ms"))) is not None
    ]
    totals = [value for row in calibration if (value := _number(row.get("total_ms"))) is not None]
    known_tokens = [
        _number(row.get("tokens_in")) + _number(row.get("tokens_out"))
        for row in calibration
        if _number(row.get("tokens_in")) is not None and _number(row.get("tokens_out")) is not None
    ]
    return {
        "attempts": len(calibration),
        "successful_attempts": sum(row.get("status") == "ok" for row in calibration),
        "median_first_token_ms": percentile(first_tokens, 0.5),
        "median_total_ms": percentile(totals, 0.5),
        "tokens_total": int(sum(known_tokens))
        if len(known_tokens) == len(calibration) and calibration
        else None,
        "retries": sum(int(_number(row.get("retries")) or 0) for row in calibration),
        "observed_http_statuses": sorted(
            {
                int(value)
                for row in calibration
                if (value := _number(row.get("http_status"))) is not None
            }
        ),
    }


def service_limit_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calibration = [row for row in rows if row.get("record_kind") == "calibration"]
    if not calibration:
        return []
    documentation = next(
        (
            parsed
            for row in calibration
            if (parsed := _json_object(row.get("documented_limits_json")))
        ),
        {},
    )
    observed = {}
    for row in calibration:
        observed.update(_json_object(row.get("limits_json")))
    max_concurrency = max(
        (
            int(value)
            for row in calibration
            if (value := _number(row.get("calibration_concurrency"))) is not None
        ),
        default=None,
    )
    observed_statuses = {
        int(value) for row in calibration if (value := _number(row.get("http_status"))) is not None
    }
    return [
        {
            "limit": "requests/min",
            "value_found": documentation.get("rpm"),
            "how_found": "official documentation; not stress-tested",
            "confidence": "medium",
        },
        {
            "limit": "tokens/min",
            "value_found": observed.get("x-ratelimit-limit-tokens") or documentation.get("tpm"),
            "how_found": "real response headers and official documentation",
            "confidence": "high" if observed.get("x-ratelimit-limit-tokens") else "medium",
        },
        {
            "limit": "requests/day",
            "value_found": observed.get("x-ratelimit-limit-requests") or documentation.get("rpd"),
            "how_found": "real response headers and official documentation",
            "confidence": "high" if observed.get("x-ratelimit-limit-requests") else "medium",
        },
        {
            "limit": "tokens/day",
            "value_found": documentation.get("tpd"),
            "how_found": "official documentation; not exhausted at provider",
            "confidence": "medium",
        },
        {
            "limit": "requests in flight",
            "value_found": f"at least {max_concurrency}; maximum not measured"
            if max_concurrency is not None
            else "not measured",
            "how_found": "successful real calibration concurrency",
            "confidence": "low",
        },
        {
            "limit": "limit response",
            "value_found": (
                f"not measured; documentation specifies HTTP "
                f"{documentation.get('limit_http_status')} + Retry-After"
                if documentation.get("limit_http_status") and documentation.get("retry_after")
                else "not measured"
            ),
            "how_found": f"observed HTTP statuses {sorted(observed_statuses)}; documentation",
            "confidence": "low",
        },
        {
            "limit": "recovery time",
            "value_found": "not measured",
            "how_found": "real limit was not deliberately reached",
            "confidence": "low",
        },
    ]


def build_report(
    input_root: Path,
    output_dir: Path,
    *,
    calibration_path: Path | None = None,
    quality_path: Path | None = None,
    grades_path: Path | None = None,
    service_facts_path: Path | None = None,
) -> dict[str, Path]:
    """Combine per-run CSVs and regenerate only evidence-supported tables."""

    sources = sorted(input_root.glob("*/results.csv"))
    if not sources:
        raise ValueError("No per-run results.csv files were found")
    rows: list[dict[str, Any]] = []
    for path in sources:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or reader.fieldnames[: len(MANDATORY_COLUMNS)] != list(
                MANDATORY_COLUMNS
            ):
                raise ValueError(f"Mandatory results columns are missing or reordered: {path}")
            for row in reader:
                row["record_kind"] = row.get("record_kind") or "load"
                rows.append(row)

    supplemental_sources = []
    if calibration_path is not None:
        rows.extend(calibration_rows(calibration_path, service_facts_path))
        supplemental_sources.append(calibration_path)
        if service_facts_path is not None:
            supplemental_sources.append(service_facts_path)
    elif service_facts_path is not None:
        raise ValueError("Service facts require a calibration artifact")
    if quality_path is not None:
        rows.extend(quality_rows(quality_path, grades_path))
        supplemental_sources.append(quality_path)
        if grades_path is not None:
            supplemental_sources.append(grades_path)
    elif grades_path is not None:
        raise ValueError("Grading decisions require a quality artifact")
    request_ids = [row.get("request_id") for row in rows]
    if any(not isinstance(request_id, str) or not request_id for request_id in request_ids):
        raise ValueError("Every result row requires a non-empty request_id")
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("Duplicate request_id found while combining result artifacts")

    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.csv"
    write_results_csv(rows, results_path)
    scenarios = scenario_summary(rows)
    try:
        quality_table_rows = retrieval_summary(rows)
        retrieval_quality = {"status": "ready", "rows": quality_table_rows}
    except ValueError:
        retrieval_quality = {
            "status": "blocked_pending_user_grading",
            "rows": [],
            "reason": "answer_grade remains empty until explicit human review",
        }
    tables = {
        "schema_version": 1,
        "source_files": [str(path) for path in [*sources, *supplemental_sources]],
        "percentile_method": "linear interpolation over observed request values",
        "efficiency_method": (
            "all known consumed work divided by delivered answers; unknown usage or cost "
            "keeps the corresponding metric null"
        ),
        "service_limits": service_limit_summary(rows),
        "calibration": calibration_summary(rows),
        "scenario_runs": scenarios,
        "retrieval_quality": retrieval_quality,
    }
    tables_path = output_dir / "tables.json"
    tables_path.write_text(json.dumps(tables, indent=2), encoding="utf-8")

    scenario_columns = [
        "run_id",
        "scenario",
        "source",
        "count",
        "duration_s",
        "offered_rate_per_min",
        "ttft_p50_ms",
        "ttft_p95_ms",
        "ttft_p99_ms",
        "total_p50_ms",
        "total_p95_ms",
        "total_p99_ms",
        "success_pct",
        "rate_limited_pct",
        "timeout_or_given_up_pct",
        "retries_per_request",
        "peak_queue_length",
        "delivered_answers",
        "tokens_per_answer",
        "token_usage_coverage_pct",
        "cost_per_1000_answers_usd",
    ]
    markdown = [
        "# The Relay measured tables",
        "",
        "Percentiles use linear interpolation over observed request values.",
        "Efficiency charges all known consumed work, including failures, to delivered answers.",
        "",
        "## Real service limits",
        "",
        _markdown_table(
            tables["service_limits"],
            ["limit", "value_found", "how_found", "confidence"],
        ).rstrip(),
        "",
        "## Real calibration",
        "",
        _markdown_table([tables["calibration"]], list(tables["calibration"])).rstrip(),
        "",
        "## Scenario runs",
        "",
        _markdown_table(scenarios, scenario_columns).rstrip(),
        "",
        "## Retrieval quality",
        "",
    ]
    if retrieval_quality["status"] == "ready":
        markdown.append(
            _markdown_table(
                retrieval_quality["rows"],
                [
                    "retrieval_setting",
                    "questions",
                    "correct_and_cited_pct",
                    "wrong_pct",
                    "correctly_refused_pct",
                    "wrong_refusal_count",
                    "tokens_per_answer",
                    "token_usage_coverage_pct",
                    "ttft_p50_ms",
                    "ttft_p95_ms",
                    "total_p50_ms",
                    "total_p95_ms",
                ],
            ).rstrip()
        )
    else:
        markdown.append(
            "**Pending user grading.** No retrieval-quality percentages were generated."
        )
    markdown_path = output_dir / "tables.md"
    markdown_path.write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return {
        "results_csv": results_path,
        "tables_json": tables_path,
        "tables_markdown": markdown_path,
    }
