"""Empirical calibration of the retrieval similarity threshold.

The threshold (:attr:`config.Settings.similarity_threshold`) gates retrieval:
below it, the system refuses to answer. Its right value depends on the embedding
model, so it must be calibrated empirically rather than guessed. This tool
measures, for every labeled question, the top retrieval similarity (the score of
the best matching chunk) *without* applying any threshold, then sweeps candidate
thresholds to find the one that best separates in-course from out-of-course
questions.

The scoring of a question is injectable so the pure sweep/metric logic can be
unit tested without loading the embedding model or touching Qdrant. The default
wiring uses the real retrieval stack and is imported lazily, keeping this module
importable in CI without those dependencies.

The dataset convention follows ``eval/run_eval.py``: ``expect_refusal=false``
marks an in-course question (should score high), ``expect_refusal=true`` an
out-of-course question (should score low).
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from eval.run_eval import DATASET_PATH, EvalCase, load_dataset

# A scorer maps a question to its top retrieval similarity (no threshold).
ScoreFn = Callable[[str], float]


@dataclass(frozen=True)
class ClassStats:
    """Summary of a class's score distribution."""

    count: int
    min: float
    max: float
    mean: float

    @classmethod
    def from_scores(cls, scores: Sequence[float]) -> ClassStats:
        """Build stats from a (possibly empty) list of scores."""
        if not scores:
            return cls(count=0, min=float("nan"), max=float("nan"), mean=float("nan"))
        return cls(
            count=len(scores),
            min=min(scores),
            max=max(scores),
            mean=sum(scores) / len(scores),
        )


@dataclass(frozen=True)
class Calibration:
    """Result of a threshold sweep."""

    threshold: float
    accuracy: float
    in_course: ClassStats
    out_course: ClassStats


def _accuracy(
    threshold: float,
    in_course_scores: Sequence[float],
    out_course_scores: Sequence[float],
) -> float:
    """Fraction of questions classified correctly at the given threshold.

    An in-course question is correct when its score is ``>= threshold`` (kept);
    an out-of-course question is correct when its score is ``< threshold``
    (refused). With no questions at all, accuracy is 1.0 (vacuously perfect).
    """
    total = len(in_course_scores) + len(out_course_scores)
    if total == 0:
        return 1.0
    correct = sum(1 for s in in_course_scores if s >= threshold)
    correct += sum(1 for s in out_course_scores if s < threshold)
    return correct / total


def _candidate_grid(
    in_course_scores: Sequence[float],
    out_course_scores: Sequence[float],
) -> list[float]:
    """Default sweep points: every observed score plus midpoints between them.

    Including midpoints lets the sweep land strictly between two adjacent scores,
    which is where a clean decision boundary lives. The points are deduplicated
    and sorted ascending.
    """
    scores = sorted(set(in_course_scores) | set(out_course_scores))
    if not scores:
        return [0.5]
    points = set(scores)
    for lo, hi in zip(scores, scores[1:], strict=False):
        points.add((lo + hi) / 2)
    # A threshold just below the smallest score keeps everything; just above the
    # largest refuses everything. Both are useful boundaries to consider.
    points.add(scores[0] - 1e-9)
    points.add(scores[-1] + 1e-9)
    return sorted(points)


def best_threshold(
    in_course_scores: Sequence[float],
    out_course_scores: Sequence[float],
    *,
    grid: Sequence[float] | None = None,
) -> Calibration:
    """Sweep candidate thresholds and return the one maximizing separation.

    The objective is classification accuracy: in-course questions kept
    (``score >= t``) plus out-of-course questions refused (``score < t``). On a
    tie, the threshold closest to the midpoint between the in-course minimum and
    the out-of-course maximum is preferred, which sits the boundary in the gap
    between the two classes rather than hugging one side.

    ``grid`` overrides the default candidate set (observed scores and their
    midpoints). Returns a :class:`Calibration` with the chosen threshold, the
    achieved accuracy, and the per-class distribution stats.
    """
    in_scores = list(in_course_scores)
    out_scores = list(out_course_scores)

    candidates = list(grid) if grid is not None else _candidate_grid(in_scores, out_scores)
    if not candidates:
        candidates = [0.5]

    # Tie-break target: the natural gap between the classes. Falls back to the
    # midpoint of whatever data exists when one class is empty.
    if in_scores and out_scores:
        midpoint = (min(in_scores) + max(out_scores)) / 2
    elif in_scores:
        midpoint = min(in_scores)
    elif out_scores:
        midpoint = max(out_scores)
    else:
        midpoint = 0.5

    best: tuple[float, float] | None = None  # (accuracy, threshold)
    best_t = candidates[0]
    for t in candidates:
        acc = _accuracy(t, in_scores, out_scores)
        key = (acc, -abs(t - midpoint))
        if best is None or key > best:
            best = key
            best_t = t

    accuracy = _accuracy(best_t, in_scores, out_scores)
    return Calibration(
        threshold=best_t,
        accuracy=accuracy,
        in_course=ClassStats.from_scores(in_scores),
        out_course=ClassStats.from_scores(out_scores),
    )


