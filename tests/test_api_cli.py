import json

import httpx

from relay.api import create_app
from relay.cli import main
from relay.config import Settings
from relay.corpus import PAPERS, chunk_page
from relay.retrieval import Retriever


def config(tmp_path):
    return Settings(
        _env_file=None,
        groq_api_key="",
        relay_data_dir=tmp_path / "data",
        relay_runs_dir=tmp_path / "runs",
        relay_ui_dir=tmp_path / "missing-ui",
    )


async def test_api_missing_corpus_is_actionable_without_leaking_details(tmp_path):
    transport = httpx.ASGITransport(app=create_app(config(tmp_path)))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        assert (await client.get("/health")).json()["corpus_ready"] is False
        response = await client.post("/api/retrieve", json={"question": "attention"})
        assert response.status_code == 503
        assert "ingest" in response.json()["detail"]


async def test_health_checks_default_advanced_retriever_and_stand_in_model(tmp_path, monkeypatch):
    import relay.api as api_module
    from relay.retrieval import HYBRID_RERANK

    loads = []

    class Searcher:
        def search(self, question, *, k, setting, expanded=False):
            return []

    def loader(data_dir, setting):
        loads.append(setting)
        return Searcher()

    monkeypatch.setattr(api_module, "load_retriever", loader)
    settings = config(tmp_path).model_copy(update={"relay_source": "stand-in"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://localhost"
    ) as client:
        health = (await client.get("/health")).json()

    assert loads == [HYBRID_RERANK]
    assert health["corpus_ready"] is True
    assert health["model_configured"] is True
    assert health["source"] == "stand-in"


async def test_optional_ui_serves_spa_assets_without_capturing_api_routes(tmp_path):
    ui_dir = tmp_path / "dist"
    assets = ui_dir / "assets"
    assets.mkdir(parents=True)
    (ui_dir / "index.html").write_text("<main>The Relay UI</main>", encoding="utf-8")
    (assets / "app-fixture.js").write_text("window.RELAY=true", encoding="utf-8")
    settings = config(tmp_path).model_copy(update={"relay_ui_dir": ui_dir})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://localhost"
    ) as client:
        root = await client.get("/")
        nested = await client.get("/library")
        asset = await client.get("/assets/app-fixture.js")
        unknown_api = await client.get("/api/not-a-route")

    assert root.status_code == nested.status_code == asset.status_code == 200
    assert root.text == nested.text == "<main>The Relay UI</main>"
    assert asset.text == "window.RELAY=true"
    assert unknown_api.status_code == 404
    assert "The Relay UI" not in unknown_api.text


async def test_missing_ui_keeps_api_only_behavior(tmp_path):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(config(tmp_path))),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/")
    assert response.status_code == 404


async def test_api_retrieval_exposes_only_pinned_evidence(tmp_path):
    retriever = Retriever(chunk_page(PAPERS[0], 3, "Attention uses queries keys and values."))
    transport = httpx.ASGITransport(app=create_app(config(tmp_path), retriever=retriever))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.post("/api/retrieve", json={"question": "attention"})
        assert response.status_code == 200
        assert response.json()["evidence"][0]["chunk"]["page"] == 3
        assert (await client.post("/api/ask", json={"question": "attention"})).status_code == 503
        assert (await client.post("/api/ask", json={"question": " "})).status_code == 422
        assert (await client.post("/api/ask", json={"question": "x" * 2001})).status_code == 422


def test_doctor_reports_key_presence_only(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "fixture-secret-not-real")
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "fixture-secret-not-real" not in output
    assert json.loads(output)["groq_key_configured"] is True


