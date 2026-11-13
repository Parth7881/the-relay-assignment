import json

import pytest

from relay.corpus import PAPERS, chunk_page
from relay.evaluation import (
    evaluate_quality,
    evaluation_order,
    load_question_set,
    quality_progress,
    retrieval_evaluation,
)
from relay.pipeline import Answer
from relay.retrieval import HYBRID, HYBRID_RERANK, LEXICAL, Hit


def question_document(status="pending_user"):
    questions = []
    for index in range(15):
        answerable = index < 12
        questions.append(
            {
                "id": f"q{index + 1:02}",
                "question": f"Original evaluation question {index + 1}?",
                "answerability": "answerable" if answerable else "unanswerable",
                "expected_papers": [PAPERS[index % 3].id] if answerable else [],
                "rationale": "Fixture rationale.",
                "origin": "assistant_draft",
            }
        )
    return {"schema_version": 1, "review_status": status, "questions": questions}


def test_question_set_requires_15_unique_original_questions_and_human_review(tmp_path):
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(question_document()))
    draft = load_question_set(path)
    assert len(draft.questions) == 15
    with pytest.raises(ValueError, match="user review"):
        load_question_set(path, require_approved=True)
    approved = question_document("approved_by_user")
    approved["questions"][1]["id"] = approved["questions"][0]["id"]
    path.write_text(json.dumps(approved))
    with pytest.raises(ValueError, match="unique"):
        load_question_set(path)


def test_retrieval_evaluation_preserves_hits_and_does_not_grade_unanswerable(tmp_path):
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(question_document()))
    chunk = chunk_page(PAPERS[0], 2, "Evidence for the original evaluation question.")[0]

    class Searcher:
        def search(self, question, *, k, setting, expanded=False):
            return [Hit(chunk=chunk, score=1, scores={"fixture": 1})]

    report = retrieval_evaluation(Searcher(), load_question_set(path))
    assert len(report["records"]) == 45
    assert {row["retrieval_setting"] for row in report["records"]} == {
        LEXICAL,
        HYBRID,
        HYBRID_RERANK,
    }
    assert report["records"][0]["hits"][0]["chunk"]["page"] == 2
    unanswerable = [row for row in report["records"] if row["answerability"] == "unanswerable"]
    assert all(row["paper_recall_at_4"] is None for row in unanswerable)
    assert report["review_status"] == "pending_user"


def test_multi_paper_question_requires_every_expected_paper(tmp_path):
    document = question_document()
    document["questions"][0]["expected_papers"] = [PAPERS[0].id, PAPERS[1].id]
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(document))
    chunk = chunk_page(PAPERS[0], 2, "Only one expected paper is present.")[0]

    class Searcher:
        def search(self, question, *, k, setting, expanded=False):
            return [Hit(chunk=chunk, score=1)]

    report = retrieval_evaluation(Searcher(), load_question_set(path))
    rows = [row for row in report["records"] if row["question_id"] == "q01"]
    assert all(row["paper_recall_at_4"] is False for row in rows)


@pytest.mark.asyncio
async def test_quality_evaluation_is_resumable_and_leaves_human_grades_pending(tmp_path):
    document = question_document("approved_by_user")
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    questions = load_question_set(path, require_approved=True)
    output = tmp_path / "quality.json"
    chunk = chunk_page(PAPERS[0], 2, "Evidence preserved for human review.")[0]
    calls = []

    async def ask_one(question, setting):
        calls.append((question.id, setting))
        return Answer(
            request_id=f"request-{len(calls)}",
            question=question.question,
            start_time="2026-11-12T10:00:00+00:00",
            source="real",
            status="ok",
            disposition="answered",
            answer="A grounded answer. [chunk]",
            evidence=[Hit(chunk=chunk, score=1, scores={"fixture": 1})],
            first_token_ms=None,
            total_ms=125,
            tokens_in=100,
            tokens_out=20,
            retries=0,
            retrieval_setting=setting,
            reason="support_checks_passed",
        )

    first = await evaluate_quality(
        questions,
        output,
        ask_one,
        question_set_sha256="fixed-question-hash",
        max_new=2,
    )
    assert len(first["records"]) == 2
    assert first["human_review_status"] == "pending_user"
    assert first["quality_claim_allowed"] is False
    assert first["records"][0]["answer_grade"] is None
    assert first["records"][0]["grading_rationale"] is None
    assert first["records"][0]["answer"]["evidence"][0]["chunk"]["page"] == 2

    second = await evaluate_quality(
        questions,
        output,
        ask_one,
        question_set_sha256="fixed-question-hash",
        max_new=2,
    )
    assert len(second["records"]) == 4
    assert calls == [
        ("q13", LEXICAL),
        ("q13", HYBRID),
        ("q13", HYBRID_RERANK),
        ("q01", LEXICAL),
    ]
    assert json.loads(output.read_text(encoding="utf-8"))["records"] == second["records"]


