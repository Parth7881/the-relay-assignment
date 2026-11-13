import csv
import json

import httpx
import pytest

from relay.load import (
    MANDATORY_COLUMNS,
    enrich_row_from_server_trace,
    load_question_cases,
    measure_request,
    preflight_target,
    run_load_experiment,
    scenario_offsets,
    validate_load_target,
    write_results_csv,
)


def answer_payload() -> dict:
    return {
        "request_id": "request-1",
        "question": "What replaces recurrence?",
        "start_time": "2026-11-12T10:00:00+00:00",
        "source": "stand-in",
        "status": "ok",
        "disposition": "refused",
        "answer": "I could not find enough supporting evidence.",
        "evidence": [],
        "first_token_ms": None,
        "total_ms": 120.0,
        "tokens_in": 100,
        "tokens_out": 20,
        "retries": 1,
        "retrieval_setting": "hybrid-minilm220-rrf-rerank-k4-v1",
        "reason": "model_refused",
    }


async def test_measure_request_records_client_timing_without_inventing_a_grade():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/ask"
        assert json.loads(request.content)["question"] == "What replaces recurrence?"
        return httpx.Response(200, json=answer_payload())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:8000",
    ) as client:
        row, trace = await measure_request(
            client,
            question_id="transformer-recurrence",
            question="What replaces recurrence?",
            scenario="steady",
            expected_source="stand-in",
            retrieval_setting="hybrid-minilm220-rrf-rerank-k4-v1",
            run_id="run-1",
        )

    assert row["request_id"] == "request-1"
    assert row["source"] == "stand-in"
    assert row["status"] == "ok"
    assert row["first_token_ms"] is not None
    assert row["total_ms"] >= row["first_token_ms"]
    assert row["answer_grade"] == ""
    assert row["grade_applicable"] is True
    assert trace["response"]["answer"] == answer_payload()["answer"]
    assert trace["client_timing"]["first_content_ms"] == row["first_token_ms"]


def test_results_csv_keeps_mandatory_columns_first_and_validates_enums(tmp_path):
    row = {
        "request_id": "request-1",
        "scenario": "burst",
        "source": "stand-in",
        "start_time": "2026-11-12T10:00:00+00:00",
        "first_token_ms": 10.0,
        "total_ms": 20.0,
        "status": "ok",
        "retries": 0,
        "tokens_in": 10,
        "tokens_out": 2,
        "retrieval_setting": "lexical-word180-k4-v1",
        "answer_grade": "",
        "run_id": "run-1",
        "question_id": "q-1",
        "grade_applicable": True,
        "outcome_reason": "support_checks_passed",
    }
    path = tmp_path / "results.csv"
    write_results_csv([row], path)

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames[: len(MANDATORY_COLUMNS)] == list(MANDATORY_COLUMNS)
        saved = next(reader)
    assert saved["request_id"] == "request-1"
    assert saved["answer_grade"] == ""

    with pytest.raises(ValueError, match="source"):
        write_results_csv([{**row, "source": "synthetic"}], path)


def test_scenario_offsets_are_open_loop_and_burst_is_simultaneous():
    assert scenario_offsets("steady", count=3, rate_per_minute=30) == [0.0, 2.0, 4.0]
    assert scenario_offsets("burst", count=3, rate_per_minute=30) == [0.0, 0.0, 0.0]
    assert scenario_offsets("daily_budget_exhausted", count=2, rate_per_minute=30) == [0.0, 0.0]


