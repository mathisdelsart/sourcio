"""Grade request-response models."""

from typing import Any

from pydantic import BaseModel

from agent.state import Rigor


class GradeRequest(BaseModel):
    """A student's answer to grade, optionally against a prior exercise.

    ``rigor`` sets the marking strictness; an unsupported value is rejected with
    422 by the ``Rigor`` literal, matching how ``ReexplainRequest.level`` is
    validated.
    """

    student_id: str
    message: str
    exercise: dict[str, Any] | None = None
    rigor: Rigor = "standard"


class GradeResponse(BaseModel):
    """The judge's verdict on the student's answer."""

    score: int
    feedback: str
