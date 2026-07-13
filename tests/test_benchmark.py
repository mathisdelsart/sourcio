"""Tests for the provider benchmark harness and its comparison report.

Everything here runs with fakes: the answer function, judge and retrieval are
injected, so no model or Qdrant is touched and no API call is made.
"""

import json

from eval.benchmark import (
    DATASET_PATH,
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkMetrics,
    aggregate,
    answer_keyword_hit,
    evaluate,
    format_summary,
    has_citation,
    load_dataset,
    main,
    metrics_to_dict,
    provider_label,
    run_benchmark,
    write_results,
)
from eval.compare_report import (
    render_comparison,
    render_comparison_from_files,
    write_comparison,
)
from eval.run_eval import EvalCase
from eval.run_eval import load_dataset as load_eval_dataset

# --- dataset --------------------------------------------------------------

_ALLOWED_FIELDS = {"question", "expect_refusal", "note", "expect_keywords", "category"}
_CATEGORIES = {"factual", "math", "synthesis", "refuse"}


def test_bundled_dataset_has_the_expected_case_mix():
    cases = load_dataset()
    assert len(cases) == 50
    refuse = [c for c in cases if c.case.expect_refusal]
    answer = [c for c in cases if not c.case.expect_refusal]
    assert len(refuse) == 18
    assert len(answer) == 32


def test_bundled_dataset_parses_with_plain_eval_loader():
    # The shipped file must also parse through the base EvalCase loader, proving
    # the extra ``category`` key does not break the reused schema.
    cases = load_eval_dataset(DATASET_PATH)
    assert len(cases) == 50
    assert any(c.expect_refusal for c in cases)
    assert any(not c.expect_refusal for c in cases)


def test_bundled_dataset_every_line_matches_schema():
    seen = 0
    categories: set[str] = set()
    for raw in DATASET_PATH.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        seen += 1
        obj = json.loads(raw)
        assert set(obj) <= _ALLOWED_FIELDS, f"unexpected fields: {set(obj) - _ALLOWED_FIELDS}"
        assert isinstance(obj["question"], str) and obj["question"].strip()
        assert isinstance(obj["expect_refusal"], bool)
        categories.add(obj.get("category", ""))
        if obj["expect_refusal"]:
            # Out-of-scope cases carry no keywords.
            assert "expect_keywords" not in obj or obj["expect_keywords"] == []
        else:
            assert obj.get("expect_keywords"), "answer-case should declare keywords"
            assert all(isinstance(k, str) for k in obj["expect_keywords"])
    assert seen == 50
    assert categories == _CATEGORIES


def test_load_dataset_keeps_category_and_lowercases_keywords(tmp_path):
    path = tmp_path / "bench.jsonl"
    path.write_text(
        '{"question": "Q?", "expect_refusal": false, "category": "factual", '
        '"expect_keywords": ["PPO", "CBAM"]}\n',
        encoding="utf-8",
    )
    cases = load_dataset(path)
    assert cases[0].category == "factual"
    assert cases[0].case.expect_keywords == ("ppo", "cbam")


# --- citation / answer-keyword helpers ------------------------------------


def test_has_citation_detects_marker():
    assert has_citation("The win rate is 96.67% [2].") is True
    assert has_citation("No citation here.") is False
    assert has_citation("") is False


def test_answer_keyword_hit_is_case_insensitive():
    assert answer_keyword_hit("The baseline is PPO.", ["ppo"]) is True
    assert answer_keyword_hit("Uses A2C instead.", ["ppo"]) is False
    assert answer_keyword_hit("anything", []) is False


# --- aggregation ----------------------------------------------------------


def test_aggregate_computes_all_rates():
    results = [
        # answered answer-case: faithful, relevant, cited, keyword present
        BenchmarkCaseResult(
            "q1",
            "factual",
            expect_refusal=False,
            refused=False,
            faithful=True,
            relevant=True,
            cited=True,
            answer_keyword_hit=True,
            retrieval_hit=True,
        ),
        # answered answer-case: unfaithful, uncited, keyword missing, retrieval miss
        BenchmarkCaseResult(
            "q2",
            "math",
            expect_refusal=False,
            refused=False,
            faithful=False,
            relevant=True,
            cited=False,
            answer_keyword_hit=False,
            retrieval_hit=False,
        ),
        # refuse-case correctly refused (not judged)
        BenchmarkCaseResult("q3", "refuse", expect_refusal=True, refused=True),
        # refuse-case wrongly answered -> refusal miss
        BenchmarkCaseResult("q4", "refuse", expect_refusal=True, refused=False),
    ]
    m = aggregate(results, provider="openai")
    assert m.provider == "openai"
    assert m.total == 4
    assert m.judged == 2
    assert m.refusal_accuracy == 3 / 4
    assert m.faithfulness_rate == 1 / 2
    assert m.relevance_rate == 2 / 2
    assert m.citation_rate == 1 / 2
    assert m.answer_keyword_rate == 1 / 2
    assert m.retrieval_hit_rate == 1 / 2
    assert m.cited_checked == 2
    assert m.answer_keyword_checked == 2
    assert m.retrieval_checked == 2
    joined = " ".join(m.failures)
    assert "q2" in joined and "q4" in joined


