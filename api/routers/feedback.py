"""Feedback routes: record a thumbs up/down and report aggregate counts."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select

import api.main as api_main
from api.auth import UserOut
from api.deps import DataUser, _resolve_student, _student_for_read, require_api_key
from api.schemas import FeedbackRequest, FeedbackResponse, FeedbackSummary
from db.models import Feedback
from db.session import get_session

router = APIRouter()


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def submit_feedback(request: FeedbackRequest, user: UserOut | None = DataUser) -> dict[str, int]:
    """Persist a student's thumbs up/down on a tutor answer.

    The student is ensured to exist (and linked to the caller when
    authenticated). The captured question/answer text makes the feedback
    self-contained so it can later feed offline evaluation. Returns 201 with the
    new row id; an invalid ``rating`` is rejected with 422 by request
    validation. This route reaches no LLM and runs no retrieval.
    """
    with get_session(api_main._engine) as session:
        student = _resolve_student(session, request.student_id, user)
        row = Feedback(
            student_id=student.id,
            rating=request.rating,
            note=request.note,
            question=request.question,
            answer=request.answer,
        )
        session.add(row)
        session.flush()
        feedback_id = row.id
    return {"id": feedback_id}


@router.get(
    "/feedback/summary",
    response_model=FeedbackSummary,
    dependencies=[Depends(require_api_key)],
)
def feedback_summary(student_id: str, user: UserOut | None = DataUser) -> dict[str, int]:
    """Return thumbs up/down counts for a student.

    An unknown student yields zero counts rather than an error. Useful for a
    lightweight quality signal without exposing individual feedback rows. In
    require_auth mode the student must belong to the caller (403 otherwise).
    """
    with get_session(api_main._engine) as session:
        student = _student_for_read(session, student_id, user)
        if student is None:
            return {"up": 0, "down": 0}
        up = session.scalar(
            select(func.count())
            .select_from(Feedback)
            .where(Feedback.student_id == student.id, Feedback.rating == 1)
        )
        down = session.scalar(
            select(func.count())
            .select_from(Feedback)
            .where(Feedback.student_id == student.id, Feedback.rating == -1)
        )
    return {"up": up or 0, "down": down or 0}