def score_cases(cases: Sequence[EvalCase], score_fn: ScoreFn) -> tuple[list[float], list[float]]:
    """Split cases by label and score each one with ``score_fn``.

    Returns ``(in_course_scores, out_course_scores)``. The scorer is expected to
    return a question's top retrieval similarity with no threshold applied.
    """
    in_course: list[float] = []
    out_course: list[float] = []
    for case in cases:
        score = score_fn(case.question)
        if case.expect_refusal:
            out_course.append(score)
        else:
            in_course.append(score)
    return in_course, out_course


def _default_score_fn(k: int = 5, owner: str | None = None) -> ScoreFn:
    """Wire the real top-score scorer, imported lazily.

    Queries Qdrant with no score threshold and returns the best chunk's
    similarity, or 0.0 when nothing is retrieved. The retrieval and embedding
    imports happen inside the function so this module stays importable without
    them (CI lint/tests do not load the embedding model).

    ``owner`` scopes the query to one account's material, exactly as the API does.
    Without it the whole collection is scored, so an out-of-course question can
    score highly against *another account's* documents — and the threshold gets
    calibrated to separate classes it will never actually see. Pass the account
    that owns the benchmark corpus.
    """
    from qdrant_client import QdrantClient

    from core.config import get_settings
    from core.retrieval import owner_scope_filter
    from ingestion.embed import embed_query

    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url)
    query_filter = owner_scope_filter(owner) if owner else None

    def top_score(question: str) -> float:
        response = client.query_points(
            collection_name=settings.qdrant_collection,
            query=embed_query(question),
            limit=k,
            query_filter=query_filter,
            # No score_threshold: we want the raw top similarity to calibrate it.
            with_payload=False,
        )
        if not response.points:
            return 0.0
        return max(point.score for point in response.points)

    return top_score


def _fmt(value: float) -> str:
    """Format a score, tolerating NaN for empty classes."""
    return "n/a" if math.isnan(value) else f"{value:.3f}"


def format_report(calibration: Calibration, current_threshold: float) -> str:
    """Render a human-readable calibration report.

    Shows the recommended threshold, the accuracy it achieves, the per-class
    score ranges, and how the recommendation compares to the current setting.
    """
    inc = calibration.in_course
    out = calibration.out_course
    lines = [
        "Similarity-threshold calibration",
        f"  in-course  ({inc.count}): "
        f"min {_fmt(inc.min)}  mean {_fmt(inc.mean)}  max {_fmt(inc.max)}",
        f"  out-course ({out.count}): "
        f"min {_fmt(out.min)}  mean {_fmt(out.mean)}  max {_fmt(out.max)}",
        f"  recommended threshold: {calibration.threshold:.3f}",
        f"  accuracy at threshold: {calibration.accuracy:.0%}",
        f"  current threshold:     {current_threshold:.3f}",
    ]

    delta = calibration.threshold - current_threshold
    if abs(delta) < 1e-6:
        lines.append("  -> current setting already matches the recommendation.")
    else:
        direction = "raise" if delta > 0 else "lower"
        lines.append(
            f"  -> {direction} the threshold by {abs(delta):.3f} "
            f"(set similarity_threshold to {calibration.threshold:.3f})."
        )
    if calibration.accuracy < 1.0:
        lines.append(
            "  note: classes overlap; no threshold separates them perfectly. "
            "Consider revising the dataset or the embedding model."
        )
    return "\n".join(lines)


def calibrate(
    *,
    dataset_path: Path = DATASET_PATH,
    score_fn: ScoreFn | None = None,
    grid: Sequence[float] | None = None,
) -> Calibration:
    """Load the dataset, score every question, and return the calibration.

    ``score_fn`` defaults to the real retrieval-based scorer but is injectable so
    tests can pass a fake and avoid any model load or Qdrant access.
    """
    if score_fn is None:
        score_fn = _default_score_fn()
    cases = load_dataset(dataset_path)
    in_course, out_course = score_cases(cases, score_fn)
    return best_threshold(in_course, out_course, grid=grid)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: print the calibration report against the dataset."""
    parser = argparse.ArgumentParser(
        description="Empirically calibrate the retrieval similarity threshold."
    )
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Top-k chunks to consider when taking each question's top score.",
    )
    parser.add_argument(
        "--owner",
        default=None,
        help=(
            "Scope scoring to this account's material, as the API does. Without it "
            "the whole collection is scored and the threshold is calibrated against "
            "documents the caller will never be shown."
        ),
    )
    args = parser.parse_args(argv)

    from core.config import get_settings

    calibration = calibrate(
        dataset_path=args.dataset, score_fn=_default_score_fn(k=args.k, owner=args.owner)
    )
    print(format_report(calibration, get_settings().similarity_threshold))
    return 0


if __name__ == "__main__":
    sys.exit(main())
