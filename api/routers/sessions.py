"""Conversation-thread routes: create, list, read messages, and delete."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

import api.main as api_main
from api.auth import UserOut
from api.deps import DataUser, _iso_utc, _resolve_student, _student_for_read, require_api_key
from api.schemas import HistoryItem, SessionCreateRequest, SessionOut
from db.models import Message as MessageModel
from db.models import Session as SessionModel
from db.session import delete_messages, get_session

router = APIRouter()


@router.post(
    "/sessions",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def create_session(
    request: SessionCreateRequest, user: UserOut | None = DataUser
) -> dict[str, Any]:
    """Open a new conversation thread for a student.

    The student is ensured to exist (and linked to the caller when
    authenticated). Returns 201 with the new thread's id, title and creation
    time. This route is additive: the existing flat ``/history`` keeps working
    and threads are entirely opt-in.
    """
    with get_session(api_main._engine) as session:
        student = _resolve_student(session, request.student_id, user)
        thread = SessionModel(student_id=student.id, title=request.title)
        session.add(thread)
        session.flush()
        return {
            "id": thread.id,
            "title": thread.title,
            "created_at": _iso_utc(thread.created_at),
        }


@router.get(
    "/sessions/{student_id}",
    response_model=list[SessionOut],
    dependencies=[Depends(require_api_key)],
)
def list_sessions(student_id: str, user: UserOut | None = DataUser) -> list[dict[str, Any]]:
    """List a student's conversation threads, newest first.

    An unknown student yields an empty list rather than an error. In require_auth
    mode the student must belong to the caller (403 otherwise).
    """
    with get_session(api_main._engine) as session:
        student = _student_for_read(session, student_id, user)
        if student is None:
            return []
        rows = session.scalars(
            select(SessionModel)
            .where(SessionModel.student_id == student.id)
            .order_by(SessionModel.created_at.desc(), SessionModel.id.desc())
        )
        return [
            {
                "id": row.id,
                "title": row.title,
                "created_at": _iso_utc(row.created_at),
            }
            for row in rows
        ]


@router.get(
    "/sessions/{student_id}/{session_id}/messages",
    response_model=list[HistoryItem],
    dependencies=[Depends(require_api_key)],
)
def session_messages(
    student_id: str, session_id: int, user: UserOut | None = DataUser
) -> list[dict[str, Any]]:
    """Return the messages of one thread in chronological order.

    Yields 404 when the thread does not exist or does not belong to the student,
    so a caller can never read another student's thread. In require_auth mode the
    student must belong to the caller (403 otherwise).
    """
    with get_session(api_main._engine) as session:
        student = _student_for_read(session, student_id, user)
        thread = None
        if student is not None:
            thread = session.scalar(
                select(SessionModel).where(
                    SessionModel.id == session_id, SessionModel.student_id == student.id
                )
            )
        if thread is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found for this student.",
            )
        rows = session.scalars(
            select(MessageModel)
            .where(MessageModel.session_id == thread.id)
            .order_by(MessageModel.created_at.asc(), MessageModel.id.asc())
        )
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
    "/sessions/{student_id}/{session_id}",
    dependencies=[Depends(require_api_key)],
)
def delete_session_route(
    student_id: str, session_id: int, user: UserOut | None = DataUser
) -> dict[str, bool]:
    """Delete a conversation thread together with its messages.

    The thread's messages are removed as well, so deleting a thread clears that
    conversation rather than leaving orphaned turns in the flat history. Yields
    404 when the thread does not exist or is not owned by the student. In
    require_auth mode the student must belong to the caller (403 otherwise).
    """
    with get_session(api_main._engine) as session:
        student = _student_for_read(session, student_id, user)
        thread = None
        if student is not None:
            thread = session.scalar(
                select(SessionModel).where(
                    SessionModel.id == session_id, SessionModel.student_id == student.id
                )
            )
        if thread is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found for this student.",
            )
        # Delete the thread's messages, then the thread row itself.
        delete_messages(session, thread.student_id, session_id=thread.id)
        session.delete(thread)
    return {"deleted": True}
