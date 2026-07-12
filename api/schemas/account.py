"""Session (thread), student identity, and feedback models."""

from pydantic import BaseModel, Field, field_validator


class SessionCreateRequest(BaseModel):
    """A request to open a new conversation thread for a student."""

    student_id: str
    title: str | None = None


class SessionOut(BaseModel):
    """A conversation thread owned by a student."""

    id: int
    title: str | None
    created_at: str


class StudentOut(BaseModel):
    """A student identity owned by the authenticated caller."""

    id: int
    external_id: str
    created_at: str


class FeedbackRequest(BaseModel):
    """A student's thumbs up/down on a tutor answer.

    ``rating`` is ``1`` for thumbs up and ``-1`` for thumbs down (validated). The
    question and answer text are stored verbatim so the feedback is
    self-contained for later evaluation. ``note`` is optional (e.g. why the
    answer was unhelpful).
    """

    student_id: str
    rating: int = Field(description="1 for thumbs up, -1 for thumbs down.")
    question: str
    answer: str
    note: str | None = None

    @field_validator("rating")
    @classmethod
    def _rating_in_range(cls, value: int) -> int:
        """Reject any rating other than the two allowed values."""
        if value not in (1, -1):
            raise ValueError("rating must be 1 (up) or -1 (down).")
        return value


class FeedbackResponse(BaseModel):
    """The id of the persisted feedback row."""

    id: int


class FeedbackSummary(BaseModel):
    """Aggregate thumbs up/down counts for a student."""

    up: int
    down: int
