"""PowerShell-friendly entry points; no credentials printed or accepted as CLI flags."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from relay.config import Settings
from relay.corpus import ingest, load_chunks
from relay.pipeline import Pipeline
from relay.policy import Admission, Budget, ManagedModel
from relay.provider import GroqProvider
from relay.retrieval import (
    HYBRID_RERANK,
    LEXICAL,
    RETRIEVAL_SETTINGS,
    build_advanced_index,
    load_retriever,
    prepare_models,
)


async def _ask(settings: Settings, question: str, retrieval_setting: str = LEXICAL):
    index = load_retriever(settings.relay_data_dir, retrieval_setting)
    budget = Budget(settings.relay_runs_dir / f"budget-{settings.relay_source}.sqlite3", settings)
    async with httpx.AsyncClient(trust_env=False) as client:
        return await Pipeline(
            index,
            ManagedModel(GroqProvider(settings, client), budget, settings),
            settings.relay_runs_dir,
            deadline=settings.relay_deadline_seconds,
            source=settings.relay_source,
            admission=Admission(
                settings.relay_concurrency,
                settings.relay_queue_capacity,
                settings.relay_queue_wait_seconds,
            ),
            retrieval_setting=retrieval_setting,
        ).ask(question)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="relay", description="The Relay — local research assistant"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check local setup without exposing the key or calling Groq")
    sub.add_parser("ingest", help="Fetch exact arXiv versions and build the local corpus")
    sub.add_parser("index", help="Build pinned local dense index and cache retrieval models")
    retrieve = sub.add_parser("retrieve", help="Find passages without a model call")
    retrieve.add_argument("question")
    retrieve.add_argument("--k", type=int, default=4, choices=range(1, 13))
    retrieve.add_argument("--setting", choices=RETRIEVAL_SETTINGS, default=LEXICAL)
    ask = sub.add_parser("ask", help="Draft and verify, with bounded retries and budget checks")
    ask.add_argument("question")
    ask.add_argument("--setting", choices=RETRIEVAL_SETTINGS, default=LEXICAL)
    serve = sub.add_parser("serve", help="Start local API on 127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    calibrate_parser = sub.add_parser("calibrate", help="Measure 4-20 modest real Groq samples")
    calibrate_parser.add_argument("--requests", type=int, default=12, choices=range(4, 21))
    simulate = sub.add_parser("simulate", help="Start loopback streaming stand-in (no Groq calls)")
    simulate.add_argument("--profile", type=Path)
    simulate.add_argument("--replay", type=Path)
    simulate.add_argument(
        "--scenario",
        default="normal",
        choices=[
            "normal",
            "slow",
            "failure",
            "rate-limit",
            "load",
            "half-minute",
            "daily-exhausted",
        ],
    )
    simulate.add_argument("--port", type=int, default=8001)
    simulate.add_argument("--seed", type=int, default=42)
    evaluate_retrieval = sub.add_parser(
        "eval-retrieval", help="Compare all three retrievers without hosted model calls"
    )
    evaluate_retrieval.add_argument(
        "--questions", type=Path, default=Path("docs/evaluation-questions.json")
    )
    evaluate_retrieval.add_argument(
        "--output", type=Path, default=Path("runs/retrieval-evaluation.json")
    )
    evaluate_quality = sub.add_parser(
        "eval-quality", help="Run a resumable answer-quality batch after question approval"
    )
    evaluate_quality.add_argument(
        "--questions", type=Path, default=Path("docs/evaluation-questions.json")
    )
    evaluate_quality.add_argument(
        "--output", type=Path, default=Path("runs/quality-evaluation.json")
    )
    evaluate_quality.add_argument("--max-new", type=int, choices=range(1, 55), default=3)
    load = sub.add_parser(
        "load", help="Run one bounded local traffic scenario and retain raw evidence"
    )
    load.add_argument(
        "--scenario",
        required=True,
        choices=[
            "steady",
            "burst",
            "sustained_overload",
            "minute_limit_halved",
            "daily_budget_exhausted",
        ],
    )
    load.add_argument("--source", choices=["real", "stand-in"], default="stand-in")
    load.add_argument("--allow-real", action="store_true")
    load.add_argument("--requests", type=int, choices=range(1, 101), default=6)
    load.add_argument("--rate-per-minute", type=float, default=30.0)
    load.add_argument("--base-url", default="http://127.0.0.1:8000")
    load.add_argument("--questions", type=Path, default=Path("docs/evaluation-questions.json"))
    load.add_argument("--output-root", type=Path, default=Path("runs/experiments"))
    load.add_argument("--server-runs-dir", type=Path)
    load.add_argument("--setting", choices=RETRIEVAL_SETTINGS, default=HYBRID_RERANK)
    report = sub.add_parser(
        "report", help="Reconcile per-run CSV files and regenerate measured tables"
    )
    report.add_argument("--input-root", type=Path, default=Path("runs/experiments"))
    report.add_argument("--output-dir", type=Path, default=Path("runs/submission"))
    report.add_argument("--calibration", type=Path)
    report.add_argument("--quality", type=Path)
    report.add_argument("--grades", type=Path)
    report.add_argument("--service-facts", type=Path)
    args = parser.parse_args(argv)
    settings = None
    try:
        settings = Settings()
        if args.command == "doctor":
            try:
                chunks = load_chunks(settings.relay_data_dir)
                corpus = {"ready": True, "chunks": len(chunks)}
            except ValueError as exc:
                corpus = {"ready": False, "message": str(exc)}
            print(
                json.dumps(
                    {
                        "python": sys.version.split()[0],
                        "groq_key_configured": bool(
                            settings.groq_api_key.get_secret_value().strip()
                        ),
                        "model": settings.groq_model,
                        "corpus": corpus,
                    },
                    indent=2,
                )
            )
        elif args.command == "ingest":
            print(json.dumps(ingest(settings.relay_data_dir), indent=2))
        elif args.command == "index":
            manifest = build_advanced_index(settings.relay_data_dir)
            # Load the reranker now so later measured runs exclude download/startup.
            prepare_models()
            load_retriever(settings.relay_data_dir, HYBRID_RERANK)
            print(json.dumps(manifest, indent=2))
        elif args.command == "retrieve":
            if not 1 <= len(args.question.strip()) <= 2000:
                raise ValueError("Question must contain between 1 and 2000 characters.")
            index = load_retriever(settings.relay_data_dir, args.setting)
            hits = index.search(args.question, k=args.k, setting=args.setting)
            print(
                json.dumps(
                    [
                        {
                            **hit.model_dump(),
                            "url": hit.chunk.url,
                        }
                        for hit in hits
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "ask":
            if settings.relay_source == "real":
                settings.require_key()
            answer = asyncio.run(_ask(settings, args.question, args.setting))
            print(answer.model_dump_json(indent=2))
            return 0 if answer.status == "ok" else 1
        elif args.command == "serve":
            import uvicorn

            from relay.api import create_app

            # Load one shared advanced retriever before Uvicorn starts its event loop.
            index = load_retriever(settings.relay_data_dir, HYBRID_RERANK)
            uvicorn.run(
                create_app(settings, retriever=index), host="127.0.0.1", port=args.port, workers=1
            )
        elif args.command == "calibrate":
            from relay.experiments import calibrate

            print(json.dumps(asyncio.run(calibrate(settings, args.requests)), indent=2))
        elif args.command == "eval-retrieval":
            from relay.evaluation import run_retrieval_evaluation

            print(
                json.dumps(
                    run_retrieval_evaluation(settings.relay_data_dir, args.questions, args.output),
                    indent=2,
                )
            )
        elif args.command == "eval-quality":
            from relay.evaluation import run_quality_evaluation

            if settings.relay_source == "real":
                settings.require_key()
            print(
                json.dumps(
                    asyncio.run(
                        run_quality_evaluation(
                            settings,
                            args.questions,
                            args.output,
                            max_new=args.max_new,
                        )
                    ),
                    indent=2,
                )
            )
        elif args.command == "load":
            from relay.load import (
                load_question_cases,
                preflight_target,
                run_load_experiment,
                validate_load_target,
            )

            validate_load_target(
                args.base_url,
                source=args.source,
                allow_real=args.allow_real,
                count=args.requests,
            )
            cases = load_question_cases(args.questions)

            async def run_load():
                timeout = httpx.Timeout(settings.relay_deadline_seconds + 5, connect=5)
                async with httpx.AsyncClient(
                    base_url=args.base_url, timeout=timeout, trust_env=False
                ) as client:
                    await preflight_target(client, args.source)
                    return await run_load_experiment(
                        client,
                        cases=cases,
                        scenario=args.scenario,
                        source=args.source,
                        retrieval_setting=args.setting,
                        count=args.requests,
                        rate_per_minute=args.rate_per_minute,
                        output_root=args.output_root,
                        server_runs_dir=args.server_runs_dir or settings.relay_runs_dir,
                    )

            print(json.dumps(asyncio.run(run_load()), indent=2))
        elif args.command == "report":
            from relay.report import build_report

            artifacts = build_report(
                args.input_root,
                args.output_dir,
                calibration_path=args.calibration,
                quality_path=args.quality,
                grades_path=args.grades,
                service_facts_path=args.service_facts,
            )
            print(json.dumps({key: str(path) for key, path in artifacts.items()}, indent=2))
        elif args.command == "simulate":
            import uvicorn

            from relay.simulator import Simulation, create_simulator

            controls = {
                "normal": {},
                "slow": {"first_token_ms": 15000},
                "failure": {"fail_every": 2},
                "rate-limit": {"rate_limit_every": 2},
                "load": {"load_ms": 1500},
                "half-minute": {"rpm": 15, "tpm": 4000},
                "daily-exhausted": {"rpd": 0},
            }[args.scenario]
            if args.scenario == "slow" and args.profile:
                raise ValueError("Slow scenario requires no profile (explicit 15-second delay)")
            app = create_simulator(
                Simulation(seed=args.seed, **controls), profile=args.profile, replay=args.replay
            )
            uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1)
        return 0
    except (ValueError, OSError, httpx.HTTPError):
        # Config validation may include secrets as input values: never print raw exceptions.
        if (
            args.command in {"ask", "eval-quality"}
            and settings is not None
            and not settings.groq_api_key.get_secret_value().strip()
        ):
            print("Set GROQ_API_KEY in local .env; never paste it in chat.", file=sys.stderr)
            return 2
        if args.command == "load" and args.source == "real" and not args.allow_real:
            print(
                "Real traffic is disabled by default. Re-run with --allow-real only after "
                "reviewing the request count and local budget ledger.",
                file=sys.stderr,
            )
            return 2
        print(
            "Command failed. Check local configuration, corpus integrity and network access. "
            "Run 'uv run relay doctor' for a safe setup check.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
