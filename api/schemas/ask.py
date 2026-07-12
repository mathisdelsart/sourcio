"""Ask / re-explain / history request-response models."""

from pydantic import BaseModel, Field

from agent.state import Level


class AskRequest(BaseModel):
    """A question to answer from the course, on behalf of a student.

    ``course`` and ``chapter`` optionally restrict retrieval to a single course
    (and chapter). Both default to ``None`` so existing callers keep searching
    the whole collection unchanged.
    """

    student_id: str
    question: str
    k: int = Field(default=5, ge=1)
    course: str | None = None
    chapter: str | None = None
    session_id: int | None = None
    # Optional locale code ('en'/'fr'/'nl') to force the default answer language;
    # None keeps the model answering in the question's own language.
    language: str | None = None


class Citation(BaseModel):
    """A cited source: its inline marker number, chunk id (to fetch its excerpt)
    and label.

    ``n`` is the 1-based index exactly as written inline in the answer (``[n]``),
    so a UI can render a numbered legend matching the markers.
    """

    n: int
    id: str
    label: str


class AskResponse(BaseModel):
    """A grounded answer, refused when the course does not cover the question."""

    answer: str
    refused: bool
    sources: list[str]
    # Structured citations carry the chunk id so a UI can open the exact source
    # excerpt via GET /source/{id}; `sources` keeps the plain labels.
    citations: list[Citation] = []


class ReexplainRequest(BaseModel):
    """A request to rephrase the student's last tutor answer at a given level."""

    student_id: str
    level: Level = "beginner"


class ReexplainResponse(BaseModel):
    """The rephrased explanation (or a friendly note when nothing to re-explain)."""

    answer: str


class HistoryItem(BaseModel):
    """A single persisted conversation turn.

    ``ref_id`` links an activity turn (exercise/quiz) back to its domain object
    so the UI can fetch the full item for review; it is ``None`` for plain Q&A
    turns.
    """

    role: str
    content: str
    created_at: str
    ref_id: int | None = None
