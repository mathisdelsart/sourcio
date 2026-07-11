"""Conversation history routes: replay and clear a student's turns."""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

import api.main as api_main
from api.auth import UserOut
from api.deps import DataUser, _iso_utc, _student_for_read, require_api_key
from api.schemas import HistoryItem
from db.models import Session as SessionModel
from db.session import delete_messages, get_session, recent_messages

router = APIRouter()


@router.get(
    "/history/{student_id}",
    response_model=list[HistoryItem],
    dependencies=[Depends(require_api_key)],
)
def history(
    student_id: str, limit: int = 20, user: UserOut | None = DataUser
) -> list[dict[str, Any]]:
    """Return the student's most recent turns in chronological order.

    An unknown student yields an empty history rather than an error. In
    require_auth mode the student must belong to the caller (403 otherwise).
    """
    with get_session(api_main._engine) as session:
        student = _student_for_read(session, student_id, user)
        if student is None:
            return []
        rows = recent_messages(session, student.id, limit=limit)
        return [
            {
                "role": row.role,
                "content": row.content,
                "created_at": _iso_utc(row.created_at),
                "ref_id": row.ref_id,
            }
            for row in rows
        ]


@router.delete(
    "/history/{student_id}",
    dependencies=[Depends(require_api_key)],
)
def clear_history(
    student_id: str, session_id: int | None = None, user: UserOut | None = DataUser
) -> dict[str, int]:
    """Delete a student's conversation messages and report how many were removed.

    With ``session_id`` set, only that thread's messages are cleared (after
    verifying the thread belongs to the student); without it, every message of
    the student is deleted. An unknown student, or a thread that is not owned by
    the student, yields ``{"deleted": 0}`` rather than an error, mirroring the
    idempotent style of the other delete routes. In require_auth mode the student
    must belong to the caller (403 otherwise).
    """
    with get_session(api_main._engine) as session:
        student = _student_for_read(session, student_id, user)
        if student is None:
            return {"deleted": 0}
        if session_id is not None:
            thread = session.scalar(
                select(SessionModel).where(
                    SessionModel.id == session_id, SessionModel.student_id == student.id
                )
            )
            if thread is None:
                return {"deleted": 0}
        deleted = delete_messages(session, student.id, session_id=session_id)
        return {"deleted": deleted}
