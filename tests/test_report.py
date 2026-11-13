import csv
import json

import pytest

from relay.report import (
    build_report,
    calibration_rows,
    percentile,
    quality_rows,
    retrieval_summary,
    scenario_summary,
)


def test_percentile_uses_linear_interpolation_for_small_honest_samples():
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 0.50) == 25.0
    assert percentile(values, 0.95) == 38.5
    assert percentile(values, 0.99) == 39.7
    assert percentile([], 0.95) is None


def test_scenario_summary_uses_observed_rows_and_keeps_unknown_cost_blank():
    rows = [
        {
            "run_id": "run-1",
            "scenario": "steady",
            "source": "stand-in",
            "first_token_ms": "100",
            "total_ms": "200",
            "status": "ok",
            "retries": "0",
            "tokens_in": "100",
            "tokens_out": "20",
            "disposition": "answered",
            "peak_queue_length": "2",
            "run_duration_s": "10",
            "offered_rate_per_min": "24",
        },
        {
            "run_id": "run-1",
            "scenario": "steady",
            "source": "stand-in",
            "first_token_ms": "200",
            "total_ms": "400",
            "status": "ok",
            "retries": "1",
            "tokens_in": "80",
            "tokens_out": "10",
            "disposition": "refused",
            "peak_queue_length": "2",
            "run_duration_s": "10",
            "offered_rate_per_min": "24",
        },
        {
            "run_id": "run-1",
            "scenario": "steady",
            "source": "stand-in",
            "first_token_ms": "300",
            "total_ms": "600",
            "status": "rate_limited",
            "retries": "0",
            "tokens_in": "",
            "tokens_out": "",
            "disposition": "unavailable",
            "peak_queue_length": "2",
            "run_duration_s": "10",
            "offered_rate_per_min": "24",
        },
        {
            "run_id": "run-1",
            "scenario": "steady",
            "source": "stand-in",
            "first_token_ms": "",
            "total_ms": "50",
            "status": "timeout",
            "retries": "0",
            "tokens_in": "",
            "tokens_out": "",
            "disposition": "unavailable",
            "peak_queue_length": "2",
            "run_duration_s": "10",
            "offered_rate_per_min": "24",
        },
    ]

    summary = scenario_summary(rows)[0]

    assert summary["count"] == 4
    assert summary["ttft_p50_ms"] == 200.0
    assert summary["ttft_p95_ms"] == 290.0
    assert summary["total_p50_ms"] == 300.0
    assert summary["success_pct"] == 50.0
    assert summary["rate_limited_pct"] == 25.0
    assert summary["timeout_or_given_up_pct"] == 25.0
    assert summary["retries_per_request"] == 0.25
    assert summary["peak_queue_length"] == 2
    assert summary["tokens_per_answer"] is None
    assert summary["token_usage_coverage_pct"] == 50.0
    assert summary["cost_per_1000_answers_usd"] is None


def test_scenario_efficiency_charges_failed_work_to_delivered_answers():
    rows = [
        {
            "run_id": "run-1",
            "scenario": "steady",
            "source": "stand-in",
            "status": "ok",
            "disposition": "answered",
            "tokens_in": "80",
            "tokens_out": "20",
            "cost_usd": "0.01",
            "retries": "0",
        },
        {
            "run_id": "run-1",
            "scenario": "steady",
            "source": "stand-in",
            "status": "error",
            "disposition": "unavailable",
            "tokens_in": "180",
            "tokens_out": "20",
            "cost_usd": "0.02",
            "retries": "0",
        },
    ]

    summary = scenario_summary(rows)[0]

    assert summary["tokens_per_answer"] == 300.0
    assert summary["token_usage_coverage_pct"] == 100.0
    assert summary["cost_per_1000_answers_usd"] == 30.0