def test_aggregate_empty_is_vacuously_perfect():
    m = aggregate([], provider="groq")
    assert (m.refusal_accuracy, m.faithfulness_rate, m.relevance_rate) == (1.0, 1.0, 1.0)
    assert (m.citation_rate, m.answer_keyword_rate, m.retrieval_hit_rate) == (1.0, 1.0, 1.0)


def test_aggregate_carries_latency():
    m = aggregate([], retrieval_p50_ms=67.0, retrieval_p95_ms=466.0)
    assert m.retrieval_p50_ms == 67.0
    assert m.retrieval_p95_ms == 466.0


# --- end-to-end evaluate with fakes (no API) ------------------------------


class _RecordingJudge:
    def __init__(self, verdict: dict):
        self._verdict = verdict
        self.calls: list[str] = []

    def __call__(self, question, answer_text, sources):
        self.calls.append(question)
        return self._verdict


def _bc(question, category, expect_refusal, keywords=()):
    return BenchmarkCase(
        EvalCase(question, expect_refusal, expect_keywords=tuple(keywords)),
        category=category,
    )


def test_evaluate_scores_answer_and_refuse_cases():
    cases = [
        _bc("factual q", "factual", False, keywords=("ppo",)),
        _bc("refuse q", "refuse", True),
    ]
    answered = {
        "answer": "The baseline is PPO [1].",
        "refused": False,
        "sources": ["(Thesis, p.1)"],
        "retrieved": ["PPO is the training algorithm."],
    }

    def fake_answer(question):
        if question == "refuse q":
            return {"answer": "This is not covered.", "refused": True, "sources": []}
        return answered

    judge = _RecordingJudge({"faithful": True, "relevant": True})

    retrieve_calls: list[str] = []

    def fake_retrieve(question):
        retrieve_calls.append(question)
        return ["PPO is the training algorithm."]

    results = evaluate(cases, fake_answer, judge, fake_retrieve)

    # Judge and retrieval only run for the answered answer-case.
    assert judge.calls == ["factual q"]
    assert retrieve_calls == ["factual q"]
    r0 = results[0]
    assert r0.faithful is True and r0.relevant is True
    assert r0.cited is True
    assert r0.answer_keyword_hit is True
    assert r0.retrieval_hit is True
    # The refuse-case is scored only on the refusal decision.
    r1 = results[1]
    assert r1.refused is True
    assert r1.faithful is None and r1.cited is None and r1.answer_keyword_hit is None


def test_evaluate_refused_answer_case_is_not_cited_or_keyword_checked():
    cases = [_bc("factual q", "factual", False, keywords=("ppo",))]

    def refusing_answer(_question):
        return {"answer": "This is not covered.", "refused": True, "sources": []}

    judge = _RecordingJudge({"faithful": True, "relevant": True})
    results = evaluate(cases, refusing_answer, judge, retrieve_fn=None)

    assert judge.calls == []  # not answered -> not judged
    assert results[0].cited is None
    assert results[0].answer_keyword_hit is None


def test_run_benchmark_end_to_end_with_fakes(tmp_path):
    path = tmp_path / "bench.jsonl"
    path.write_text(
        '{"question": "factual q", "expect_refusal": false, "category": "factual", '
        '"expect_keywords": ["ppo"]}\n'
        '{"question": "refuse q", "expect_refusal": true, "category": "refuse"}\n',
        encoding="utf-8",
    )

    def fake_answer(question):
        if question == "refuse q":
            return {"answer": "This is not covered.", "refused": True, "sources": []}
        return {
            "answer": "The baseline is PPO [1].",
            "refused": False,
            "sources": ["(Thesis, p.1)"],
            "retrieved": ["PPO is the training algorithm."],
        }

    metrics = run_benchmark(
        dataset_path=path,
        provider="openai",
        answer_fn=fake_answer,
        judge_fn=_RecordingJudge({"faithful": True, "relevant": True}),
        retrieve_fn=lambda _q: ["PPO is the training algorithm."],
    )
    assert metrics.provider == "openai"
    assert metrics.total == 2
    assert metrics.refusal_accuracy == 1.0
    assert metrics.faithfulness_rate == 1.0
    assert metrics.citation_rate == 1.0
    assert metrics.answer_keyword_rate == 1.0
    assert metrics.retrieval_hit_rate == 1.0


