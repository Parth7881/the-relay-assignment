"""Frozen-question validation and retrieval-only comparison without hosted calls."""

import asyncio
import hashlib
import json
import math
import statistics
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from relay.corpus import PAPERS
from relay.pipeline import Answer
from relay.retrieval import (
    HYBRID,
    HYBRID_RERANK,
    LEXICAL,
    RETRIEVAL_SETTINGS,
    Searcher,
    load_retriever,
)


class EvaluationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9_-]{2,40}$")
    question: str = Field(min_length=5, max_length=500)
    answerability: Literal["answerable", "unanswerable"]
    expected_papers: list[str] = Field(max_length=3)
    rationale: str = Field(min_length=5, max_length=1000)
    origin: Literal["assistant_draft", "user_authored", "user_revised"]

    @model_validator(mode="after")
    def evidence_contract(self):
        allowed = {paper.id for paper in PAPERS}
        if len(set(self.expected_papers)) != len(self.expected_papers):
            raise ValueError("Expected paper IDs must be unique.")
        if any(paper not in allowed for paper in self.expected_papers):
            raise ValueError("Expected evidence must stay inside the pinned library.")
        if self.answerability == "answerable" and not self.expected_papers:
            raise ValueError("Answerable questions need preliminary expected papers.")
        if self.answerability == "unanswerable" and self.expected_papers:
            raise ValueError("Unanswerable questions cannot claim expected evidence.")
        return self


class QuestionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    review_status: Literal["pending_user", "approved_by_user"]
    questions: list[EvaluationQuestion] = Field(min_length=15)

    @model_validator(mode="after")
    def unique_questions(self):
        ids = [question.id for question in self.questions]
        texts = [" ".join(question.question.casefold().split()) for question in self.questions]
        if len(set(ids)) != len(ids) or len(set(texts)) != len(texts):
            raise ValueError("Question IDs and normalized question text must be unique.")
        return self


def load_question_set(path: Path, *, require_approved: bool = False) -> QuestionSet:
    document = QuestionSet.model_validate_json(path.read_text(encoding="utf-8"))
    if require_approved and document.review_status != "approved_by_user":
        raise ValueError("Evaluation is blocked until explicit user review is recorded.")
    return document


def retrieval_evaluation(retriever: Searcher, questions: QuestionSet) -> dict:
    records = []
    for question in questions.questions:
        for setting in RETRIEVAL_SETTINGS:
            start = time.perf_counter()
            hits = retriever.search(question.question, k=4, setting=setting)
            elapsed = (time.perf_counter() - start) * 1000
            papers = {hit.chunk.paper_id for hit in hits}
            recall = (
                set(question.expected_papers).issubset(papers)
                if question.answerability == "answerable"
                else None
            )
            records.append(
                {
                    "question_id": question.id,
                    "question": question.question,
                    "origin": question.origin,
                    "answerability": question.answerability,
                    "expected_papers": question.expected_papers,
                    "retrieval_setting": setting,
                    "retrieval_ms": elapsed,
                    "context_characters": sum(len(hit.chunk.text) for hit in hits),
                    "paper_recall_at_4": recall,
                    "hits": [hit.model_dump() for hit in hits],
                }
            )
    summary = []
    for setting in RETRIEVAL_SETTINGS:
        rows = [row for row in records if row["retrieval_setting"] == setting]
        graded = [row for row in rows if row["paper_recall_at_4"] is not None]
        summary.append(
            {
                "retrieval_setting": setting,
                "questions": len(rows),
                "answerable_questions": len(graded),
                "paper_recall_at_4": (
                    sum(row["paper_recall_at_4"] for row in graded) / len(graded)
                    if graded
                    else None
                ),
                "median_retrieval_ms": statistics.median(row["retrieval_ms"] for row in rows),
                "median_context_characters": statistics.median(
                    row["context_characters"] for row in rows
                ),
            }
        )
    return {
        "schema_version": 1,
        "kind": "retrieval_only",
        "review_status": questions.review_status,
        "quality_claim_allowed": questions.review_status == "approved_by_user",
        "summary": summary,
        "records": records,
        "note": (
            "Paper recall is a coarse screening metric, not answer correctness or passage support."
        ),
    }


def run_retrieval_evaluation(data_dir: Path, questions_path: Path, output_path: Path) -> dict:
    raw = questions_path.read_bytes()
    questions = load_question_set(questions_path)
    retriever = load_retriever(data_dir, HYBRID_RERANK)
    report = retrieval_evaluation(retriever, questions)
    report["question_set_path"] = str(questions_path)
    report["question_set_sha256"] = hashlib.sha256(raw).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output_path)
    return {
        "output": str(output_path),
        "review_status": questions.review_status,
        "summary": report["summary"],
    }


QualityAsker = Callable[[EvaluationQuestion, str], Awaitable[Answer]]


