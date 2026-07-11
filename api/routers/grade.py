"""Grading route: score a student's free-form answer with the judge node."""

from typing import Any

from fastapi import APIRouter, Depends

import api.main as api_main
from agent.state import TutorState
from api.auth import UserOut
from api.deps import DataUser, OpenAIKey, _resolve_student, require_api_key
from api.schemas import GradeRequest, GradeResponse
from core.errors import raise_friendly_llm_error
from db.session import get_session

router = APIRouter()


@router.post("/grade", response_model=GradeResponse, dependencies=[Depends(require_api_key)])
def grade_answer(
    request: GradeRequest,
    user: UserOut | None = DataUser,
    openai_key: str | None = OpenAIKey,
) -> dict[str, Any]:
    """Grade the student's answer, optionally against a prior exercise.

    The student is ensured to exist (and linked to the caller when
    authenticated); grade persistence is owned by the agent node, which needs the
    ``student_id`` (and the exercise's id) to link the grade to its exercise.
    """
    with get_session(api_main._engine) as session:
        _resolve_student(session, request.student_id, user)
    state: TutorState = {
        "message": request.message,
        "student_id": request.student_id,
        "rigor": request.rigor,
        "api_key": openai_key,
    }
    if request.exercise is not None:
        state["exercise"] = request.exercise
    try:
        verdict = api_main.grade(state).get("grade")
    except Exception as exc:
        raise_friendly_llm_error(exc, used_own_key=bool(openai_key))
        raise
    # grade always populates "grade" with the judge's verdict.
    assert verdict is not None
    return {"score": verdict["score"], "feedback": verdict["feedback"]}
