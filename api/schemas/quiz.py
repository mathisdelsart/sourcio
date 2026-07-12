"""Quiz request-response, whole-quiz grading, and review models."""

from pydantic import BaseModel, Field

from agent.state import Rigor


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
