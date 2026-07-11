"""Shared FastAPI dependencies and helpers for the tutor routes.

These are the cross-cutting pieces every domain router reuses: the API-key and
data-user guards, the optional per-request OpenAI key, student resolution and
ownership enforcement, thread validation and activity persistence.

Runtime state that tests swap at will — the database engine and the settings
factory — is read through the ``api.main`` module at call time (never bound at
import), so monkeypatching ``api.main._engine`` / ``api.main.get_settings`` keeps
driving these helpers exactly as when they lived in ``api.main`` itself.
"""

import hmac
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select

import api.main as api_main
from api.auth import UserOut, get_current_user, get_optional_user
from db.models import Session as SessionModel
from db.models import Student
from db.session import add_message, get_or_create_student, get_session

STUDENT_FOREIGN = "This student belongs to another account."

# Distinct message roles for the activity feed. ``user``/``assistant`` are the
# Q&A turns written by /ask and /reexplain; these two label exercise and quiz
# activity so the history can style them apart. ``Message.role`` is a plain
# string column (no enum/CHECK), so new values are safe, and ``to_history`` maps
# unknown roles through unchanged — they are never treated as tutor context, so
# reexplain keeps reformulating the last real answer only.
ROLE_EXERCISE = "exercise"
ROLE_QUIZ = "quiz"


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce API-key authentication when one is configured.

    When ``Settings.api_key`` is empty (the default) the API stays fully open and
    this dependency is a no-op, preserving backward compatibility. When a key is
    set, the request must carry a matching ``X-API-Key`` header; otherwise the
    request is rejected with 401. ``/health`` never depends on this guard.
    """
    expected = api_main.get_settings().api_key
    if not expected:
        return
    if not hmac.compare_digest(x_api_key or "", expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )


def get_data_user(authorization: str | None = Header(default=None)) -> UserOut | None:
    """Resolve the caller for data endpoints, honouring ``REQUIRE_AUTH``.

    When ``require_auth`` is on, a valid bearer token is mandatory (401
    otherwise); when off, authentication stays optional (anonymous allowed),
    preserving the MVP behaviour byte-for-byte.
    """
    if api_main.get_settings().require_auth:
        return get_current_user(authorization)
    return get_optional_user(authorization)


# Re-exported so routes can declare the flag-aware data dependency concisely.
DataUser = Depends(get_data_user)


def get_openai_key(x_openai_key: Annotated[str | None, Header()] = None) -> str | None:
    """Resolve a visitor's optional per-request OpenAI key from ``X-OpenAI-Key``.

    The value is trimmed and an empty/whitespace header normalizes to ``None`` so
    it is never forwarded. When present it is threaded into the core/agent LLM
    calls as a per-request key, so the visitor's own premium OpenAI model replaces
    the free default for THIS request only (Ask, re-explain, exercises, quizzes,
    grading, the router and — on upload — PDF extraction). When absent, every call
    stays on the free default model exactly as before.

    SECURITY: the key is used transiently for this one request and is NEVER stored
    server-side, NEVER logged (the request middleware logs neither request headers
    nor bodies), NEVER persisted in a job record, and NEVER returned in any
    response.
    """
    if x_openai_key is None:
        return None
    trimmed = x_openai_key.strip()
    return trimmed or None


# Re-exported so routes can declare the per-request OpenAI-key dependency concisely.
OpenAIKey = Depends(get_openai_key)


def _iso_utc(dt: datetime | None) -> str:
    """Serialize a timestamp as a timezone-aware UTC ISO string.

    SQLite stores ``func.now()`` as a naive UTC value, so a bare ``isoformat()``
    emits no offset and the browser parses it as local time (showing the wrong
    clock). Tagging naive datetimes as UTC lets the frontend convert to the
    user's local timezone; already-aware datetimes (e.g. PostgreSQL, or Python
    ``datetime.now(UTC)``) are left unchanged.
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _resolve_student(session: Any, external_id: str, user: UserOut | None) -> Student:
    """Get-or-create the student and, when authenticated, claim/enforce ownership.

    Anonymous requests (``user is None``, i.e. no bearer token) behave exactly as
    before: the student is keyed solely by ``external_id`` and left unlinked. As
    soon as a valid bearer token is present the caller is isolated to their own
    students: an unowned student is linked to that user, and touching a student
    that belongs to a *different* account is rejected with 403. This holds
    whenever a user is authenticated, independently of ``require_auth`` (that flag
    only additionally *forces* a token via the sign-in gate). This never changes
    the answer, only the ownership link.
    """
    student = get_or_create_student(session, external_id)
    if user is None:
        return student
    if student.user_id is None:
        student.user_id = user.id
        session.flush()
    elif student.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=STUDENT_FOREIGN)
    return student


