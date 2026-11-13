"""Local-only API with bounded admission and persistent protective budgets."""

import asyncio
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from relay.config import Settings
from relay.corpus import PAPERS
from relay.pipeline import Answer, Pipeline
from relay.policy import Admission, Budget, ManagedModel
from relay.provider import GroqProvider, ProviderError
from relay.retrieval import HYBRID, HYBRID_RERANK, LEXICAL, Searcher, load_retriever


class Question(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    retrieval_setting: Literal[
        "lexical-word180-k4-v1",
        "hybrid-minilm220-rrf-k4-v1",
        "hybrid-minilm220-rrf-rerank-k4-v1",
    ] = LEXICAL


class BodyLimit:
    def __init__(self, app, limit: int = 16384):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                return await JSONResponse({"detail": "Request body too large"}, 413)(
                    scope, receive, send
                )
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def cancel_on_disconnect(request: Request, work):
    async def watch():
        # The endpoint body is already parsed; wait for ASGI disconnect without polling.
        while True:
            if (await request.receive())["type"] == "http.disconnect":
                return

    task, watcher = asyncio.create_task(work), asyncio.create_task(watch())
    try:
        done, _ = await asyncio.wait({task, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            return task.result()
        raise HTTPException(499, "Client disconnected")
    finally:
        for pending in (task, watcher):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, watcher, return_exceptions=True)


def create_app(settings: Settings | None = None, *, retriever: Searcher | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="The Relay", version="0.1.0")
    app.add_middleware(BodyLimit)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )
    app.state.retrievers = (
        {setting: retriever for setting in (LEXICAL, HYBRID, HYBRID_RERANK)} if retriever else {}
    )
    app.state.retriever_locks = {
        LEXICAL: asyncio.Lock(),
        HYBRID_RERANK: asyncio.Lock(),
    }
    admission = Admission(
        settings.relay_concurrency, settings.relay_queue_capacity, settings.relay_queue_wait_seconds
    )
    budget = Budget(settings.relay_runs_dir / f"budget-{settings.relay_source}.sqlite3", settings)

    async def get_retriever(setting: str = LEXICAL) -> Searcher:
        if setting in app.state.retrievers:
            return app.state.retrievers[setting]
        load_setting = LEXICAL if setting == LEXICAL else HYBRID_RERANK
        async with app.state.retriever_locks[load_setting]:
            if setting in app.state.retrievers:
                return app.state.retrievers[setting]
            try:
                async with asyncio.timeout(settings.relay_deadline_seconds):
                    loaded = await asyncio.to_thread(
                        load_retriever, settings.relay_data_dir, load_setting
                    )
            except ValueError as exc:
                raise HTTPException(503, str(exc)) from exc
            except TimeoutError as exc:
                raise HTTPException(
                    503, "Retriever warmup timed out. Run 'uv run relay index' and retry."
                ) from exc
            if load_setting == LEXICAL:
                app.state.retrievers[LEXICAL] = loaded
            else:
                app.state.retrievers[HYBRID] = loaded
                app.state.retrievers[HYBRID_RERANK] = loaded
            return app.state.retrievers[setting]

    @app.get("/health")
    async def health():
        try:
            await get_retriever(HYBRID_RERANK)
            ready = True
        except HTTPException:
            ready = False
        return {
            "status": "ok",
            "phase": "part-4",
            "source": settings.relay_source,
            "corpus_ready": ready,
            "model_configured": settings.relay_source == "stand-in"
            or bool(settings.groq_api_key.get_secret_value().strip()),
        }

    @app.get("/api/library")
    async def library():
        return [{**paper.model_dump(), "url": paper.url} for paper in PAPERS]

    @app.post("/api/retrieve")
    async def retrieve(body: Question):
        index = await get_retriever(body.retrieval_setting)
        queue_metrics: dict = {}
        try:
            async with admission.enter(queue_metrics):
                hits = await asyncio.to_thread(
                    index.search, body.question, k=4, setting=body.retrieval_setting
                )
        except ProviderError as exc:
            status_code = 429 if exc.status == "rate_limited" else 504
            raise HTTPException(status_code, str(exc)) from exc
        return {
            "retrieval_setting": body.retrieval_setting,
            "evidence": [hit.model_dump() for hit in hits],
        }

    @app.post("/api/ask", response_model=Answer)
    async def ask(body: Question, request: Request):
        try:
            if settings.relay_source == "real":
                settings.require_key()
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc
        index = await get_retriever(body.retrieval_setting)
        async with httpx.AsyncClient(trust_env=False) as client:
            pipeline = Pipeline(
                index,
                ManagedModel(GroqProvider(settings, client), budget, settings),
                settings.relay_runs_dir,
                deadline=settings.relay_deadline_seconds,
                source=settings.relay_source,
                admission=admission,
                retrieval_setting=body.retrieval_setting,
            )
            return await cancel_on_disconnect(request, pipeline.ask(body.question))

    ui_index = settings.relay_ui_dir / "index.html"
    ui_assets = settings.relay_ui_dir / "assets"
    if ui_index.is_file():
        if ui_assets.is_dir():
            app.mount("/assets", StaticFiles(directory=ui_assets), name="ui-assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def ui_fallback(path: str):
            if path == "api" or path.startswith("api/") or path == "health":
                raise HTTPException(404, "Not found")
            return FileResponse(ui_index)

    return app
