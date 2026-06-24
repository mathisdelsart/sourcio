"""Tests for the similarity-threshold calibration tool.

Everything here runs on synthetic score lists or with an injected fake scorer,
so no embedding model is loaded, Qdrant is never touched, and no API call is
made. Only the pure sweep/metric/report logic is exercised.
"""

import math

from eval.calibrate import (
    Calibration,
    ClassStats,
    best_threshold,
    calibrate,
    format_report,
    score_cases,
)
from eval.run_eval import EvalCase

# --- best_threshold: pure sweep logic -------------------------------------


def test_clean_separation_threshold_between_classes_accuracy_one():
    in_course = [0.8, 0.9, 0.85]
    out_course = [0.1, 0.2, 0.15]

    result = best_threshold(in_course, out_course)

    assert result.accuracy == 1.0
    # Boundary should sit strictly between the two clusters.
    assert max(out_course) < result.threshold <= min(in_course)


def test_clean_separation_picks_midpoint_of_the_gap():
    # With a wide gap, the tie-break prefers the midpoint between classes.
    in_course = [0.9]
    out_course = [0.1]

    result = best_threshold(in_course, out_course)

    assert result.accuracy == 1.0
    assert math.isclose(result.threshold, 0.5, abs_tol=1e-6)


def test_overlapping_distributions_maximizes_accuracy():
    # One out-of-course score (0.6) sits inside the in-course range; one
    # in-course score (0.55) dips low. No threshold is perfect.
    in_course = [0.55, 0.7, 0.8, 0.9]
    out_course = [0.1, 0.2, 0.3, 0.6]

    result = best_threshold(in_course, out_course)

    # Best achievable: classify all but the two crossing points correctly.
    # 8 questions, at most one misclassified on each side around the overlap.
    assert result.accuracy >= 6 / 8
    # No grid point beats the reported accuracy.
    grid = [s / 100 for s in range(0, 101)]
    best_acc = max(best_threshold(in_course, out_course, grid=[t]).accuracy for t in grid)
    assert math.isclose(result.accuracy, best_acc, abs_tol=1e-9)


def test_custom_grid_is_respected():
    in_course = [0.8]
    out_course = [0.2]

    # Only offer thresholds that cannot perfectly separate (both below both
    # scores keeps everything; out-course always misclassified).
    result = best_threshold(in_course, out_course, grid=[0.05, 0.1])

    assert result.threshold in (0.05, 0.1)
    assert result.accuracy == 0.5  # in-course kept, out-course wrongly kept


def test_empty_lists_are_safe():
    result = best_threshold([], [])

    assert result.accuracy == 1.0
    assert result.in_course.count == 0
    assert result.out_course.count == 0
    assert math.isnan(result.in_course.mean)


def test_only_in_course():
    result = best_threshold([0.7, 0.8], [])

    assert result.accuracy == 1.0
    # A threshold at/below the minimum keeps every in-course question.
    assert result.threshold <= 0.7


def test_only_out_course():
    result = best_threshold([], [0.2, 0.3])

    assert result.accuracy == 1.0
    # A threshold above the maximum refuses every out-of-course question.
    assert result.threshold > 0.3


def test_all_equal_scores_cannot_separate():
    # Identical scores in both classes: any threshold keeps or refuses both.
    result = best_threshold([0.5, 0.5], [0.5, 0.5])

    # Best is to keep both (threshold <= 0.5): 2 right, 2 wrong.
    assert result.accuracy == 0.5


# --- ClassStats -----------------------------------------------------------


def test_class_stats_from_scores():
    stats = ClassStats.from_scores([0.2, 0.4, 0.6])

    assert stats.count == 3
    assert stats.min == 0.2
    assert stats.max == 0.6
    assert math.isclose(stats.mean, 0.4)


def test_class_stats_empty_is_nan():
    stats = ClassStats.from_scores([])

    assert stats.count == 0
    assert math.isnan(stats.min)
    assert math.isnan(stats.max)
    assert math.isnan(stats.mean)


# --- score_cases with an injected fake scorer -----------------------------


def test_score_cases_splits_by_label():
    cases = [
        EvalCase(question="in A", expect_refusal=False),
        EvalCase(question="out B", expect_refusal=True),
        EvalCase(question="in C", expect_refusal=False),
    ]
    fake_scores = {"in A": 0.9, "out B": 0.1, "in C": 0.85}

    in_course, out_course = score_cases(cases, lambda q: fake_scores[q])

    assert sorted(in_course) == [0.85, 0.9]
    assert out_course == [0.1]


def test_calibrate_with_injected_scorer_touches_no_qdrant(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"question": "wavelet?", "expect_refusal": false, "note": "in"}',
                '{"question": "capital?", "expect_refusal": true, "note": "out"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    scores = {"wavelet?": 0.88, "capital?": 0.12}

    result = calibrate(dataset_path=path, score_fn=lambda q: scores[q])

    assert result.accuracy == 1.0
    assert result.in_course.count == 1
    assert result.out_course.count == 1
    assert 0.12 < result.threshold <= 0.88


# --- report formatting ----------------------------------------------------


def _calibration(threshold, accuracy=1.0):
    return Calibration(
        threshold=threshold,
        accuracy=accuracy,
        in_course=ClassStats.from_scores([0.8, 0.9]),
        out_course=ClassStats.from_scores([0.1, 0.2]),
    )


def test_format_report_recommends_raising():
    report = format_report(_calibration(0.55), current_threshold=0.5)

    assert "recommended threshold: 0.550" in report
    assert "accuracy at threshold: 100%" in report
    assert "current threshold:     0.500" in report
    assert "raise" in report


def test_format_report_recommends_lowering():
    report = format_report(_calibration(0.40), current_threshold=0.5)

    assert "lower" in report


def test_format_report_matches_current():
    report = format_report(_calibration(0.5), current_threshold=0.5)

    assert "already matches the recommendation" in report


def test_format_report_warns_on_overlap():
    report = format_report(_calibration(0.5, accuracy=0.75), current_threshold=0.5)

    assert "overlap" in report
    assert "accuracy at threshold: 75%" in report


def test_format_report_handles_empty_class():
    calibration = Calibration(
        threshold=0.5,
        accuracy=1.0,
        in_course=ClassStats.from_scores([0.8]),
        out_course=ClassStats.from_scores([]),
    )

    report = format_report(calibration, current_threshold=0.5)

    assert "n/a" in report  # empty out-course class renders as n/a