def evaluation_order(questions: QuestionSet) -> list[EvaluationQuestion]:
    answerable = [q for q in questions.questions if q.answerability == "answerable"]
    unanswerable = [q for q in questions.questions if q.answerability == "unanswerable"]
    if not unanswerable:
        return answerable
    stride = math.ceil(len(answerable) / len(unanswerable))
    ordered: list[EvaluationQuestion] = []
    for index, question in enumerate(unanswerable):
        ordered.append(question)
        ordered.extend(answerable[index * stride : (index + 1) * stride])
    ordered.extend(answerable[len(unanswerable) * stride :])
    return ordered


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _load_quality_artifact(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


async def evaluate_quality(
    questions: QuestionSet,
    output_path: Path,
    ask_one: QualityAsker,
    *,
    question_set_sha256: str,
    max_new: int | None = None,
) -> dict:
    """Run and checkpoint answer cases; grading remains an explicit human action."""
    if questions.review_status != "approved_by_user":
        raise ValueError("Evaluation is blocked until explicit user review is recorded.")
    if max_new is not None and max_new < 1:
        raise ValueError("max_new must be at least one when supplied.")
    report = await asyncio.to_thread(_load_quality_artifact, output_path)
    if report is not None:
        if report.get("question_set_sha256") != question_set_sha256:
            raise ValueError("Existing evaluation belongs to a different question set.")
        if report.get("kind") != "answer_quality" or not isinstance(report.get("records"), list):
            raise ValueError("Existing evaluation artifact is invalid.")
    else:
        report = {
            "schema_version": 1,
            "kind": "answer_quality",
            "question_set_sha256": question_set_sha256,
            "human_review_status": "pending_user",
            "quality_claim_allowed": False,
            "records": [],
            "grading_note": (
                "answer_grade and grading_rationale remain null until explicit human review."
            ),
        }
    complete = {
        (record.get("question_id"), record.get("retrieval_setting"))
        for record in report["records"]
        if record.get("case_complete") is True
    }
    added = 0
    for question in evaluation_order(questions):
        for setting in RETRIEVAL_SETTINGS:
            if (question.id, setting) in complete:
                continue
            if max_new is not None and added >= max_new:
                return report
            answer = await ask_one(question, setting)
            case_complete = answer.status == "ok" and answer.disposition in {
                "answered",
                "refused",
            }
            report["records"].append(
                {
                    "question_id": question.id,
                    "question": question.question,
                    "origin": question.origin,
                    "preliminary_answerability": question.answerability,
                    "preliminary_expected_papers": question.expected_papers,
                    "preliminary_rationale": question.rationale,
                    "retrieval_setting": setting,
                    "answer": answer.model_dump(mode="json"),
                    "case_complete": case_complete,
                    "answer_grade": None,
                    "grading_rationale": None,
                }
            )
            if case_complete:
                complete.add((question.id, setting))
            added += 1
            await asyncio.to_thread(_write_json_atomic, output_path, report)
    return report


def quality_progress(report: dict, *, planned: int) -> dict:
    complete = {
        (record.get("question_id"), record.get("retrieval_setting"))
        for record in report.get("records", [])
        if record.get("case_complete") is True
    }
    return {
        "attempted_records": len(report.get("records", [])),
        "completed_cases": len(complete),
        "planned_cases": planned,
    }


async def run_quality_evaluation(
    settings,
    questions_path: Path,
    output_path: Path,
    *,
    max_new: int | None = None,
) -> dict:
    """Run a resumable real/stand-in quality batch through the complete pipeline."""
    import httpx

    from relay.pipeline import Pipeline
    from relay.policy import Admission, Budget, ManagedModel
    from relay.provider import GroqProvider

    if settings.relay_source == "real":
        settings.require_key()
    # Offline evaluation may wait through one minute-cap reset; interactive Ask remains fail-fast.
    settings = settings.model_copy(update={"relay_deadline_seconds": 120})
    raw = await asyncio.to_thread(questions_path.read_bytes)
    digest = hashlib.sha256(raw).hexdigest()
    questions = await asyncio.to_thread(load_question_set, questions_path, require_approved=True)
    lexical = load_retriever(settings.relay_data_dir, LEXICAL)
    advanced = load_retriever(settings.relay_data_dir, HYBRID_RERANK)
    retrievers = {LEXICAL: lexical, HYBRID: advanced, HYBRID_RERANK: advanced}
    budget = Budget(settings.relay_runs_dir / f"budget-{settings.relay_source}.sqlite3", settings)
    admission = Admission(1, settings.relay_queue_capacity, settings.relay_queue_wait_seconds)
    async with httpx.AsyncClient(trust_env=False) as client:
        provider = GroqProvider(settings, client)

        async def ask_one(question: EvaluationQuestion, setting: str) -> Answer:
            return await Pipeline(
                retrievers[setting],
                ManagedModel(
                    provider,
                    budget,
                    settings,
                    wait_for_minute_capacity=True,
                ),
                settings.relay_runs_dir,
                deadline=settings.relay_deadline_seconds,
                source=settings.relay_source,
                admission=admission,
                retrieval_setting=setting,
            ).ask(question.question)

        report = await evaluate_quality(
            questions,
            output_path,
            ask_one,
            question_set_sha256=digest,
            max_new=max_new,
        )
    planned = len(questions.questions) * len(RETRIEVAL_SETTINGS)
    return {
        "output": str(output_path),
        **quality_progress(report, planned=planned),
        "human_review_status": report["human_review_status"],
        "quality_claim_allowed": report["quality_claim_allowed"],
    }
