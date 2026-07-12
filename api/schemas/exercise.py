"""Exercise request-response and after-the-fact review models."""

from pydantic import BaseModel


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
