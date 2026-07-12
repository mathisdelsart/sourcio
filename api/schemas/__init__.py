"""Pydantic request/response models for the tutor API, split by domain.

Pure data schemas (no behavior beyond field validation) shared by the route
modules in ``api.routers``. The models live in per-domain modules alongside the
routers; this package re-exports every model so ``from api.schemas import X``
keeps working unchanged.
"""

from api.schemas.account import (
    FeedbackRequest,
    FeedbackResponse,
    FeedbackSummary,
    SessionCreateRequest,
    SessionOut,
    StudentOut,
)
from api.schemas.ask import (
    AskRequest,
    AskResponse,
    Citation,
    HistoryItem,
    ReexplainRequest,
    ReexplainResponse,
)
from api.schemas.documents import (
    ChaptersResponse,
    CoursesResponse,
    DocumentChapter,
    DocumentCourse,
    DocumentDeleteResponse,
    DocumentRenameRequest,
    DocumentRenameResponse,
    SourceResponse,
)
from api.schemas.exercise import (
    ExerciseGradeReview,
    ExerciseRequest,
    ExerciseResponse,
    ExerciseReviewResponse,
)
from api.schemas.grade import GradeRequest, GradeResponse
from api.schemas.quiz import (
    QuizGradeAllItem,
    QuizGradeAllRequest,
    QuizGradeRequest,
    QuizGradeResult,
    QuizQuestionOut,
    QuizQuestionReview,
    QuizRequest,
    QuizResponse,
    QuizReviewResponse,
    QuizSummaryResponse,
)
from api.schemas.reviews import EnqueueReviewRequest, ReviewRequest, ReviewSchedule

__all__ = [
    "AskRequest",
    "AskResponse",
    "ChaptersResponse",
    "Citation",
    "CoursesResponse",
    "DocumentChapter",
    "DocumentCourse",
    "DocumentDeleteResponse",
    "DocumentRenameRequest",
    "DocumentRenameResponse",
    "EnqueueReviewRequest",
    "ExerciseGradeReview",
    "ExerciseRequest",
    "ExerciseResponse",
    "ExerciseReviewResponse",
    "FeedbackRequest",
    "FeedbackResponse",
    "FeedbackSummary",
    "GradeRequest",
    "GradeResponse",
    "HistoryItem",
    "QuizGradeAllItem",
    "QuizGradeAllRequest",
    "QuizGradeRequest",
    "QuizGradeResult",
    "QuizQuestionOut",
    "QuizQuestionReview",
    "QuizRequest",
    "QuizResponse",
    "QuizReviewResponse",
    "QuizSummaryResponse",
    "ReexplainRequest",
    "ReexplainResponse",
    "ReviewRequest",
    "ReviewSchedule",
    "SessionCreateRequest",
    "SessionOut",
    "SourceResponse",
    "StudentOut",
]