def test_retrieval_summary_requires_human_grades_and_preserves_wrong_refusals():
    ungraded = [
        {
            "retrieval_setting": "lexical-word180-k4-v1",
            "answer_grade": "",
            "question_id": "q-1",
        }
    ]
    with pytest.raises(ValueError, match="human-graded"):
        retrieval_summary(ungraded)

    graded = [
        {
            "retrieval_setting": "lexical-word180-k4-v1",
            "answer_grade": "correct",
            "question_id": "q-1",
            "first_token_ms": "100",
            "total_ms": "200",
            "tokens_in": "90",
            "tokens_out": "10",
        },
        {
            "retrieval_setting": "lexical-word180-k4-v1",
            "answer_grade": "refused_correctly",
            "question_id": "q-2",
            "first_token_ms": "200",
            "total_ms": "400",
            "tokens_in": "80",
            "tokens_out": "20",
        },
        {
            "retrieval_setting": "lexical-word180-k4-v1",
            "answer_grade": "refused_wrongly",
            "question_id": "q-3",
            "first_token_ms": "300",
            "total_ms": "600",
            "tokens_in": "70",
            "tokens_out": "30",
        },
    ]

    summary = retrieval_summary(graded)[0]
    assert summary["questions"] == 3
    assert summary["correct_and_cited_pct"] == 33.3
    assert summary["wrong_pct"] == 33.3
    assert summary["correctly_refused_pct"] == 33.3
    assert summary["wrong_refusal_count"] == 1
    assert summary["tokens_per_answer"] == 100.0
    assert summary["ttft_p50_ms"] == 200.0


def test_build_report_combines_runs_and_marks_ungraded_quality_as_blocked(tmp_path):
    input_root = tmp_path / "experiments"
    fieldnames = [
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
        "run_id",
        "question_id",
        "disposition",
        "run_duration_s",
        "offered_rate_per_min",
    ]
    for index, scenario in enumerate(("steady", "burst"), start=1):
        run_dir = input_root / f"run-{index}"
        run_dir.mkdir(parents=True)
        with (run_dir / "results.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "request_id": f"request-{index}",
                    "scenario": scenario,
                    "source": "stand-in",
                    "start_time": "2026-11-12T10:00:00+00:00",
                    "first_token_ms": "100",
                    "total_ms": "200",
                    "status": "ok",
                    "retries": "0",
                    "tokens_in": "90",
                    "tokens_out": "10",
                    "retrieval_setting": "lexical-word180-k4-v1",
                    "answer_grade": "",
                    "run_id": f"run-{index}",
                    "question_id": f"q-{index}",
                    "disposition": "answered",
                    "run_duration_s": "1",
                    "offered_rate_per_min": "60",
                }
            )

    output = build_report(input_root, tmp_path / "submission")

    with output["results_csv"].open(newline="", encoding="utf-8") as handle:
        combined = list(csv.DictReader(handle))
    assert len(combined) == 2
    tables = json.loads(output["tables_json"].read_text(encoding="utf-8"))
    assert len(tables["scenario_runs"]) == 2
    assert tables["retrieval_quality"]["status"] == "blocked_pending_user_grading"
    assert tables["retrieval_quality"]["rows"] == []
    assert "Pending user grading" in output["tables_markdown"].read_text(encoding="utf-8")


