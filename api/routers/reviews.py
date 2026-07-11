"""Spaced-repetition routes: record recalls, enqueue notions, list due ones."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

import api.main as api_main
from api.auth import UserOut
from api.deps import DataUser, _iso_utc, _resolve_student, _student_for_read, require_api_key
from api.schemas import EnqueueReviewRequest, ReviewRequest, ReviewSchedule
from core.scheduling import schedule
from db.models import Review
from db.session import get_session

router = APIRouter()


@router.post(
    "/reviews",
    response_model=ReviewSchedule,
    dependencies=[Depends(require_api_key)],
)
def record_review(request: ReviewRequest, user: UserOut | None = DataUser) -> dict[str, Any]:
    """Record a recall rating for a notion and return its updated schedule.

    The student is ensured to exist (and linked to the caller when
    authenticated). At most one review row exists per ``(student, notion)``: an
    existing row is updated in place, otherwise a fresh one is created. The SM-2
    step is applied by ``core.scheduling.schedule`` and ``due_at`` is computed
    from a timezone-aware "now" plus the new interval. An out-of-range
    ``quality`` is rejected with 422 by request validation. This route reaches no
    LLM and runs no retrieval.
    """
    now = datetime.now(UTC)
    with get_session(api_main._engine) as session:
        student = _resolve_student(session, request.student_id, user)
        row = session.scalar(
            select(Review).where(Review.student_id == student.id, Review.notion == request.notion)
        )
        if row is None:
            # A fresh notion starts from the SM-2 defaults; the column defaults
            # only materialise on flush, so seed the values explicitly here.
            row = Review(
                student_id=student.id,
                notion=request.notion,
                ease=2.5,
                interval_days=0,
                repetitions=0,
            )
            session.add(row)

        state = schedule(
            ease=row.ease,
            interval_days=row.interval_days,
            repetitions=row.repetitions,
            quality=request.quality,
        )
        row.ease = state.ease
        row.interval_days = state.interval_days
        row.repetitions = state.repetitions
        row.last_reviewed = now
        due_at = now + timedelta(days=state.interval_days)
        row.due_at = due_at
        session.flush()

        return {
            "notion": row.notion,
            "ease": row.ease,
            "interval_days": row.interval_days,
            "due_at": _iso_utc(due_at),
        }


@router.post(
    "/reviews/enqueue",
    response_model=ReviewSchedule,
    dependencies=[Depends(require_api_key)],
)
def enqueue_review(
    request: EnqueueReviewRequest, user: UserOut | None = DataUser
) -> dict[str, Any]:
    """Add a notion to the spaced-repetition queue, due immediately.

    The student is ensured to exist (and linked to the caller when
    authenticated). At most one review row exists per ``(student, notion)``: an
    existing row is reset to the SM-2 defaults rather than duplicated. No SM-2
    step is applied; ``due_at`` is set to "now" so the notion is due right away
    and appears in ``GET /reviews/due``, ready for its first rating. This route
    reaches no LLM and runs no retrieval.
    """
    now = datetime.now(UTC)
    with get_session(api_main._engine) as session:
        student = _resolve_student(session, request.student_id, user)
        row = session.scalar(
            select(Review).where(Review.student_id == student.id, Review.notion == request.notion)
        )
        if row is None:
            row = Review(student_id=student.id, notion=request.notion)
            session.add(row)
        # Seed (or reset) the SM-2 state so the notion is due immediately.
        row.ease = 2.5
        row.interval_days = 0
        row.repetitions = 0
        row.last_reviewed = None
        row.due_at = now
        session.flush()

        return {
            "notion": row.notion,
            "ease": row.ease,
            "interval_days": row.interval_days,
            "due_at": _iso_utc(now),
        }


@router.get(
    "/reviews/due",
    response_model=list[ReviewSchedule],
    dependencies=[Depends(require_api_key)],
)
def due_reviews(student_id: str, user: UserOut | None = DataUser) -> list[dict[str, Any]]:
    """List the student's notions due for review, soonest first.

    A notion is due when its ``due_at`` is at or before "now". Newly created
    rows default ``due_at`` to their creation time, so brand-new notions are due
    immediately and surface here too. An unknown student yields an empty list
    rather than an error. This route reaches no LLM and runs no retrieval. In
    require_auth mode the student must belong to the caller (403 otherwise).
    """
    now = datetime.now(UTC)
    with get_session(api_main._engine) as session:
        student = _student_for_read(session, student_id, user)
        if student is None:
            return []
        rows = session.scalars(
            select(Review)
            .where(Review.student_id == student.id, Review.due_at <= now)
            .order_by(Review.due_at.asc(), Review.id.asc())
        )
        return [
            {
                "notion": row.notion,
                "ease": row.ease,
                "interval_days": row.interval_days,
                "due_at": _iso_utc(row.due_at),
            }
            for row in rows
        ]
