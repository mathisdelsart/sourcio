"""Question-answering routes: synchronous, streamed (SSE) and background job.

Every path delegates to the grounded ``answer``/``stream_answer`` functions and
persists the resulting turn as conversation history. The grounded functions are
resolved through ``api.main`` at call time so tests can swap them in place.
"""

import json
import logging
import threading
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

import api.main as api_main
from api.auth import UserOut
from api.deps import (
    DataUser,
    OpenAIKey,
    _resolve_session_id,
    _resolve_student,
    _scoped_read_owner,
    require_api_key,
)
from api.schemas import AskRequest, AskResponse
from core.errors import friendly_llm_error_message, raise_friendly_llm_error
from core.jobs import create_answer_job, get_answer_job, update_job
from db.session import add_message, get_session

logger = logging.getLogger("api")

router = APIRouter()

REFUSAL_FALLBACK = "This is not covered in the course material."


@router.post("/ask", response_model=AskResponse, dependencies=[Depends(require_api_key)])
def ask(
    request: AskRequest,
    user: UserOut | None = DataUser,
    openai_key: str | None = OpenAIKey,
) -> dict[str, Any]:
    """Answer a question grounded in the course, or refuse if uncovered.

    The question and the assistant's answer are persisted as conversation
    history for the student. When the request carries a valid bearer token, the
    student is linked to that account so the turns become the user's own. When an
    ``X-OpenAI-Key`` header is present the answer runs on the visitor's own OpenAI
    model instead of the free default (the key is used transiently, never stored).
    """
    # Resolve (and, when authenticated, enforce ownership of) the student up
    # front so a foreign student id is rejected with 403 *before* any retrieval
    # or LLM work runs, mirroring ``/ask/stream``. The block below re-resolves to
    # persist the turn; by then the student is owned, so that call is a no-op.
    with get_session(api_main._engine) as session:
        _resolve_student(session, request.student_id, user)
    try:
        result = api_main.answer(
            request.question,
            k=request.k,
            course=request.course,
            chapter=request.chapter,
            owner=request.student_id,
            language=request.language,
            api_key=openai_key,
        )
    except Exception as exc:
        raise_friendly_llm_error(exc, used_own_key=bool(openai_key))
        raise
    with get_session(api_main._engine) as session:
        student = _resolve_student(session, request.student_id, user)
        thread_id = _resolve_session_id(session, student.id, request.session_id)
        add_message(
            session,
            student_id=student.id,
            role="user",
            content=request.question,
            session_id=thread_id,
        )
        add_message(
            session,
            student_id=student.id,
            role="assistant",
            content=result["answer"],
            session_id=thread_id,
        )
    return {
        "answer": result["answer"],
        "refused": result["refused"],
        "sources": result["sources"],
        "citations": result.get("citations", []),
    }


def _stream_ask_events(
    request: AskRequest, user: UserOut | None = None, openai_key: str | None = None
) -> Iterator[str]:
    """Serialize ``stream_answer`` as Server-Sent Events and persist on completion.

    Each item from the generator is emitted as one SSE ``data:`` line carrying a
    JSON object: ``{"type": "token", "text": ...}`` for each delta, then a final
    ``{"type": "sources", "sources": [...], "refused": ...}`` event. Once the
    stream ends, the question and the fully assembled assistant answer are
    persisted as conversation history, exactly like ``/ask``. ``openai_key`` (the
    visitor's own OpenAI key, when supplied) is used transiently for this answer
    and never stored or logged.
    """
    final_answer = REFUSAL_FALLBACK
    try:
        for event in api_main.stream_answer(
            request.question,
            k=request.k,
            course=request.course,
            chapter=request.chapter,
            owner=request.student_id,
            language=request.language,
            api_key=openai_key,
        ):
            if event.get("type") == "sources":
                final_answer = event.get("answer", final_answer)
                payload = {
                    "type": "sources",
                    "sources": event.get("sources", []),
                    "citations": event.get("citations", []),
                    "refused": event.get("refused", False),
                    # Forward the cleaned final answer so the client can replace the
                    # raw token buffer (which may still show a trailing refusal the
                    # model wrongly appended) with the server-cleaned text.
                    "answer": final_answer,
                }
                yield f"data: {json.dumps(payload)}\n\n"
            else:
                yield f"data: {json.dumps(event)}\n\n"
    except Exception as exc:
        logger.exception("Error while streaming /ask/stream")
        message = friendly_llm_error_message(exc, used_own_key=bool(openai_key))
        yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"
        return

    with get_session(api_main._engine) as session:
        student = _resolve_student(session, request.student_id, user)
        thread_id = _resolve_session_id(session, student.id, request.session_id)
        add_message(
            session,
            student_id=student.id,
            role="user",
            content=request.question,
            session_id=thread_id,
        )
        add_message(
            session,
            student_id=student.id,
            role="assistant",
            content=final_answer,
            session_id=thread_id,
        )


