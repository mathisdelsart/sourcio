"""Exercise routes: generate a grounded exercise and review it after the fact."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

import api.main as api_main
from api.auth import UserOut
from api.deps import (
    ROLE_EXERCISE,
    DataUser,
    OpenAIKey,
    _iso_utc,
    _record_activity,
    _resolve_student,
    _student_for_read,
    require_api_key,
)
from api.schemas import ExerciseRequest, ExerciseResponse, ExerciseReviewResponse
from core.errors import raise_friendly_llm_error
from db.models import Exercise, Grade
from db.session import get_session

router = APIRouter()


@router.post("/exercise", response_model=ExerciseResponse, dependencies=[Depends(require_api_key)])
def exercise(
    request: ExerciseRequest,
    user: UserOut | None = DataUser,
    openai_key: str | None = OpenAIKey,
) -> dict[str, Any]:
    """Generate a course-grounded exercise on the requested notion.

    The reference solution stays server-side and is never returned. The student
    is ensured to exist (and linked to the caller when authenticated); exercise
    persistence is owned by the agent node, which needs the ``student_id`` to
    store the exercise. The persisted exercise id is surfaced so a later
    ``/grade`` call can link the grade back to it.
    """
    with get_session(api_main._engine) as session:
        _resolve_student(session, request.student_id, user)
    try:
        state = api_main.generate(
            {
                "message": request.notion,
                "student_id": request.student_id,
                "course": request.course,
                "chapter": request.chapter,
                "language": request.language,
                "api_key": openai_key,
            }
        )
    except Exception as exc:
        raise_friendly_llm_error(exc, used_own_key=bool(openai_key))
        raise
    # generate always populates "exercise" (a built exercise or a refusal).
    built = state.get("exercise")
    assert built is not None
    # Record the generated exercise as an activity turn so it shows in history
    # next to the Q&A. The activity content is the student's request (the typed
    # notion), so the history card shows the ask; the full problem/solution stays
    # behind the "Show details" fetch (GET /exercise/{id}/review). Skip on
    # refusal: an uncovered notion produces no activity.
    if not built["refused"]:
        _record_activity(
            request.student_id,
            user,
            request.session_id,
            role=ROLE_EXERCISE,
            content=request.notion,
            ref_id=built.get("id"),
        )
    return {"problem": built["problem"], "refused": built["refused"], "id": built.get("id")}


@router.get(
    "/exercise/{exercise_id}/review",
    response_model=ExerciseReviewResponse,
    dependencies=[Depends(require_api_key)],
)
def exercise_review(
    exercise_id: int, student_id: str, user: UserOut | None = DataUser
) -> dict[str, Any]:
    """Return a generated exercise's full content for after-the-fact review.

    Unlike ``/exercise``, the reference solution is returned: review happens once
    the exercise is done, so the student is meant to see the model answer. The
    latest grade on the exercise (if any) is included so the student can see their
    answer, score and feedback. Ownership is enforced: the exercise must belong to
    ``student_id`` and, when authenticated, that student must belong to the caller
    (403 otherwise). An unknown or unowned exercise yields 404.
    """
    with get_session(api_main._engine) as session:
        student = _student_for_read(session, student_id, user)
        ex = None
        if student is not None:
            ex = session.scalar(
                select(Exercise).where(
                    Exercise.id == exercise_id, Exercise.student_id == student.id
                )
            )
        if ex is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Exercise not found for this student.",
            )
        latest = session.scalar(
            select(Grade)
            .where(Grade.exercise_id == ex.id)
            .order_by(Grade.created_at.desc(), Grade.id.desc())
        )
        grade_payload = None
        if latest is not None:
            grade_payload = {
                "answer": latest.answer,
                "score": latest.score,
                "feedback": latest.feedback,
                "created_at": _iso_utc(latest.created_at),
            }
        return {
            "problem": ex.problem,
            "reference_solution": ex.reference_solution,
            "grade": grade_payload,
        }