def test_cli_missing_key_does_not_call_model(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert main(["ask", "What is attention?"]) == 2
    assert "GROQ_API_KEY" in capsys.readouterr().err


def test_quality_cli_requires_key_before_loading_retrieval_models(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("Retrieval models must not load before credential validation.")

    monkeypatch.setattr("relay.retrieval.load_retriever", forbidden_loader)
    assert main(["eval-quality", "--max-new", "1"]) == 2
    assert "GROQ_API_KEY" in capsys.readouterr().err


def test_load_cli_refuses_accidental_real_provider_use(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["load", "--scenario", "steady", "--source", "real", "--requests", "4"]) == 2
    assert "allow-real" in capsys.readouterr().err


def test_load_cli_defaults_to_stand_in_and_prints_artifact_paths(tmp_path, monkeypatch, capsys):
    import relay.load as load_module

    monkeypatch.chdir(tmp_path)
    questions = tmp_path / "questions.json"
    questions.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        load_module,
        "load_question_cases",
        lambda _path: [{"id": "q-1", "question": "Question?"}],
    )
    preflights = []

    async def fake_preflight(_client, expected_source):
        preflights.append(expected_source)

    monkeypatch.setattr(load_module, "preflight_target", fake_preflight)

    async def fake_run(_client, **kwargs):
        assert kwargs["source"] == "stand-in"
        assert kwargs["scenario"] == "burst"
        assert kwargs["server_runs_dir"] == tmp_path / "server-runs"
        return {
            "run_id": "run-1",
            "requests": kwargs["count"],
            "results_csv": "results.csv",
            "raw_traces": "raw.jsonl",
        }

    monkeypatch.setattr(load_module, "run_load_experiment", fake_run)
    assert (
        main(
            [
                "load",
                "--scenario",
                "burst",
                "--questions",
                str(questions),
                "--output-root",
                str(tmp_path / "experiments"),
                "--server-runs-dir",
                str(tmp_path / "server-runs"),
                "--requests",
                "2",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == "run-1"
    assert output["results_csv"] == "results.csv"
    assert preflights == ["stand-in"]


def test_report_cli_rebuilds_submission_artifacts_without_grades(tmp_path, capsys):
    from relay.load import write_results_csv

    run_dir = tmp_path / "experiments" / "run-1"
    row = {
        "request_id": "request-1",
        "scenario": "steady",
        "source": "stand-in",
        "start_time": "2026-11-12T10:00:00+00:00",
        "first_token_ms": 100,
        "total_ms": 200,
        "status": "ok",
        "retries": 0,
        "tokens_in": 90,
        "tokens_out": 10,
        "retrieval_setting": "lexical-word180-k4-v1",
        "answer_grade": "",
        "run_id": "run-1",
        "question_id": "q-1",
        "grade_applicable": True,
        "outcome_reason": "support_checks_passed",
    }
    write_results_csv([row], run_dir / "results.csv")
    output_dir = tmp_path / "submission"

    assert (
        main(
            [
                "report",
                "--input-root",
                str(tmp_path / "experiments"),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["results_csv"] == str(output_dir / "results.csv")
    assert (output_dir / "tables.json").is_file()


async def test_api_rejects_oversized_body_before_parsing(tmp_path):
    app = create_app(Settings(_env_file=None, relay_runs_dir=tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/api/ask", content=b" " * 17000, headers={"content-type": "application/json"}
        )
    assert response.status_code == 413


async def test_disconnect_cancels_running_work():
    import asyncio

    import pytest
    from fastapi import HTTPException

    from relay.api import cancel_on_disconnect

    cancelled = asyncio.Event()

    class Disconnected:
        async def receive(self):
            return {"type": "http.disconnect"}

    async def work():
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    with pytest.raises(HTTPException) as error:
        await cancel_on_disconnect(Disconnected(), work())
    assert error.value.status_code == 499
    assert cancelled.is_set()


async def test_daily_exhaustion_is_operational_failure_with_zero_provider_calls(tmp_path):
    settings = Settings(
        _env_file=None, relay_source="stand-in", relay_rpd=0, relay_runs_dir=tmp_path
    )
    retriever = Retriever(chunk_page(PAPERS[0], 3, "Attention uses queries keys and values."))
    app = create_app(settings, retriever=retriever)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post("/api/ask", json={"question": "What does attention use?"})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "rate_limited" and result["disposition"] == "unavailable"
    assert result["reason"] == "daily_budget_exhausted"
    assert result["tokens_in"] == result["tokens_out"] == 0
    trace = json.loads((tmp_path / f"{result['request_id']}.json").read_text())
    assert trace["attempts"] == [] and trace["queue"]["queue_outcome"] == "admitted"


async def test_api_selects_only_allowlisted_retrieval_setting(tmp_path):
    from relay.retrieval import HYBRID, Hit

    chunk = chunk_page(PAPERS[0], 3, "Attention uses queries keys and values.")[0]

    class SearchSpy:
        def __init__(self):
            self.settings = []

        def search(self, question, *, k, setting, expanded=False):
            self.settings.append(setting)
            return [Hit(chunk=chunk, score=1)]

    search = SearchSpy()
    app = create_app(config(tmp_path), retriever=search)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/api/retrieve", json={"question": "attention", "retrieval_setting": HYBRID}
        )
        invalid = await client.post(
            "/api/retrieve", json={"question": "attention", "retrieval_setting": "invented"}
        )
    assert response.status_code == 200 and response.json()["retrieval_setting"] == HYBRID
    assert search.settings == [HYBRID]
    assert invalid.status_code == 422


async def test_advanced_loader_runs_off_loop_and_is_shared_by_hybrid_settings(
    tmp_path, monkeypatch
):
    import asyncio
    import time

    import relay.api as api_module
    from relay.retrieval import HYBRID, HYBRID_RERANK, Hit

    chunk = chunk_page(PAPERS[0], 3, "Attention uses queries keys and values.")[0]
    ticked = asyncio.Event()
    observed, loads = [], []

    class Searcher:
        def search(self, question, *, k, setting, expanded=False):
            return [Hit(chunk=chunk, score=1)]

    def slow_loader(data_dir, setting):
        loads.append(setting)
        time.sleep(0.05)
        observed.append(ticked.is_set())
        return Searcher()

    async def tick():
        await asyncio.sleep(0.01)
        ticked.set()

    monkeypatch.setattr(api_module, "load_retriever", slow_loader)
    app = create_app(config(tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        first, _ = await asyncio.gather(
            client.post(
                "/api/retrieve", json={"question": "attention", "retrieval_setting": HYBRID}
            ),
            tick(),
        )
        second = await client.post(
            "/api/retrieve", json={"question": "attention", "retrieval_setting": HYBRID_RERANK}
        )
    assert first.status_code == second.status_code == 200
    assert observed == [True]
    assert loads == [HYBRID_RERANK]


async def test_retrieve_uses_bounded_admission_instead_of_unbounded_worker_queue(tmp_path):
    import asyncio
    import threading

    from relay.retrieval import Hit

    chunk = chunk_page(PAPERS[0], 3, "Attention uses queries keys and values.")[0]
    started = threading.Event()
    release = threading.Event()

    class BlockingSearch:
        def search(self, question, *, k, setting, expanded=False):
            started.set()
            assert release.wait(timeout=2)
            return [Hit(chunk=chunk, score=1)]

    settings = config(tmp_path).model_copy(
        update={"relay_concurrency": 1, "relay_queue_capacity": 0}
    )
    app = create_app(settings, retriever=BlockingSearch())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        first = asyncio.create_task(client.post("/api/retrieve", json={"question": "attention"}))
        assert await asyncio.to_thread(started.wait, 1)
        second = await client.post("/api/retrieve", json={"question": "attention"})
        release.set()
        first_response = await first

    assert first_response.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == "queue_full"