@router.post("/ask/stream", dependencies=[Depends(require_api_key)])
def ask_stream(
    request: AskRequest,
    user: UserOut | None = DataUser,
    openai_key: str | None = OpenAIKey,
) -> StreamingResponse:
    """Stream a grounded answer token by token as Server-Sent Events.

    Mirrors ``/ask`` (same request model, auth and history persistence, and
    optional ownership linking) but returns a ``text/event-stream`` response:
    token deltas arrive first, then a final sources/refusal event. ``/ask`` stays
    available for non-streaming clients.
    """
    # Resolve (and, in require_auth mode, enforce ownership of) the student up
    # front so a foreign student is rejected with 403 *before* any bytes stream,
    # rather than after the answer has already been emitted. The generator
    # re-resolves at the end to persist the turn; by then the student is owned,
    # so that call is a no-op link.
    with get_session(api_main._engine) as session:
        _resolve_student(session, request.student_id, user)
    return StreamingResponse(
        _stream_ask_events(request, user, openai_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _run_answer_job(
    job_id: str, request: AskRequest, user: UserOut | None, openai_key: str | None = None
) -> None:
    """Drive ``stream_answer`` on a daemon thread, mirroring state into the job.

    Each token grows the job's partial ``answer`` (so a client that reconnects
    sees what has been produced so far, still growing); each stage event updates
    ``stage``; the final event stores the cleaned ``answer``, ``refused`` flag,
    ``sources`` and ``citations``. The turn is persisted as conversation history
    on completion, exactly like ``_stream_ask_events``. A failure marks the job
    ``error`` (and does not persist a partial turn). ``openai_key`` (the visitor's
    own OpenAI key, when supplied) authenticates the answer's LLM for this run
    only — it is passed to the answer generator and is NEVER written into the job
    record.
    """
    parts: list[str] = []
    final_answer = REFUSAL_FALLBACK
    refused = False
    sources: list[str] = []
    citations: list[dict[str, Any]] = []
    try:
        for event in api_main.stream_answer(
            request.question,
            k=request.k,
            course=request.course,
            chapter=request.chapter,
            owner=request.student_id,
            language=request.language,
            api_key=openai_key,
        ):
            etype = event.get("type")
            if etype == "token":
                parts.append(event.get("text", ""))
                # Once tokens flow the model is "writing"; expose the growing text.
                update_job(job_id, {"stage": "writing", "answer": "".join(parts)})
            elif etype == "stage":
                patch: dict[str, Any] = {"stage": event.get("stage", "retrieving")}
                if isinstance(event.get("sources"), int):
                    patch["source_count"] = event["sources"]
                update_job(job_id, patch)
            elif etype == "sources":
                final_answer = event.get("answer", final_answer)
                refused = bool(event.get("refused", False))
                sources = event.get("sources", [])
                citations = event.get("citations", [])

        with get_session(api_main._engine) as session:
            student = _resolve_student(session, request.student_id, user)
            thread_id = _resolve_session_id(session, student.id, request.session_id)
            add_message(
                session,
                student_id=student.id,
                role="user",
                content=request.question,
                session_id=thread_id,
            )
            add_message(
                session,
                student_id=student.id,
                role="assistant",
                content=final_answer,
                session_id=thread_id,
            )
        update_job(
            job_id,
            {
                "status": "done",
                "stage": "writing",
                "answer": final_answer,
                "refused": refused,
                "sources": sources,
                "citations": citations,
            },
        )
    except Exception as exc:  # pragma: no cover - defensive; answer guards itself
        logger.exception("Error while running /ask/async job")
        message = friendly_llm_error_message(exc, used_own_key=bool(openai_key))
        update_job(job_id, {"status": "error", "message": message})


@router.post(
    "/ask/async",
    dependencies=[Depends(require_api_key)],
    status_code=status.HTTP_202_ACCEPTED,
)
def ask_async(
    request: AskRequest,
    user: UserOut | None = DataUser,
    openai_key: str | None = OpenAIKey,
) -> dict[str, str]:
    """Start answering a question as a background job and return its id.

    Mirrors ``/ask`` (same request model, auth, ownership and history persistence)
    but the answer runs on a daemon thread instead of being tied to the request:
    a browser refresh or navigation no longer cancels it. Ownership is resolved up
    front (a foreign student id is rejected with 403 before any work), then
    ``{"job_id": ...}`` is returned immediately (HTTP 202). The client polls
    ``GET /ask/jobs/{job_id}`` to follow — or, after a refresh, re-attach to — the
    running answer. ``/ask`` and ``/ask/stream`` stay available. The job registry
    is in-process — see the multi-worker caveat in ``core.jobs``.
    """
    with get_session(api_main._engine) as session:
        _resolve_student(session, request.student_id, user)
    job_id = create_answer_job(request.student_id, request.question)
    threading.Thread(
        target=_run_answer_job, args=(job_id, request, user, openai_key), daemon=True
    ).start()
    return {"job_id": job_id}


@router.get("/ask/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def ask_job(
    job_id: str,
    student_id: str,
    user: UserOut | None = DataUser,
) -> dict[str, Any]:
    """Return one background answer job's record, or 404 if unknown/foreign.

    ``student_id`` is the owner the job was created for; the caller must present
    it. When authenticated, passing another account's student id is rejected with
    403 (via ``_scoped_read_owner``); otherwise a mismatched owner yields 404, so
    a user can only read their own answer job. The record carries ``status``,
    ``stage``, the partial-or-final ``answer``, ``refused``, ``sources`` and
    ``citations``.
    """
    owner = _scoped_read_owner(student_id, user)
    job = get_answer_job(job_id, owner)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job
