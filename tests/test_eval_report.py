"""Tests for the Markdown report generator and the dataset expansion.

Everything here is offline: no LLM, no Qdrant, no API call. The report renderer
is a pure function and the ``--report`` hook is exercised by monkeypatching
``run_eval`` so only the writing path runs.
"""

import json

from eval.report import (
    render_report,
    render_report_from_file,
    write_report,
)
from eval.run_eval import (
    DATASET_PATH,
    Metrics,
    load_dataset,
    main,
    metrics_to_dict,
)

# --- dataset still parses and validates after the expansion ---------------

_ALLOWED_FIELDS = {"question", "expect_refusal", "note", "expect_keywords", "category"}


def test_expanded_dataset_every_line_parses_and_validates():
    in_course = 0
    out_course = 0
    questions: set[str] = set()
    for raw in DATASET_PATH.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        assert set(obj) <= _ALLOWED_FIELDS, f"unexpected fields: {set(obj) - _ALLOWED_FIELDS}"
        assert isinstance(obj["question"], str) and obj["question"].strip()
        assert isinstance(obj["expect_refusal"], bool)
        questions.add(obj["question"])
        if obj["expect_refusal"]:
            out_course += 1
            # Out-of-course cases never carry keywords.
            assert "expect_keywords" not in obj or obj["expect_keywords"] == []
        else:
            in_course += 1
            assert isinstance(obj.get("expect_keywords", []), list)
            assert obj.get("expect_keywords"), "in-course case should declare keywords"
            assert all(k == k.lower() for k in obj["expect_keywords"])
    # The expansion grows both classes well past the original counts.
    assert in_course >= 24
    assert out_course >= 18


def test_expanded_dataset_has_no_duplicate_questions():
    cases = load_dataset()
    questions = [c.question for c in cases]
    assert len(questions) == len(set(questions)), "duplicate reference questions found"


def test_expanded_dataset_loads_into_eval_cases():
    cases = load_dataset()
    assert len(cases) >= 40
    assert any(c.expect_refusal for c in cases)
    assert any(not c.expect_refusal for c in cases)


# --- report rendering: full metrics dict ----------------------------------


def _full_metrics() -> dict:
    return metrics_to_dict(
        Metrics(
            refusal_accuracy=1.0,
            faithfulness_rate=0.75,
            relevance_rate=1.0,
            retrieval_hit_rate=0.5,
            judged=3,
            total=4,
            retrieval_checked=2,
            failures=["unfaithful answer: 'q'"],
        )
    )


def test_render_report_renders_table_and_summary():
    md = render_report(_full_metrics(), title="My report")
    assert md.startswith("# My report")
    # Table header and a couple of rows.
    assert "| Metric | Value | Threshold | Status |" in md
    assert "| Refusal accuracy | 100% |" in md
    assert "| Faithfulness | 75% |" in md
    assert "| Retrieval hit rate | 50% |" in md
    # Counts and failures sections.
    assert "**Total cases:** 4" in md
    assert "## Failures" in md
    assert "unfaithful answer: 'q'" in md
    assert "## Summary" in md


def test_render_report_pass_fail_status_uses_thresholds():
    # Default thresholds: faithfulness must be 100%, so 75% fails overall.
    md_default = render_report(_full_metrics())
    assert "**Overall result: FAIL**" in md_default
    # Relaxed faithfulness threshold flips the verdict to PASS.
    md_relaxed = render_report(
        _full_metrics(),
        thresholds={
            "refusal_accuracy": 1.0,
            "faithfulness_rate": 0.5,
            "relevance_rate": 1.0,
            "retrieval_hit_rate": 0.0,
        },
    )
    assert "**Overall result: PASS**" in md_relaxed


def test_render_report_handles_missing_keys_gracefully():
    # Only a subset of the metrics is present.
    md = render_report({"faithfulness_rate": 1.0})
    assert "| Faithfulness | 100% |" in md
    # Absent rates simply do not appear.
    assert "Refusal accuracy" not in md
    assert "Retrieval hit rate" not in md
    # A subset that still has all rates verdicts PASS.
    assert "## Summary" in md


def test_render_report_handles_empty_metrics():
    md = render_report({})
    assert "_(no metrics)_" in md
    assert "No rate metrics were provided." in md


def test_render_report_non_numeric_value_is_not_a_failure():
    md = render_report({"faithfulness_rate": None})
    # A non-numeric value renders as n/a and does not flip the verdict to FAIL.
    assert "| Faithfulness | n/a | 100% | n/a |" in md
    assert "**Overall result: PASS**" in md


def test_write_report_creates_parent_dirs_and_writes_markdown(tmp_path):
    path = tmp_path / "nested" / "report.md"
    write_report(_full_metrics(), path)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Offline evaluation report")
    assert "| Faithfulness | 75% |" in text


def test_render_report_from_file_round_trips(tmp_path):
    path = tmp_path / "results.json"
    path.write_text(json.dumps(_full_metrics()), encoding="utf-8")
    md = render_report_from_file(path)
    assert "| Faithfulness | 75% |" in md


# --- the --report hook on the CLI (no API) --------------------------------


def test_main_with_report_writes_markdown(tmp_path):
    """``main --report`` writes the Markdown report without any API call.

    ``run_eval`` is monkeypatched so no answer function, judge or retrieval is
    wired; only the report-writing path is exercised.
    """
    import eval.run_eval as run_eval_module

    metrics = Metrics(
        refusal_accuracy=1.0,
        faithfulness_rate=1.0,
        relevance_rate=1.0,
        retrieval_hit_rate=1.0,
        judged=1,
        total=2,
    )
    report_path = tmp_path / "report.md"
    original = run_eval_module.run_eval
    run_eval_module.run_eval = lambda **_kwargs: (metrics, True)
    try:
        code = main(["--report", str(report_path)])
    finally:
        run_eval_module.run_eval = original

    assert code == 0
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "# Offline evaluation report" in text
    assert "**Overall result: PASS**" in text


def test_main_without_report_does_not_write(tmp_path, monkeypatch):
    """The default run (no --report) writes no report file."""
    import eval.run_eval as run_eval_module

    monkeypatch.setattr(
        run_eval_module, "run_eval", lambda **_kwargs: (Metrics(1.0, 1.0, 1.0), True)
    )
    monkeypatch.chdir(tmp_path)
    code = main([])
    assert code == 0
    assert not (tmp_path / "eval" / "report.md").exists()
