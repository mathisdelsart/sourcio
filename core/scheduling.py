"""Pure spaced-repetition scheduling math (SM-2).

This module holds the SM-2 algorithm and nothing else: no database, no clock, no
network. Given the current schedule of a notion and how well the student just
recalled it (a ``quality`` rating from 0 to 5), it returns the next schedule
(ease factor, repetition count, interval in days). The caller is responsible for
turning the returned interval into a concrete due date from its own notion of
"now", which keeps this function deterministic and trivially unit-testable.

Reference: SuperMemo SM-2. A recall of ``quality < 3`` is treated as a lapse and
resets the repetition streak and interval, while the ease factor still relaxes
toward its ``1.3`` floor. A successful recall (``quality >= 3``) grows the
interval and nudges the ease factor up or down based on the rating.
"""

from __future__ import annotations

from dataclasses import dataclass

# The ease factor is never allowed below this floor (standard SM-2 value); a
# lower factor would make intervals collapse and review the notion forever.
MIN_EASE = 1.3

# Quality ratings at or above this threshold count as a successful recall.
PASS_QUALITY = 3

# Inclusive bounds for a valid quality rating.
MIN_QUALITY = 0
MAX_QUALITY = 5


@dataclass(frozen=True)
class ReviewState:
    """The schedule of a notion after applying one recall rating.

    Attributes:
        ease: The SM-2 ease factor, floored at :data:`MIN_EASE`.
        interval_days: Days until the notion should next be reviewed.
        repetitions: The current streak of successful recalls.
    """

    ease: float
    interval_days: int
    repetitions: int


def schedule(ease: float, interval_days: int, repetitions: int, quality: int) -> ReviewState:
    """Apply one SM-2 step and return the next review state.

    Args:
        ease: The current ease factor (e.g. ``2.5`` for a fresh notion).
        interval_days: The current interval in days (``0`` for a fresh notion).
        repetitions: The current count of consecutive successful recalls.
        quality: How well the notion was just recalled, an integer in ``0..5``.

    Returns:
        A :class:`ReviewState` with the updated ease, interval and repetition
        count. The caller derives the due date from the interval and its own
        clock.

    Raises:
        ValueError: If ``quality`` is outside ``0..5``.
    """
    if not (MIN_QUALITY <= quality <= MAX_QUALITY):
        raise ValueError(f"quality must be in {MIN_QUALITY}..{MAX_QUALITY}, got {quality}.")

    # Update the ease factor with the standard SM-2 formula, then floor it. A low
    # quality lowers the ease; a perfect recall raises it.
    new_ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ease = max(MIN_EASE, new_ease)

    if quality < PASS_QUALITY:
        # Lapse: restart the streak and schedule a fresh short interval.
        return ReviewState(ease=new_ease, interval_days=1, repetitions=0)

    new_repetitions = repetitions + 1
    if new_repetitions == 1:
        new_interval = 1
    elif new_repetitions == 2:
        new_interval = 6
    else:
        new_interval = round(interval_days * new_ease)

    return ReviewState(ease=new_ease, interval_days=new_interval, repetitions=new_repetitions)