def test_report_imports_retained_calibration_and_quality_rows_offline(tmp_path):
    input_root = tmp_path / "experiments"
    run_dir = input_root / "run-1"
    run_dir.mkdir(parents=True)
    fieldnames = [
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
        "run_id",
        "question_id",
        "disposition",
    ]
    with (run_dir / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "request_id": "load-1",
                "scenario": "steady",
                "source": "stand-in",
                "start_time": "2026-11-12T10:00:00+00:00",
                "first_token_ms": "100",
                "total_ms": "200",
                "status": "ok",
                "retries": "0",
                "tokens_in": "90",
                "tokens_out": "10",
                "retrieval_setting": "lexical-word180-k4-v1",
                "answer_grade": "",
                "run_id": "run-1",
                "question_id": "q-load",
                "disposition": "answered",
            }
        )

    service_facts = tmp_path / "service-facts.json"
    service_facts.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "model": "openai/gpt-oss-20b",
                "observed_at": "2026-11-12",
                "documentation": {
                    "rpm": 30,
                    "tpm": 8000,
                    "rpd": 1000,
                    "tpd": 200000,
                    "limit_http_status": 429,
                    "retry_after": True,
                    "sources": ["https://console.groq.com/docs/rate-limits"],
                },
            }
        ),
        encoding="utf-8",
    )
    calibration = tmp_path / "calibration.json"
    calibration.write_text(
        json.dumps(
            {
                "source": "real",
                "model": "openai/gpt-oss-20b",
                "records": [
                    {
                        "sample_id": 0,
                        "concurrency": 2,
                        "input_size": "short",
                        "attempts": [
                            {
                                "attempt": 1,
                                "started_at": "2026-11-12T10:01:00+00:00",
                                "status": "ok",
                                "http_status": 200,
                                "first_token_ms": 250,
                                "total_ms": 260,
                                "tokens_in": 100,
                                "tokens_out": 10,
                                "model": "openai/gpt-oss-20b",
                                "headers": {
                                    "x-request-id": "real-1",
                                    "x-ratelimit-limit-requests": "1000",
                                    "x-ratelimit-limit-tokens": "8000",
                                },
                            }
                        ],
                        "status": "ok",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    quality = tmp_path / "quality.json"
    quality.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "answer_quality",
                "records": [
                    {
                        "question_id": "q-1",
                        "question": "Question?",
                        "case_complete": True,
                        "answer_grade": None,
                        "grading_rationale": None,
                        "answer": {
                            "request_id": "quality-1",
                            "start_time": "2026-11-12T10:02:00+00:00",
                            "source": "real",
                            "status": "ok",
                            "disposition": "answered",
                            "first_token_ms": None,
                            "total_ms": 500,
                            "tokens_in": 200,
                            "tokens_out": 20,
                            "retries": 0,
                            "retrieval_setting": "lexical-word180-k4-v1",
                            "reason": "support_checks_passed",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    output = build_report(
        input_root,
        tmp_path / "submission",
        calibration_path=calibration,
        quality_path=quality,
        service_facts_path=service_facts,
    )

    with output["results_csv"].open(newline="", encoding="utf-8") as handle:
        combined = list(csv.DictReader(handle))
    assert {row["record_kind"] for row in combined} == {"load", "calibration", "quality"}
    assert {row["request_id"] for row in combined} == {"load-1", "real-1", "quality-1"}
    assert next(row for row in combined if row["request_id"] == "quality-1")["answer_grade"] == ""
    tables = json.loads(output["tables_json"].read_text(encoding="utf-8"))
    assert len(tables["scenario_runs"]) == 1
    assert tables["calibration"]["successful_attempts"] == 1
    assert tables["service_limits"][0]["value_found"] == 30
    assert tables["retrieval_quality"]["status"] == "blocked_pending_user_grading"


def test_offline_importers_reject_duplicate_or_malformed_artifacts(tmp_path):
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps({"source": "real", "records": []}), encoding="utf-8")
    assert calibration_rows(calibration) == []

    quality = tmp_path / "quality.json"
    quality.write_text(json.dumps({"kind": "wrong", "records": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="answer_quality"):
        quality_rows(quality)


def test_quality_import_applies_only_explicit_approved_grading_overlay(tmp_path):
    quality = tmp_path / "quality.json"
    quality.write_text(
        json.dumps(
            {
                "kind": "answer_quality",
                "records": [
                    {
                        "question_id": "q-1",
                        "question": "Question?",
                        "case_complete": True,
                        "answer_grade": None,
                        "grading_rationale": None,
                        "answer": {
                            "request_id": "quality-1",
                            "start_time": "2026-11-12T10:02:00+00:00",
                            "source": "real",
                            "status": "ok",
                            "disposition": "answered",
                            "total_ms": 500,
                            "tokens_in": 200,
                            "tokens_out": 20,
                            "retries": 0,
                            "retrieval_setting": "lexical-word180-k4-v1",
                            "reason": "support_checks_passed",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    grades = tmp_path / "grades.json"
    grades.write_text(
        json.dumps(
            {
                "review_status": "approved_by_user",
                "approval_message": "all clear",
                "grade_groups": [
                    {
                        "answer_grade": "correct",
                        "grading_rationale": "Answer and citation were approved.",
                        "request_ids": ["quality-1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    rows = quality_rows(quality, grades_path=grades)

    assert rows[0]["answer_grade"] == "correct"
    assert rows[0]["grading_rationale"] == "Answer and citation were approved."
