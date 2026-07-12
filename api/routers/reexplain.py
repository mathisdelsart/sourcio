"""Re-explanation routes: rephrase the last tutor answer, plain or streamed."""

import json
import logging
from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select

import api.main as api_main
from agent.state import TutorState, to_history
from api.auth import UserOut
from api.deps import DataUser, OpenAIKey, _student_for_read, require_api_key
from api.schemas import ReexplainRequest, ReexplainResponse
from core.errors import friendly_llm_error_message, raise_friendly_llm_error
from db.models import Student
from db.session import add_message, get_session, recent_messages

logger = logging.getLogger("api")

router = APIRouter()

NOTHING_TO_REEXPLAIN = "There is no previous answer to re-explain yet. Ask a question first."


def _last_tutor_answer(history: list[dict[str, str]]) -> str | None:
    """Return the most recent tutor turn's content, or None when there is none."""
    for turn in reversed(history):
        if turn.get("role") == "tutor" and turn.get("content"):
            return turn["content"]
    return None


@router.post(
    "/reexplain", response_model=ReexplainResponse, dependencies=[Depends(require_api_key)]
)
def reexplain_answer(
    request: ReexplainRequest,
    user: UserOut | None = DataUser,
    openai_key: str | None = OpenAIKey,
) -> dict[str, str]:
    """Rephrase the student's last tutor answer at the requested level.

    The recent conversation is rebuilt from the database and handed to the
    ``reexplain`` node, which reformulates the last grounded explanation without
    running retrieval again. The new explanation is persisted as an assistant
    turn so the conversation stays continuous. When the student has no prior
    answer, a friendly note is returned instead of crashing. In require_auth mode
    the student must belong to the caller (403 otherwise).
    """
    with get_session(api_main._engine) as session:
        student = _student_for_read(session, request.student_id, user)
        if student is None:
            return {"answer": NOTHING_TO_REEXPLAIN}
        history = to_history(recent_messages(session, student.id))
        if _last_tutor_answer(history) is None:
            return {"answer": NOTHING_TO_REEXPLAIN}
        state: TutorState = {
            "student_id": request.student_id,
            "message": "Please re-explain that.",
            "level": request.level,
            "history": history,
            "api_key": openai_key,
        }
        try:
            rephrased = api_main.reexplain(state).get("answer", "")
        except Exception as exc:
            raise_friendly_llm_error(exc, used_own_key=bool(openai_key))
            raise
        add_message(session, student_id=student.id, role="assistant", content=rephrased)
    return {"answer": rephrased}


def _reexplain_state(request: ReexplainRequest, openai_key: str | None = None) -> TutorState | None:
    """Rebuild the re-explain state from stored history, or None when there is none.

    Returns None when the student is unknown or has no prior tutor answer, so the
    caller can surface the friendly ``NOTHING_TO_REEXPLAIN`` note instead of
    calling the model. ``openai_key`` (the visitor's own OpenAI key, when
    supplied) is threaded onto the state so the re-explanation runs on their own
    OpenAI model; it is transient and never persisted.
    """
    with get_session(api_main._engine) as session:
        student = session.scalar(select(Student).where(Student.external_id == request.student_id))
        if student is None:
            return None
        history = to_history(recent_messages(session, student.id))
        if _last_tutor_answer(history) is None:
            return None
        return {
            "student_id": request.student_id,
            "message": "Please re-explain that.",
            "level": request.level,
            "history": history,
            "api_key": openai_key,
        }


def _stream_reexplain_events(
    request: ReexplainRequest, openai_key: str | None = None
) -> Iterator[str]:
    """Serialize ``stream_reexplain`` as Server-Sent Events and persist on completion.

    Mirrors ``/ask/stream`` but token-only: no retrieval, so no "retrieving"
    stage and no sources event. When there is nothing to re-explain, the friendly
    note is emitted as a single token then a ``done`` event. Otherwise token
    deltas stream, then a final ``{"type": "done", "answer": ...}`` event, and the
    assembled re-explanation is persisted as an assistant turn.
    """
    state = _reexplain_state(request, openai_key)
    if state is None:
        yield f"data: {json.dumps({'type': 'token', 'text': NOTHING_TO_REEXPLAIN})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'answer': NOTHING_TO_REEXPLAIN})}\n\n"
        return

    final_answer = ""
    try:
        for event in api_main.stream_reexplain(state):
            if event.get("type") == "done":
                final_answer = event.get("answer", "")
            yield f"data: {json.dumps(event)}\n\n"
    except Exception as exc:
        logger.exception("Error while streaming /reexplain/stream")
        message = friendly_llm_error_message(exc, used_own_key=bool(openai_key))
        yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"
        return

    with get_session(api_main._engine) as session:
        student = session.scalar(select(Student).where(Student.external_id == request.student_id))
        if student is not None:
            add_message(session, student_id=student.id, role="assistant", content=final_answer)


@router.post("/reexplain/stream", dependencies=[Depends(require_api_key)])
def reexplain_stream(
    request: ReexplainRequest, openai_key: str | None = OpenAIKey
) -> StreamingResponse:
    """Stream a re-explanation of the last tutor answer as Server-Sent Events.

    Mirrors ``/reexplain`` (same request model, auth and history persistence) but
    returns a ``text/event-stream`` response so the re-explanation types out.
    ``/reexplain`` stays available for non-streaming clients.
    """
    return StreamingResponse(
        _stream_reexplain_events(request, openai_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
