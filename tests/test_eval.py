"""Tests for the offline faithfulness evaluation harness.

Everything here runs with fakes: the answer function and the judge are
injected, so no model or Qdrant is touched and no API call is made.
"""

from pathlib import Path

from eval.run_eval import (
    CaseResult,
    EvalCase,
    Metrics,
    Verdict,
    aggregate,
    evaluate,
    format_summary,
    load_dataset,
    parse_verdict,
    passed,
    run_eval,
)

# --- dataset loader -------------------------------------------------------


def _write_dataset(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "dataset.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_load_dataset_parses_jsonl(tmp_path):
    path = _write_dataset(
        tmp_path,
        [
            '{"question": "What is a wavelet?", "expect_refusal": false, "note": "core"}',
            "",  # blank line is ignored
            '{"question": "Capital of Australia?", "expect_refusal": true, "note": "geo"}',
        ],
    )
    cases = load_dataset(path)
    assert len(cases) == 2
    assert cases[0] == EvalCase("What is a wavelet?", False, "core")
    assert cases[1].expect_refusal is True


def test_bundled_dataset_has_both_classes():
    cases = load_dataset()
    assert any(c.expect_refusal for c in cases)
    assert any(not c.expect_refusal for c in cases)


# --- judge-output parser --------------------------------------------------


def test_parse_verdict_from_mapping():
    v = parse_verdict({"faithful": True, "relevant": False})
    assert v == Verdict(faithful=True, relevant=False)


def test_parse_verdict_from_plain_json_string():
    assert parse_verdict('{"faithful": false, "relevant": true}') == Verdict(False, True)


def test_parse_verdict_from_message_with_code_fence():
    class FakeMessage:
        content = 'Here is my verdict:\n```json\n{"faithful": true, "relevant": true}\n```'

    assert parse_verdict(FakeMessage()) == Verdict(True, True)


def test_parse_verdict_rejects_output_without_json():
    try:
        parse_verdict("no json here")
    except ValueError:
        pass
    else:  # pragma: no cover - failure path
        raise AssertionError("expected ValueError for missing JSON")


# --- metric aggregation ---------------------------------------------------


def test_aggregate_computes_all_rates():
    results = [
        # answerable + correctly answered, faithful and relevant
        CaseResult("q1", expect_refusal=False, refused=False, faithful=True, relevant=True),
        # answerable + answered, but unfaithful
        CaseResult("q2", expect_refusal=False, refused=False, faithful=False, relevant=True),
        # out-of-scope + correctly refused (not judged)
        CaseResult("q3", expect_refusal=True, refused=True),
        # out-of-scope but wrongly answered -> refusal miss (not judged)
        CaseResult("q4", expect_refusal=True, refused=False),
    ]
    m = aggregate(results)
    assert m.total == 4
    assert m.judged == 2
    assert m.refusal_accuracy == 3 / 4
    assert m.faithfulness_rate == 1 / 2
    assert m.relevance_rate == 2 / 2
    assert any("q2" in f for f in m.failures)
    assert any("q4" in f for f in m.failures)


def test_aggregate_empty_is_vacuously_perfect():
    m = aggregate([])
    assert (m.refusal_accuracy, m.faithfulness_rate, m.relevance_rate) == (1.0, 1.0, 1.0)


def test_aggregate_no_judged_cases_reports_perfect_quality_rates():
    results = [CaseResult("q", expect_refusal=True, refused=True)]
    m = aggregate(results)
    assert m.judged == 0
    assert m.faithfulness_rate == 1.0
    assert m.relevance_rate == 1.0


# --- pass / fail decision -------------------------------------------------


def test_passed_requires_all_metrics_to_meet_thresholds():
    thresholds = Metrics(1.0, 1.0, 1.0)
    assert passed(Metrics(1.0, 1.0, 1.0), thresholds)
    assert not passed(Metrics(0.9, 1.0, 1.0), thresholds)
    assert not passed(Metrics(1.0, 0.5, 1.0), thresholds)


# --- end-to-end with injected fakes (no API) ------------------------------


class _RecordingJudge:
    """Fake judge returning canned JSON; records that it was only called when due."""

    def __init__(self, verdict: dict):
        self._verdict = verdict
        self.calls: list[str] = []

    def __call__(self, question, answer_text, sources):
        self.calls.append(question)
        return self._verdict


def _fake_answer_factory(answered: dict, refused_questions: set[str]):
    def fake_answer(question: str) -> dict:
        if question in refused_questions:
            return {"answer": "This is not covered.", "refused": True, "sources": []}
        return answered

    return fake_answer


def test_evaluate_only_judges_answerable_answered_cases():
    cases = [
        EvalCase("in-scope", expect_refusal=False),
        EvalCase("out-of-scope", expect_refusal=True),
    ]
    answered = {
        "answer": "A wavelet is X [1].",
        "refused": False,
        "sources": ["(Wavelet Transform, p.1)"],
    }
    judge = _RecordingJudge({"faithful": True, "relevant": True})
    fake_answer = _fake_answer_factory(answered, refused_questions={"out-of-scope"})

    results = evaluate(cases, fake_answer, judge)

    # The judge is only consulted for the in-scope, answered case.
    assert judge.calls == ["in-scope"]
    assert results[0].faithful is True and results[0].relevant is True
    assert results[1].refused is True and results[1].faithful is None


def test_run_eval_passes_when_everything_is_correct():
    dataset = [
        EvalCase("in-scope", expect_refusal=False),
        EvalCase("out-of-scope", expect_refusal=True),
    ]
    answered = {"answer": "ok [1]", "refused": False, "sources": ["s"]}
    judge = _RecordingJudge({"faithful": True, "relevant": True})
    fake_answer = _fake_answer_factory(answered, refused_questions={"out-of-scope"})

    metrics, ok = run_eval(
        dataset_path=_DummyPath(dataset),
        answer_fn=fake_answer,
        judge_fn=judge,
    )
    assert ok is True
    assert metrics.refusal_accuracy == 1.0
    assert metrics.faithfulness_rate == 1.0


def test_run_eval_fails_on_unfaithful_answer():
    dataset = [EvalCase("in-scope", expect_refusal=False)]
    answered = {"answer": "hallucinated", "refused": False, "sources": ["s"]}
    judge = _RecordingJudge({"faithful": False, "relevant": True})
    fake_answer = _fake_answer_factory(answered, refused_questions=set())

    metrics, ok = run_eval(
        dataset_path=_DummyPath(dataset),
        answer_fn=fake_answer,
        judge_fn=judge,
    )
    assert ok is False
    assert metrics.faithfulness_rate == 0.0


def test_run_eval_fails_when_out_of_scope_is_answered():
    dataset = [EvalCase("out-of-scope", expect_refusal=True)]
    answered = {"answer": "made up", "refused": False, "sources": []}
    judge = _RecordingJudge({"faithful": True, "relevant": True})
    fake_answer = _fake_answer_factory(answered, refused_questions=set())

    metrics, ok = run_eval(
        dataset_path=_DummyPath(dataset),
        answer_fn=fake_answer,
        judge_fn=judge,
    )
    assert ok is False
    assert metrics.refusal_accuracy == 0.0


def test_format_summary_reports_pass_and_fail():
    thresholds = Metrics(1.0, 1.0, 1.0)
    pass_text = format_summary(Metrics(1.0, 1.0, 1.0, judged=2, total=3), thresholds, True)
    assert "PASS" in pass_text
    fail_metrics = Metrics(0.5, 1.0, 1.0, judged=1, total=2, failures=["x"])
    fail_text = format_summary(fail_metrics, thresholds, False)
    assert "FAIL" in fail_text
    assert "x" in fail_text


class _DummyPath:
    """Stand-in for a dataset path that yields preloaded cases.

    ``run_eval`` calls ``load_dataset(path)``; we instead make the path carry
    its own JSONL so no temp file is needed. This keeps the test self-contained
    while still exercising the loader-to-aggregate pipeline through run_eval.
    """

    def __init__(self, cases: list[EvalCase]):
        import json

        self._text = "\n".join(
            json.dumps(
                {
                    "question": c.question,
                    "expect_refusal": c.expect_refusal,
                    "note": c.note,
                }
            )
            for c in cases
        )

    def read_text(self, encoding: str = "utf-8") -> str:
        return self._text