def test_question_loader_requires_explicit_user_approval(tmp_path):
    path = tmp_path / "questions.json"
    path.write_text(
        json.dumps(
            {
                "review_status": "pending_user",
                "questions": [{"id": "q-1", "question": "A question?"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="approved_by_user"):
        load_question_cases(path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["review_status"] = "approved_by_user"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_question_cases(path) == [{"id": "q-1", "question": "A question?"}]


async def test_load_experiment_writes_raw_traces_manifest_and_results(tmp_path):
    calls = 0
    server_runs = tmp_path / "server-runs"
    server_runs.mkdir()

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        request_id = f"request-{calls}"
        response = {**answer_payload(), "request_id": request_id}
        (server_runs / f"{request_id}.json").write_text(
            json.dumps(
                {
                    "result": response,
                    "queue": {
                        "queue_depth": calls - 1,
                        "queue_wait_ms": float(calls),
                        "queue_outcome": "admitted",
                    },
                    "attempts": [
                        {
                            "stage": "draft",
                            "model": "relay-stand-in",
                            "first_token_ms": 12.0,
                            "headers": {},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:8000",
    ) as client:
        summary = await run_load_experiment(
            client,
            cases=[{"id": "q-1", "question": "Question one?"}],
            scenario="burst",
            source="stand-in",
            retrieval_setting="hybrid-minilm220-rrf-rerank-k4-v1",
            count=2,
            rate_per_minute=30,
            output_root=tmp_path,
            server_runs_dir=server_runs,
        )

    assert summary["requests"] == 2
    run_dir = tmp_path / summary["run_id"]
    assert (run_dir / "results.csv").is_file()
    traces = [json.loads(line) for line in (run_dir / "raw.jsonl").read_text().splitlines()]
    assert len(traces) == 2
    assert {trace["schedule"]["offset_seconds"] for trace in traces} == {0.0}
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "stand-in"
    assert manifest["scenario"] == "burst"
    assert manifest["results_csv"] == "results.csv"
    rows = list(csv.DictReader((run_dir / "results.csv").open(encoding="utf-8")))
    assert {row["provider_first_token_ms"] for row in rows} == {"12.0"}
    assert {row["peak_queue_length"] for row in rows} == {"1"}
    assert (run_dir / "server-traces" / "request-1.json").is_file()


async def test_load_experiment_never_reads_server_trace_outside_configured_directory(tmp_path):
    server_runs = tmp_path / "server-runs"
    server_runs.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"secret": "must-not-be-copied"}), encoding="utf-8")

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={**answer_payload(), "request_id": "../outside"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000"
    ) as client:
        summary = await run_load_experiment(
            client,
            cases=[{"id": "q-1", "question": "Question one?"}],
            scenario="burst",
            source="stand-in",
            retrieval_setting="hybrid-minilm220-rrf-rerank-k4-v1",
            count=1,
            rate_per_minute=30,
            output_root=tmp_path / "experiments",
            server_runs_dir=server_runs,
        )

    run_dir = tmp_path / "experiments" / summary["run_id"]
    trace = json.loads((run_dir / "raw.jsonl").read_text(encoding="utf-8"))
    assert "server_trace_path" not in trace
    assert not (run_dir / "server-traces").exists()


def test_load_target_is_local_only_and_real_runs_require_explicit_opt_in():
    validate_load_target("http://127.0.0.1:8000", source="stand-in", allow_real=False, count=20)
    with pytest.raises(ValueError, match="localhost"):
        validate_load_target("https://example.com", source="stand-in", allow_real=False, count=1)
    with pytest.raises(ValueError, match="allow-real"):
        validate_load_target("http://127.0.0.1:8000", source="real", allow_real=False, count=4)
    with pytest.raises(ValueError, match="12 requests"):
        validate_load_target("http://127.0.0.1:8000", source="real", allow_real=True, count=13)


def test_server_trace_enrichment_uses_observed_queue_retry_and_limit_evidence():
    row = {
        "status": "ok",
        "tokens_in": 100,
        "tokens_out": 20,
        "total_ms": 240.0,
    }
    trace = {
        "result": {"total_ms": 200.0, "disposition": "answered"},
        "queue": {"queue_depth": 3, "queue_wait_ms": 12.5, "queue_outcome": "admitted"},
        "attempts": [
            {
                "model": "relay-stand-in",
                "first_token_ms": 40.0,
                "retry_wait_ms": 500.0,
                "headers": {"x-ratelimit-limit-tokens": "8000"},
            },
            {
                "model": "relay-stand-in",
                "first_token_ms": 60.0,
                "headers": {"x-ratelimit-remaining-tokens": "7000"},
            },
        ],
    }

    enrich_row_from_server_trace(row, trace)

    assert row["queue_ms"] == 12.5
    assert row["working_ms"] == 187.5
    assert row["queue_depth_at_arrival"] == 3
    assert row["retry_wait_ms"] == 500.0
    assert row["provider_first_token_ms"] == 40.0
    assert row["model_id"] == "relay-stand-in"
    assert row["disposition"] == "answered"
    assert row["usage_known"] is True
    assert json.loads(row["limits_json"])["x-ratelimit-limit-tokens"] == "8000"


async def test_preflight_rejects_source_mismatch_before_any_question_is_sent():
    paths = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "source": "real"})
        raise AssertionError("A source mismatch must stop before POST /api/ask")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:8000",
    ) as client:
        with pytest.raises(ValueError, match="expected source 'stand-in'"):
            await preflight_target(client, "stand-in")

    assert paths == ["/health"]