def test_provider_label_defaults_to_openai(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert provider_label() == "openai"
    monkeypatch.setenv("LLM_PROVIDER", "GROQ")
    assert provider_label() == "groq"


def test_format_summary_mentions_provider_and_latency():
    m = BenchmarkMetrics(
        provider="groq",
        refusal_accuracy=1.0,
        faithfulness_rate=0.9,
        relevance_rate=1.0,
        retrieval_hit_rate=0.8,
        citation_rate=1.0,
        answer_keyword_rate=0.75,
        judged=3,
        total=5,
        retrieval_p50_ms=67.0,
        retrieval_p95_ms=466.0,
        failures=["unfaithful answer: 'x'"],
    )
    text = format_summary(m)
    assert "groq" in text
    assert "67 ms" in text and "466 ms" in text
    assert "x" in text


def test_format_summary_handles_missing_latency():
    m = BenchmarkMetrics("openai", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
    assert "n/a" in format_summary(m)


# --- results JSON ----------------------------------------------------------


def test_write_results_round_trips(tmp_path):
    m = BenchmarkMetrics("openai", 1.0, 0.9, 1.0, 0.8, 1.0, 0.75, judged=3, total=5)
    path = tmp_path / "nested" / "bench.json"
    write_results(m, path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == metrics_to_dict(m)
    assert loaded["provider"] == "openai"


def test_main_writes_results(tmp_path, monkeypatch):
    import eval.benchmark as bench

    m = BenchmarkMetrics("openai", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, judged=1, total=2)
    monkeypatch.setattr(bench, "run_benchmark", lambda **_kwargs: m)
    out_path = tmp_path / "bench.json"
    code = main(["--out", str(out_path)])
    assert code == 0
    assert json.loads(out_path.read_text(encoding="utf-8")) == metrics_to_dict(m)


# --- comparison report -----------------------------------------------------


def _metrics_dict(provider: str, faithfulness: float, p50: float) -> dict:
    return metrics_to_dict(
        BenchmarkMetrics(
            provider=provider,
            refusal_accuracy=1.0,
            faithfulness_rate=faithfulness,
            relevance_rate=1.0,
            retrieval_hit_rate=0.82,
            citation_rate=1.0,
            answer_keyword_rate=0.7,
            judged=22,
            total=27,
            retrieval_checked=22,
            retrieval_p50_ms=p50,
            retrieval_p95_ms=466.0,
        )
    )


def test_render_comparison_builds_side_by_side_table():
    a = _metrics_dict("openai", 1.0, 67.0)
    b = _metrics_dict("groq", 0.9, 120.0)
    md = render_comparison(a, b)
    assert md.startswith("# Benchmark comparison")
    # Columns are labelled by the provider fields.
    assert "| Metric | openai | groq | Delta (B - A) |" in md
    # Rate rows render as percentages with a percentage-point delta.
    assert "| Faithfulness | 100% | 90% | -10.0 pts |" in md
    assert "| Citation rate | 100% | 100% | +0.0 pts |" in md
    # Latency rows render in ms with a ms delta.
    assert "| Retrieval latency p50 | 67 ms | 120 ms | +53 ms |" in md
    # Counts section present.
    assert "## Counts" in md
    assert "Total cases" in md


def test_render_comparison_explicit_labels_override_provider():
    a = _metrics_dict("openai", 1.0, 67.0)
    b = _metrics_dict("groq", 0.9, 120.0)
    md = render_comparison(a, b, label_a="GPT-4o-mini", label_b="Llama-3.3-70B")
    assert "| Metric | GPT-4o-mini | Llama-3.3-70B | Delta (B - A) |" in md


def test_render_comparison_handles_missing_keys():
    md = render_comparison({"faithfulness_rate": 1.0}, {"faithfulness_rate": 0.5})
    assert "| Faithfulness | 100% | 50% | -50.0 pts |" in md
    # Absent metrics do not appear.
    assert "Citation rate" not in md


def test_render_comparison_empty_dicts():
    md = render_comparison({}, {})
    assert "_(no metrics)_" in md


def test_render_comparison_from_files_round_trips(tmp_path):
    a_path = tmp_path / "a.json"
    b_path = tmp_path / "b.json"
    a_path.write_text(json.dumps(_metrics_dict("openai", 1.0, 67.0)), encoding="utf-8")
    b_path.write_text(json.dumps(_metrics_dict("groq", 0.9, 120.0)), encoding="utf-8")
    md = render_comparison_from_files(a_path, b_path)
    assert "| Faithfulness | 100% | 90% | -10.0 pts |" in md


def test_write_comparison_creates_file(tmp_path):
    a = _metrics_dict("openai", 1.0, 67.0)
    b = _metrics_dict("groq", 0.9, 120.0)
    path = tmp_path / "nested" / "compare.md"
    write_comparison(a, b, path)
    assert path.exists()
    assert "# Benchmark comparison" in path.read_text(encoding="utf-8")


def test_compare_report_main_writes_file(tmp_path):
    from eval.compare_report import main as compare_main

    a_path = tmp_path / "a.json"
    b_path = tmp_path / "b.json"
    out_path = tmp_path / "compare.md"
    a_path.write_text(json.dumps(_metrics_dict("openai", 1.0, 67.0)), encoding="utf-8")
    b_path.write_text(json.dumps(_metrics_dict("groq", 0.9, 120.0)), encoding="utf-8")
    code = compare_main([str(a_path), str(b_path), "--out", str(out_path)])
    assert code == 0
    assert out_path.exists()
