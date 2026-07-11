"""Pydantic request/response models for the tutor API.

These are pure data schemas shared by the route modules in ``api.routers``.
They contain no behavior beyond field validation, so they can be imported
without pulling in the FastAPI app or its dependencies.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from agent.state import Level, Rigor
from core.scheduling import MAX_QUALITY, MIN_QUALITY


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


class ExerciseRequest(BaseModel):
    """A free-form exercise request for a student.

    ``notion`` is the request itself (any exercise, in free form). ``course`` and
    ``chapter`` optionally scope retrieval so the exercise stays on the requested
    material; when both are None the whole collection is searched.
    """

    student_id: str
    notion: str
    course: str | None = None
    chapter: str | None = None
    # Optional locale code ('en'/'fr'/'nl') to force the exercise's language;
    # None keeps the model writing in the request's own language.
    language: str | None = None
    # Optional thread to attach the resulting activity item to, like /ask. When
    # None (or not owned by the student) the item stays in the flat history.
    session_id: int | None = None


class ExerciseResponse(BaseModel):
    """A course-grounded exercise. The reference solution is withheld."""

    problem: str
    refused: bool
    id: int | None = None


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


class QuizRequest(BaseModel):
    """A free-form quiz request for a student.

    ``notion`` is the request itself (any quiz, in free form). ``n`` is the
    desired number of questions; it is clamped to a small range so a request can
    never ask for an unbounded quiz. ``course`` and ``chapter`` optionally scope
    retrieval so the quiz stays on the requested material; when both are None the
    whole collection is searched.
    """

    student_id: str
    notion: str
    n: int = Field(default=3, ge=1, le=10)
    course: str | None = None
    chapter: str | None = None
    # Optional locale code ('en'/'fr'/'nl') to force the quiz's language; None
    # keeps the model writing in the request's own language.
    language: str | None = None
    # Optional thread to attach the resulting activity item to, like /ask. When
    # None (or not owned by the student) the item stays in the flat history.
    session_id: int | None = None


class QuizQuestionOut(BaseModel):
    """One quiz question, problem only. The reference solution is withheld."""

    id: int | None = None
    problem: str


class QuizResponse(BaseModel):
    """A course-grounded quiz. Reference solutions are never returned."""

    quiz_id: int | None = None
    notion: str
    questions: list[QuizQuestionOut]
    refused: bool


class QuizGradeRequest(BaseModel):
    """A student's answer to one quiz question, graded against its reference.

    ``rigor`` sets the marking strictness applied by the shared grade judge; an
    unsupported value is rejected with 422 by the ``Rigor`` literal, matching how
    ``GradeRequest.rigor`` is validated.
    """

    student_id: str
    question_id: int
    answer: str
    rigor: Rigor = "standard"


class QuizGradeAllItem(BaseModel):
    """One question's answer in a whole-quiz grading request."""

    question_id: int
    answer: str


class QuizGradeAllRequest(BaseModel):
    """All of a student's quiz answers, graded together for a final score.

    ``rigor`` sets the marking strictness applied to every answer; an unsupported
    value is rejected with 422 by the ``Rigor`` literal, matching ``GradeRequest``.
    """

    student_id: str
    answers: list[QuizGradeAllItem]
    rigor: Rigor = "standard"


class QuizGradeResult(BaseModel):
    """One question's verdict in a whole-quiz summary."""

    question_id: int
    score: int
    feedback: str


class QuizSummaryResponse(BaseModel):
    """A whole-quiz verdict: a final score and a personalized recommendation."""

    total: int
    results: list[QuizGradeResult]
    recommendation: str


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


class CoursesResponse(BaseModel):
    """The distinct courses currently indexed in Qdrant, sorted."""

    courses: list[str]


class ChaptersResponse(BaseModel):
    """The distinct chapters of one course currently indexed in Qdrant, sorted."""

    chapters: list[str]


class DocumentChapter(BaseModel):
    """One chapter of a course and how many distinct pages it carries.

    ``chapter`` is ``None`` for material indexed without one (a UI groups it as
    "Uncategorized").
    """

    chapter: str | None = None
    pages: int


