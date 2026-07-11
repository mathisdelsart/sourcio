"""Quiz routes: generate a grounded quiz, grade answers, and review it."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

import api.main as api_main
from api.auth import UserOut
from api.deps import (
    ROLE_QUIZ,
    DataUser,
    OpenAIKey,
    _record_activity,
    _resolve_student,
    _student_for_read,
    require_api_key,
)
from api.schemas import (
    GradeResponse,
    QuizGradeAllRequest,
    QuizGradeRequest,
    QuizRequest,
    QuizResponse,
    QuizReviewResponse,
    QuizSummaryResponse,
)
from core.errors import raise_friendly_llm_error
from db.models import Grade, Quiz, QuizQuestion
from db.session import get_session

router = APIRouter()


@router.post("/quiz", response_model=QuizResponse, dependencies=[Depends(require_api_key)])
def quiz(
    request: QuizRequest,
    user: UserOut | None = DataUser,
    openai_key: str | None = OpenAIKey,
) -> dict[str, Any]:
    """Generate a course-grounded quiz of ``n`` questions on the requested notion.

    Reference solutions stay server-side and are never returned: each question is
    surfaced as ``{id, problem}`` only. The student is ensured to exist (and
    linked to the caller when authenticated); quiz persistence is owned by the
    quiz node, which needs the ``student_id`` to store the quiz and its questions.
    A refusal (empty ``questions``) is returned when the course does not cover the
    notion.
    """
    with get_session(api_main._engine) as session:
        _resolve_student(session, request.student_id, user)
    try:
        result = api_main.generate_quiz(
            request.notion,
            request.n,
            request.student_id,
            course=request.course,
            chapter=request.chapter,
            language=request.language,
            api_key=openai_key,
        )
    except Exception as exc:
        raise_friendly_llm_error(exc, used_own_key=bool(openai_key))
        raise
    # Record a concise activity turn (the notion + question count), never the full
    # quiz JSON. Skip on refusal: an uncovered notion produces no questions.
    if not result["refused"] and result["questions"]:
        count = len(result["questions"])
        summary = f"{result['notion']} ({count} question{'s' if count != 1 else ''})"
        _record_activity(
            request.student_id,
            user,
            request.session_id,
            role=ROLE_QUIZ,
            content=summary,
            ref_id=result.get("quiz_id"),
        )
    return result


@router.post(
    "/quiz/{quiz_id}/grade",
    response_model=GradeResponse,
    dependencies=[Depends(require_api_key)],
)
def quiz_grade(
    quiz_id: int,
    request: QuizGradeRequest,
    user: UserOut | None = DataUser,
    openai_key: str | None = OpenAIKey,
) -> dict[str, Any]:
    """Grade one quiz answer against the question's stored reference solution.

    The reference solution is never sent by the client: it is loaded server-side
    from the persisted quiz question. The student is ensured to exist (and linked
    to the caller when authenticated). The verdict is persisted as a grade linked
    to the question. An unknown question (or one not belonging to ``quiz_id``)
    yields 404.
    """
    with get_session(api_main._engine) as session:
        _resolve_student(session, request.student_id, user)
    try:
        verdict = api_main.grade_quiz_answer(
            quiz_id,
            request.question_id,
            request.answer,
            request.student_id,
            request.rigor,
            openai_key,
        )
    except Exception as exc:
        raise_friendly_llm_error(exc, used_own_key=bool(openai_key))
        raise
    if verdict is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quiz question not found.",
        )
    return {"score": verdict["score"], "feedback": verdict["feedback"]}


@router.post(
    "/quiz/{quiz_id}/grade-all",
    response_model=QuizSummaryResponse,
    dependencies=[Depends(require_api_key)],
)
def quiz_grade_all(
    quiz_id: int,
    request: QuizGradeAllRequest,
    user: UserOut | None = DataUser,
    openai_key: str | None = OpenAIKey,
) -> dict[str, Any]:
    """Grade every answered question of a quiz at once and return a final score.

    Each answer is graded against its question's stored reference solution (loaded
    server-side, never sent by the client) and every verdict is persisted, exactly
    like one-by-one grading. The response carries the average score, the per-
    question verdicts, and a short study recommendation drawn from all the feedback
    in the language of the student's answers. The student is ensured to exist (and
    linked to the caller when authenticated). Questions that cannot be resolved are
    skipped rather than failing the whole request.
    """
    with get_session(api_main._engine) as session:
        _resolve_student(session, request.student_id, user)
    answers = [{"question_id": a.question_id, "answer": a.answer} for a in request.answers]
    return api_main.summarize_quiz(quiz_id, answers, request.student_id, request.rigor, openai_key)


@router.get(
    "/quiz/{quiz_id}/review",
    response_model=QuizReviewResponse,
    dependencies=[Depends(require_api_key)],
)
def quiz_review(quiz_id: int, student_id: str, user: UserOut | None = DataUser) -> dict[str, Any]:
    """Return a quiz's full content for after-the-fact review.

    Unlike ``/quiz``, each question's reference solution is returned, together
    with the student's latest answer, score and feedback per question (``None``
    when unanswered). Questions are ordered by position. Ownership is enforced:
    the quiz must belong to ``student_id`` and, when authenticated, that student
    must belong to the caller (403 otherwise). An unknown or unowned quiz yields
    404.
    """
    with get_session(api_main._engine) as session:
        student = _student_for_read(session, student_id, user)
        quiz_row = None
        if student is not None:
            quiz_row = session.scalar(
                select(Quiz).where(Quiz.id == quiz_id, Quiz.student_id == student.id)
            )
        if quiz_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quiz not found for this student.",
            )
        questions = session.scalars(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_id == quiz_row.id)
            .order_by(QuizQuestion.position.asc(), QuizQuestion.id.asc())
        )
        reviewed: list[dict[str, Any]] = []
        for q in questions:
            latest = session.scalar(
                select(Grade)
                .where(Grade.quiz_question_id == q.id)
                .order_by(Grade.created_at.desc(), Grade.id.desc())
            )
            reviewed.append(
                {
                    "position": q.position,
                    "problem": q.problem,
                    "reference_solution": q.reference_solution,
                    "answer": latest.answer if latest is not None else None,
                    "score": latest.score if latest is not None else None,
                    "feedback": latest.feedback if latest is not None else None,
                }
            )
        return {"notion": quiz_row.notion, "questions": reviewed}