@pytest.mark.asyncio
async def test_quality_resume_rejects_a_different_question_set(tmp_path):
    questions = load_question_set(
        _write_questions(tmp_path, question_document("approved_by_user")), require_approved=True
    )
    output = tmp_path / "quality.json"
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "answer_quality",
                "question_set_sha256": "old-hash",
                "human_review_status": "pending_user",
                "quality_claim_allowed": False,
                "records": [],
            }
        ),
        encoding="utf-8",
    )

    async def must_not_run(question, setting):
        raise AssertionError("A mismatched resume artifact must not call the model.")

    with pytest.raises(ValueError, match="question set"):
        await evaluate_quality(
            questions,
            output,
            must_not_run,
            question_set_sha256="new-hash",
            max_new=1,
        )


@pytest.mark.asyncio
async def test_quality_resume_preserves_but_retries_an_operational_failure(tmp_path):
    questions = load_question_set(
        _write_questions(tmp_path, question_document("approved_by_user")), require_approved=True
    )
    output = tmp_path / "quality.json"
    outcomes = [
        ("rate_limited", "unavailable", "minute_budget_exhausted"),
        ("ok", "refused", "insufficient_evidence"),
    ]

    async def ask_one(question, setting):
        status, disposition, reason = outcomes.pop(0)
        return Answer(
            request_id=f"request-{len(outcomes)}",
            question=question.question,
            start_time="2026-11-12T10:00:00+00:00",
            source="real",
            status=status,
            disposition=disposition,
            answer="No unverified answer released.",
            total_ms=10,
            tokens_in=0,
            tokens_out=0,
            retrieval_setting=setting,
            reason=reason,
        )

    first = await evaluate_quality(
        questions, output, ask_one, question_set_sha256="same-hash", max_new=1
    )
    second = await evaluate_quality(
        questions, output, ask_one, question_set_sha256="same-hash", max_new=1
    )
    assert [row["answer"]["status"] for row in second["records"]] == ["rate_limited", "ok"]
    assert first["records"][0]["case_complete"] is False
    assert second["records"][1]["case_complete"] is True
    assert second["records"][0]["question_id"] == second["records"][1]["question_id"]
    assert (
        second["records"][0]["retrieval_setting"]
        == second["records"][1]["retrieval_setting"]
        == LEXICAL
    )


def _write_questions(tmp_path, document):
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_quality_progress_counts_completed_cases_not_failed_attempts():
    report = {
        "records": [
            {
                "question_id": "q01",
                "retrieval_setting": LEXICAL,
                "case_complete": False,
            },
            {
                "question_id": "q01",
                "retrieval_setting": LEXICAL,
                "case_complete": True,
            },
            {
                "question_id": "q01",
                "retrieval_setting": HYBRID,
                "case_complete": True,
            },
        ]
    }
    assert quality_progress(report, planned=45) == {
        "attempted_records": 3,
        "completed_cases": 2,
        "planned_cases": 45,
    }


def test_evaluation_order_interleaves_unanswerables_before_budget_exhaustion(tmp_path):
    questions = load_question_set(
        _write_questions(tmp_path, question_document("approved_by_user")), require_approved=True
    )
    assert [question.id for question in evaluation_order(questions)] == [
        "q13",
        "q01",
        "q02",
        "q03",
        "q04",
        "q14",
        "q05",
        "q06",
        "q07",
        "q08",
        "q15",
        "q09",
        "q10",
        "q11",
        "q12",
    ]