class DocumentCourse(BaseModel):
    """A course's indexed inventory: its chapters, page count and stored files."""

    course: str
    total_pages: int
    chapters: list[DocumentChapter]
    # Names of original uploaded files kept for this course (viewable via
    # GET /documents/file). Empty for material indexed outside the upload UI.
    files: list[str] = []


class DocumentDeleteResponse(BaseModel):
    """How many indexed points were removed by a delete request."""

    deleted: int


class DocumentRenameRequest(BaseModel):
    """Rename a course and/or a chapter of the caller's indexed material.

    ``student_id`` scopes the rename to the caller's own points (required — a
    rename is a per-account write). ``course`` names the course to act on. Set
    ``new_course`` to rename that course; set both ``chapter`` and ``new_chapter``
    to rename a chapter within the course. At least one of the two renames must be
    requested.
    """

    student_id: str
    course: str
    new_course: str | None = None
    chapter: str | None = None
    new_chapter: str | None = None


class DocumentRenameResponse(BaseModel):
    """How many indexed points a rename updated, split by field."""

    course_updated: int = 0
    chapter_updated: int = 0


class SourceResponse(BaseModel):
    """A cited source chunk: its full text and citation metadata.

    Lets a UI turn a citation into a readable excerpt. ``chapter`` may be absent
    for material indexed without a chapter, so it is optional.
    """

    id: str
    course: str
    chapter: str | None = None
    page: int
    text: str


class ExerciseGradeReview(BaseModel):
    """The graded verdict on an exercise, surfaced for after-the-fact review."""

    answer: str
    score: float
    feedback: str
    created_at: str


class ExerciseReviewResponse(BaseModel):
    """A generated exercise reviewed after the fact.

    The reference solution IS returned here (unlike ``/exercise``): review is
    after-the-fact, so the student is meant to see the model answer. ``grade`` is
    the latest verdict on the exercise, or ``None`` if it was never graded.
    """

    problem: str
    reference_solution: str
    grade: ExerciseGradeReview | None = None


class QuizQuestionReview(BaseModel):
    """One quiz question reviewed after the fact, with its reference solution.

    ``answer``/``score``/``feedback`` come from the latest grade on the question
    and are ``None`` when it was never answered.
    """

    position: int
    problem: str
    reference_solution: str
    answer: str | None = None
    score: float | None = None
    feedback: str | None = None


class QuizReviewResponse(BaseModel):
    """A generated quiz reviewed after the fact.

    Reference solutions ARE returned (unlike ``/quiz``): review is after-the-fact.
    Questions are ordered by position.
    """

    notion: str
    questions: list[QuizQuestionReview]


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


class ReviewRequest(BaseModel):
    """A recall rating for one notion, driving its spaced-repetition schedule.

    ``quality`` is how well the student just recalled the notion, an integer in
    ``0..5`` (SM-2): ratings below ``3`` are lapses that reset the streak. The
    bound is validated, so an out-of-range value is rejected with 422.
    """

    student_id: str
    notion: str
    quality: int = Field(description="Recall quality in 0..5 (>=3 passes).")

    @field_validator("quality")
    @classmethod
    def _quality_in_range(cls, value: int) -> int:
        """Reject a recall quality outside the SM-2 ``0..5`` range."""
        if not (MIN_QUALITY <= value <= MAX_QUALITY):
            raise ValueError(f"quality must be in {MIN_QUALITY}..{MAX_QUALITY}.")
        return value


class EnqueueReviewRequest(BaseModel):
    """A request to add a notion to the spaced-repetition queue, due immediately.

    Unlike :class:`ReviewRequest` this carries no recall rating: the notion is
    seeded at the SM-2 defaults with ``due_at`` set to "now" so it surfaces in
    the due queue straight away, ready for its first rating.
    """

    student_id: str
    notion: str


class ReviewSchedule(BaseModel):
    """The spaced-repetition schedule of a notion after a recall."""

    notion: str
    ease: float
    interval_days: int
    due_at: str
