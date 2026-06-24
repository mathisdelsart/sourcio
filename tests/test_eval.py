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
    main,
    metrics_to_dict,
    parse_verdict,
    passed,
    retrieval_hit,
    run_eval,
    write_results,
)
from ui.metrics import format_metric_cards, load_metrics_file

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


def test_bundled_dataset_is_expanded_with_keywords():
    cases = load_dataset()
    # The expansion brings the dataset to roughly sixteen reference questions.
    assert len(cases) >= 16
    # In-course cases declare keywords; out-of-course cases never do.
    with_keywords = [c for c in cases if c.expect_keywords]
    assert with_keywords, "expected some in-course cases to declare keywords"
    assert all(not c.expect_refusal for c in with_keywords)
    assert all(c.expect_keywords == () for c in cases if c.expect_refusal)
    # Keywords are stored lowercase so substring matching is case-insensitive.
    for c in with_keywords:
        assert all(k == k.lower() for k in c.expect_keywords)


def test_load_dataset_parses_expect_keywords(tmp_path):
    path = _write_dataset(
        tmp_path,
        [
            '{"question": "Haar?", "expect_refusal": false, '
            '"expect_keywords": ["Haar", "WAVELET"]}',
        ],
    )
    cases = load_dataset(path)
    # Keywords are normalized to lowercase tuples.
    assert cases[0].expect_keywords == ("haar", "wavelet")


def test_load_dataset_defaults_keywords_to_empty(tmp_path):
    path = _write_dataset(
        tmp_path,
        ['{"question": "Capital of Australia?", "expect_refusal": true}'],
    )
    cases = load_dataset(path)
    assert cases[0].expect_keywords == ()


# --- retrieval-hit metric -------------------------------------------------


def test_retrieval_hit_accepts_when_keyword_present():
    texts = ["The Haar scaling function builds a piecewise constant approximation."]
    assert retrieval_hit(texts, ["piecewise constant"]) is True


def test_retrieval_hit_is_case_insensitive():
    assert retrieval_hit(["A WAVELET Transform"], ["wavelet"]) is True


def test_retrieval_hit_matches_any_keyword_across_chunks():
    texts = ["unrelated chunk", "multiresolution analysis here"]
    assert retrieval_hit(texts, ["scaling function", "multiresolution"]) is True


def test_retrieval_hit_rejects_when_no_keyword_present():
    assert retrieval_hit(["completely unrelated text"], ["multiresolution"]) is False


def test_retrieval_hit_rejects_with_no_keywords():
    assert retrieval_hit(["anything"], []) is False


def test_aggregate_computes_retrieval_hit_rate():
    results = [
        CaseResult("q1", expect_refusal=False, refused=False, retrieval_hit=True),
        CaseResult("q2", expect_refusal=False, refused=False, retrieval_hit=False),
        # No keyword declared -> not part of the retrieval-hit denominator.
        CaseResult("q3", expect_refusal=False, refused=False),
    ]
    m = aggregate(results)
    assert m.retrieval_checked == 2
    assert m.retrieval_hit_rate == 1 / 2
    assert any("q2" in f and "keyword" in f for f in m.failures)


def test_aggregate_no_retrieval_checked_is_vacuously_perfect():
    results = [CaseResult("q", expect_refusal=True, refused=True)]
    m = aggregate(results)
    assert m.retrieval_checked == 0
    assert m.retrieval_hit_rate == 1.0


def test_evaluate_runs_retrieval_hit_for_in_course_keyword_cases():
    cases = [
        EvalCase("in-scope", expect_refusal=False, expect_keywords=("haar",)),
        EvalCase("in-scope-no-kw", expect_refusal=False),
        EvalCase("out-of-scope", expect_refusal=True, expect_keywords=()),
    ]
    answered = {"answer": "ok [1]", "refused": False, "sources": ["s"]}
    judge = _RecordingJudge({"faithful": True, "relevant": True})
    fake_answer = _fake_answer_factory(answered, refused_questions={"out-of-scope"})

    calls: list[str] = []

    def fake_retrieve(question: str):
        calls.append(question)
        return ["a chunk about the Haar wavelet"]

    results = evaluate(cases, fake_answer, judge, fake_retrieve)

    # Retrieval only runs for the in-course case that declares keywords.
    assert calls == ["in-scope"]
    assert results[0].retrieval_hit is True
    assert results[1].retrieval_hit is None
    assert results[2].retrieval_hit is None


