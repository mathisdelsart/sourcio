"""Spaced-repetition (SM-2) review request-response models."""

from pydantic import BaseModel, Field, field_validator

from core.scheduling import MAX_QUALITY, MIN_QUALITY


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