def _student_for_read(session: Any, external_id: str, user: UserOut | None) -> Student | None:
    """Look up a student by ``external_id`` for a read/scoped route.

    Returns the ``Student`` or ``None``. Whenever a caller is authenticated (a
    bearer token was sent, so ``user`` is not ``None``), a student that exists but
    is not owned by ``user`` is treated as inaccessible: raise 403 (never leak
    another tenant's data). This holds independently of ``require_auth``. A missing
    student still returns ``None`` so callers keep their existing empty/404
    behaviour. For an anonymous caller (``user is None``) this is a plain lookup,
    so the anonymous flow is unchanged.
    """
    student = session.scalar(select(Student).where(Student.external_id == external_id))
    if student is None:
        return None
    if user is not None and student.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=STUDENT_FOREIGN)
    return student


def _scoped_read_owner(external_id: str | None, user: UserOut | None) -> str | None:
    """Return the owner id to scope a read by, enforcing ownership when authenticated.

    ``external_id`` is the request's effective ``student_id`` (``u<id>`` when
    logged in, the device id when anonymous). When ``None`` (a request carrying no
    identity) this returns ``None``, and the core read layer treats a ``None``
    owner as **fail-closed** (empty result), never as "read everything". Otherwise,
    when the caller is authenticated, a student that belongs to a *different*
    account is rejected with 403 (via :func:`_student_for_read`), so one account
    can never read another's material by passing its id. The owner string is
    returned unchanged so the core layer scopes retrieval/listing strictly to the
    caller's own material.
    """
    if external_id is None:
        return None
    with get_session(api_main._engine) as session:
        _student_for_read(session, external_id, user)
    return external_id


def _resolve_session_id(session: Any, student_id: int, session_id: int | None) -> int | None:
    """Validate that ``session_id`` is a thread owned by ``student_id``.

    Returns the id unchanged when it names one of the student's threads. When it
    is ``None`` (the default), the turn stays unthreaded. A stale or unknown id
    (for example a thread id persisted in the browser after a database reset, or
    one belonging to another student) is treated as "no thread" — it returns
    ``None`` rather than failing the request, since the query already filters by
    ``student_id`` so the message can never be mis-attached.
    """
    if session_id is None:
        return None
    thread = session.scalar(
        select(SessionModel).where(
            SessionModel.id == session_id, SessionModel.student_id == student_id
        )
    )
    return session_id if thread is not None else None


def _record_activity(
    external_id: str,
    user: UserOut | None,
    session_id: int | None,
    *,
    role: str,
    content: str,
    ref_id: int | None = None,
) -> None:
    """Persist one activity item (exercise/quiz) as a message, like /ask does.

    The student is resolved (and ownership enforced) exactly as for a question,
    and the item is attached to the active thread when ``session_id`` names one
    of the student's threads. Kept concise on purpose: callers pass a short
    summary, never a full JSON blob. ``ref_id`` links the turn back to the
    persisted exercise/quiz so the history can fetch the full item for review.
    """
    with get_session(api_main._engine) as session:
        student = _resolve_student(session, external_id, user)
        thread_id = _resolve_session_id(session, student.id, session_id)
        add_message(
            session,
            student_id=student.id,
            role=role,
            content=content,
            session_id=thread_id,
            ref_id=ref_id,
        )