def test_passed_honors_retrieval_hit_threshold():
    thresholds = Metrics(1.0, 1.0, 1.0, retrieval_hit_rate=1.0)
    assert passed(Metrics(1.0, 1.0, 1.0, retrieval_hit_rate=1.0), thresholds)
    assert not passed(Metrics(1.0, 1.0, 1.0, retrieval_hit_rate=0.5), thresholds)
    # A relaxed threshold tolerates a low hit rate.
    relaxed = Metrics(1.0, 1.0, 1.0, retrieval_hit_rate=0.0)
    assert passed(Metrics(1.0, 1.0, 1.0, retrieval_hit_rate=0.5), relaxed)


def test_run_eval_fails_on_retrieval_miss_when_threshold_set():
    dataset = [EvalCase("in-scope", expect_refusal=False, expect_keywords=("multiresolution",))]
    answered = {"answer": "ok [1]", "refused": False, "sources": ["s"]}
    judge = _RecordingJudge({"faithful": True, "relevant": True})
    fake_answer = _fake_answer_factory(answered, refused_questions=set())

    def fake_retrieve(question: str):
        return ["a chunk with no relevant keyword"]

    metrics, ok = run_eval(
        dataset_path=_DummyPath(dataset),
        answer_fn=fake_answer,
        judge_fn=judge,
        retrieve_fn=fake_retrieve,
        thresholds=Metrics(1.0, 1.0, 1.0, retrieval_hit_rate=1.0),
    )
    assert metrics.retrieval_hit_rate == 0.0
    assert ok is False


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


def _no_retrieve(question: str) -> list[str]:
    """Fake retrieval that returns nothing, so no Qdrant/model is touched."""
    return []


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
        retrieve_fn=_no_retrieve,
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
        retrieve_fn=_no_retrieve,
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
        retrieve_fn=_no_retrieve,
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
                    "expect_keywords": list(c.expect_keywords),
                }
            )
            for c in cases
        )

    def read_text(self, encoding: str = "utf-8") -> str:
        return self._text


# --- results JSON reporting (no API) --------------------------------------


def test_metrics_to_dict_exposes_all_fields():
    metrics = Metrics(
        refusal_accuracy=1.0,
        faithfulness_rate=0.9,
        relevance_rate=0.8,
        retrieval_hit_rate=0.5,
        judged=3,
        total=4,
        retrieval_checked=2,
        failures=["unfaithful answer: 'q'"],
    )
    data = metrics_to_dict(metrics)
    assert data == {
        "refusal_accuracy": 1.0,
        "faithfulness_rate": 0.9,
        "relevance_rate": 0.8,
        "retrieval_hit_rate": 0.5,
        "judged": 3,
        "total": 4,
        "retrieval_checked": 2,
        "failures": ["unfaithful answer: 'q'"],
    }


def test_metrics_to_dict_round_trips_through_load_metrics_file(tmp_path):
    metrics = Metrics(
        refusal_accuracy=1.0,
        faithfulness_rate=0.75,
        relevance_rate=1.0,
        retrieval_hit_rate=0.5,
        judged=2,
        total=3,
        retrieval_checked=2,
    )
    path = tmp_path / "results.json"
    write_results(metrics, path)

    loaded = load_metrics_file(path)
    assert loaded == metrics_to_dict(metrics)
    assert loaded["faithfulness_rate"] == 0.75
    assert loaded["retrieval_hit_rate"] == 0.5
    assert loaded["total"] == 3

    # The loaded dict feeds the dashboard cards unchanged.
    by_key = {c.key: c for c in format_metric_cards(loaded)}
    assert by_key["faithfulness_rate"].display == "75%"
    assert by_key["retrieval_hit_rate"].display == "50%"


def test_write_results_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "results.json"
    write_results(Metrics(1.0, 1.0, 1.0), path)
    assert path.exists()
    assert load_metrics_file(path)["refusal_accuracy"] == 1.0


def test_main_with_out_writes_results_file(tmp_path):
    """``main --out`` writes the metrics JSON without any API call.

    The whole evaluation is driven by monkeypatching ``run_eval`` so no answer
    function, judge or retrieval is wired; only the JSON-writing path is tested.
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
    out_path = tmp_path / "results.json"
    original = run_eval_module.run_eval
    run_eval_module.run_eval = lambda **_kwargs: (metrics, True)
    try:
        code = main(["--out", str(out_path)])
    finally:
        run_eval_module.run_eval = original

    assert code == 0
    assert load_metrics_file(out_path) == metrics_to_dict(metrics)


def test_main_without_out_does_not_write(tmp_path, monkeypatch):
    """The default run (no --out) writes nothing, matching the prior behaviour."""
    import eval.run_eval as run_eval_module

    monkeypatch.setattr(
        run_eval_module, "run_eval", lambda **_kwargs: (Metrics(1.0, 1.0, 1.0), True)
    )
    monkeypatch.chdir(tmp_path)
    code = main([])
    assert code == 0
    assert not (tmp_path / "eval" / "results.json").exists()
