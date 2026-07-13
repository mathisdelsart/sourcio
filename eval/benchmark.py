"""Provider benchmark harness over a course dataset (e.g. the Master Thesis).

This extends the offline faithfulness harness (:mod:`eval.run_eval`) with the
extra metrics a portfolio benchmark wants, and lets the whole pipeline
(retrieve -> answer -> judge) be pointed at any dataset and run against whatever
LLM the model-agnostic factory resolves from the environment. Running it once
with ``LLM_PROVIDER`` unset (or ``openai``) and once with ``LLM_PROVIDER=groq``
produces two metrics JSON files that :mod:`eval.compare_report` renders side by
side.

Metrics reported per run:

* **refusal accuracy** - refuse-cases refused and answer-cases answered;
* **faithfulness / relevance** - the existing LLM judge (judge #2);
* **citation rate** - answered answer-cases whose text carries a ``[n]`` marker
  (grounding by construction);
* **retrieval hit rate** - answer-cases whose retrieved chunks contain an
  expected keyword;
* **answer-keyword rate** - answered answer-cases whose *answer text* contains an
  expected keyword (a lightweight correctness signal);
* **retrieval latency p50/p95** - taken from the ``retrieval`` timer stage when
  ``LATENCY_ENABLED`` is set during the run.

Every collaborator (answer, judge, retrieve) is injectable, exactly like
:mod:`eval.run_eval`, so the harness unit-tests with fakes and makes no API call.
The real run against a paid provider is performed separately by the maintainer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from eval.run_eval import (
    AnswerFn,
    EvalCase,
    JudgeFn,
    RetrieveFn,
    _source_texts,
    parse_verdict,
    retrieval_hit,
)

DATASET_PATH = Path(__file__).with_name("dataset.jsonl")

# Matches an inline citation marker such as ``[1]`` or ``[12]``. A grounded
# answer produced by the citation-by-construction pipeline always carries at
# least one; its absence flags an ungrounded answer.
_CITATION_RE = re.compile(r"\[\d+\]")


def provider_label() -> str:
    """Return a human label for the LLM provider resolved from the environment.

    Mirrors :data:`core.config.Settings.llm_provider`: an empty value means the
    OpenAI default. Purely descriptive - it names the run in the output and the
    comparison report and never drives model selection.
    """
    return os.getenv("LLM_PROVIDER", "").strip().lower() or "openai"


@dataclass(frozen=True)
class BenchmarkCase:
    """One dataset case plus its coarse category (factual/math/synthesis/refuse).

    ``category`` is descriptive metadata carried in the JSONL; it is optional so
    the plain :class:`~eval.run_eval.EvalCase` loader still parses the same file.
    """

    case: EvalCase
    category: str = ""


@dataclass
class BenchmarkCaseResult:
    """Outcome of benchmarking a single case (superset of ``CaseResult``)."""

    question: str
    category: str
    expect_refusal: bool
    refused: bool
    # Judge verdicts, set only for answer-cases that produced an answer.
    faithful: bool | None = None
    relevant: bool | None = None
    # Retrieval surfaced an expected keyword (answer-cases with keywords only).
    retrieval_hit: bool | None = None
    # Answer text carries a [n] marker (answered answer-cases only).
    cited: bool | None = None
    # Answer text contains an expected keyword (answered answer-cases w/ kw).
    answer_keyword_hit: bool | None = None

    @property
    def refusal_correct(self) -> bool:
        """True if the refuse/answer decision matched the expectation."""
        return self.refused == self.expect_refusal


@dataclass
class BenchmarkMetrics:
    """Aggregated benchmark metrics for one provider run."""

    provider: str
    refusal_accuracy: float
    faithfulness_rate: float
    relevance_rate: float
    retrieval_hit_rate: float
    citation_rate: float
    answer_keyword_rate: float
    judged: int = 0
    total: int = 0
    retrieval_checked: int = 0
    cited_checked: int = 0
    answer_keyword_checked: int = 0
    # p50/p95 of the ``retrieval`` timer stage in ms; None when latency was not
    # recorded during the run (``LATENCY_ENABLED`` unset).
    retrieval_p50_ms: float | None = None
    retrieval_p95_ms: float | None = None
    failures: list[str] = field(default_factory=list)


def metrics_to_dict(metrics: BenchmarkMetrics) -> dict[str, Any]:
    """Return a plain JSON-serializable dict view of the metrics (pure)."""
    return asdict(metrics)


def write_results(metrics: BenchmarkMetrics, path: Path) -> None:
    """Write the aggregated metrics to ``path`` as a JSON object (creates dirs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics_to_dict(metrics), indent=2), encoding="utf-8")


def load_dataset(path: Path = DATASET_PATH) -> list[BenchmarkCase]:
    """Parse the benchmark JSONL into cases carrying their category.

    Reuses the exact :class:`~eval.run_eval.EvalCase` field schema and simply
    keeps the optional ``category`` alongside. Blank lines are ignored.
    """
    cases: list[BenchmarkCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        eval_case = EvalCase(
            question=obj["question"],
            expect_refusal=bool(obj["expect_refusal"]),
            note=obj.get("note", ""),
            expect_keywords=tuple(k.lower() for k in obj.get("expect_keywords", [])),
        )
        cases.append(BenchmarkCase(case=eval_case, category=obj.get("category", "")))
    return cases


def has_citation(answer_text: str) -> bool:
    """True if ``answer_text`` carries at least one ``[n]`` citation marker."""
    return _CITATION_RE.search(answer_text or "") is not None


def answer_keyword_hit(answer_text: str, expect_keywords: Sequence[str]) -> bool:
    """True if any expected keyword appears in the answer text (case-insensitive).

    Mirrors :func:`eval.run_eval.retrieval_hit` but matches against the produced
    answer rather than the retrieved chunks, giving a lightweight correctness
    signal. With no expected keywords there is nothing to find, so it is False.
    """
    if not expect_keywords:
        return False
    haystack = (answer_text or "").lower()
    return any(keyword.lower() in haystack for keyword in expect_keywords)


def evaluate(
    cases: Sequence[BenchmarkCase],
    answer_fn: AnswerFn,
    judge_fn: JudgeFn,
    retrieve_fn: RetrieveFn | None = None,
) -> list[BenchmarkCaseResult]:
    """Run every case through answer, judge (when answered) and the extra checks.

    Single pass over the cases so ``answer_fn`` (the paid step) is called exactly
    once per case. The judge sees the raw retrieved passages via
    :func:`eval.run_eval._source_texts`. All collaborators are injectable so tests
    pass fakes and no Qdrant, embedding model or API is touched.
    """
    results: list[BenchmarkCaseResult] = []
    for bc in cases:
        case = bc.case
        out = answer_fn(case.question)
        refused = bool(out.get("refused"))
        answer_text = out.get("answer", "")
        result = BenchmarkCaseResult(
            question=case.question,
            category=bc.category,
            expect_refusal=case.expect_refusal,
            refused=refused,
        )

        if not case.expect_refusal and not refused:
            sources = _source_texts(out)
            verdict = parse_verdict(judge_fn(case.question, answer_text, sources))
            result.faithful = verdict.faithful
            result.relevant = verdict.relevant
            result.cited = has_citation(answer_text)
            if case.expect_keywords:
                result.answer_keyword_hit = answer_keyword_hit(answer_text, case.expect_keywords)

        if retrieve_fn is not None and not case.expect_refusal and case.expect_keywords:
            texts = retrieve_fn(case.question)
            result.retrieval_hit = retrieval_hit(texts, case.expect_keywords)

        results.append(result)
    return results


def aggregate(
    results: Sequence[BenchmarkCaseResult],
    *,
    provider: str = "",
    retrieval_p50_ms: float | None = None,
    retrieval_p95_ms: float | None = None,
) -> BenchmarkMetrics:
    """Compute all benchmark rates from case results.

    Each rate is over the cases for which it is defined and is reported as 1.0
    (vacuously satisfied) when its denominator is empty:

    * refusal accuracy over all cases;
    * faithfulness / relevance over judged (answered answer-cases);
    * citation rate over answered answer-cases;
    * answer-keyword rate over answered answer-cases that declare keywords;
    * retrieval-hit rate over answer-cases whose retrieval was checked.
    """
    total = len(results)
    if total == 0:
        return BenchmarkMetrics(
            provider,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            retrieval_p50_ms=retrieval_p50_ms,
            retrieval_p95_ms=retrieval_p95_ms,
        )

    refusal_ok = sum(1 for r in results if r.refusal_correct)
    judged = [r for r in results if r.faithful is not None]
    faithful_ok = sum(1 for r in judged if r.faithful)
    relevant_ok = sum(1 for r in judged if r.relevant)
    cited = [r for r in results if r.cited is not None]
    cited_ok = sum(1 for r in cited if r.cited)
    kw = [r for r in results if r.answer_keyword_hit is not None]
    kw_ok = sum(1 for r in kw if r.answer_keyword_hit)
    retrieval_checked = [r for r in results if r.retrieval_hit is not None]
    retrieval_ok = sum(1 for r in retrieval_checked if r.retrieval_hit)

    failures: list[str] = []
    for r in results:
        if not r.refusal_correct:
            wanted = "refusal" if r.expect_refusal else "an answer"
            failures.append(f"expected {wanted}: {r.question!r}")
    for r in judged:
        if not r.faithful:
            failures.append(f"unfaithful answer: {r.question!r}")
        if not r.relevant:
            failures.append(f"irrelevant answer: {r.question!r}")
    for r in cited:
        if not r.cited:
            failures.append(f"uncited answer: {r.question!r}")
    for r in retrieval_checked:
        if not r.retrieval_hit:
            failures.append(f"no expected keyword retrieved: {r.question!r}")

    def rate(ok: int, denom: int) -> float:
        return ok / denom if denom else 1.0

    return BenchmarkMetrics(
        provider=provider,
        refusal_accuracy=refusal_ok / total,
        faithfulness_rate=rate(faithful_ok, len(judged)),
        relevance_rate=rate(relevant_ok, len(judged)),
        retrieval_hit_rate=rate(retrieval_ok, len(retrieval_checked)),
        citation_rate=rate(cited_ok, len(cited)),
        answer_keyword_rate=rate(kw_ok, len(kw)),
        judged=len(judged),
        total=total,
        retrieval_checked=len(retrieval_checked),
        cited_checked=len(cited),
        answer_keyword_checked=len(kw),
        retrieval_p50_ms=retrieval_p50_ms,
        retrieval_p95_ms=retrieval_p95_ms,
        failures=failures,
    )


def _retrieval_latency() -> tuple[float | None, float | None]:
    """Return (p50, p95) ms for the ``retrieval`` timer stage, or (None, None).

    Reads the process-wide samples recorded by :func:`core.obs.timer` during the
    run. Empty (latency disabled) yields ``(None, None)``.
    """
    from core.obs import get_samples, latency_stats

    for stat in latency_stats(get_samples()):
        if stat.stage == "retrieval":
            return stat.p50_ms, stat.p95_ms
    return None, None


def _default_answer_fn(course: str | None) -> AnswerFn:
    """Wire the real grounded answer function, imported lazily.

    ``course`` optionally scopes retrieval to a single course; None searches the
    whole collection (the offline path, ``owner=None``).
    """
    from core.answer import answer

    return lambda question: answer(question, course=course)


def _default_judge_fn() -> JudgeFn:
    """Wire the real faithfulness judge via the model-agnostic factory."""
    from eval.run_eval import _default_judge_fn as judge_fn

    return judge_fn()


def _default_retrieve_fn(course: str | None) -> RetrieveFn:
    """Wire the real retrieval step, imported lazily to keep CI import-light."""
    from core.retrieval import retrieve

    def fetch(question: str) -> list[str]:
        return [r.chunk.text for r in retrieve(question, course=course)]

    return fetch


def run_benchmark(
    *,
    dataset_path: Path = DATASET_PATH,
    course: str | None = None,
    provider: str | None = None,
    answer_fn: AnswerFn | None = None,
    judge_fn: JudgeFn | None = None,
    retrieve_fn: RetrieveFn | None = None,
) -> BenchmarkMetrics:
    """Run the benchmark and return the aggregated metrics for one provider.

    ``answer_fn``, ``judge_fn`` and ``retrieve_fn`` default to the real
    implementations but are injectable so tests pass fakes and avoid any API
    call or Qdrant/model load. ``provider`` defaults to :func:`provider_label`.
    """
    if provider is None:
        provider = provider_label()
    if answer_fn is None:
        answer_fn = _default_answer_fn(course)
    if judge_fn is None:
        judge_fn = _default_judge_fn()
    if retrieve_fn is None:
        retrieve_fn = _default_retrieve_fn(course)

    cases = load_dataset(dataset_path)
    results = evaluate(cases, answer_fn, judge_fn, retrieve_fn)
    p50, p95 = _retrieval_latency()
    return aggregate(results, provider=provider, retrieval_p50_ms=p50, retrieval_p95_ms=p95)


def format_summary(metrics: BenchmarkMetrics) -> str:
    """Render a human-readable summary of one benchmark run."""

    def latency(value: float | None) -> str:
        return f"{value:.0f} ms" if value is not None else "n/a"

    lines = [
        f"Benchmark summary ({metrics.provider})",
        f"  cases:              {metrics.total} ({metrics.judged} judged)",
        f"  refusal accuracy:   {metrics.refusal_accuracy:.0%}",
        f"  faithfulness:       {metrics.faithfulness_rate:.0%}",
        f"  relevance:          {metrics.relevance_rate:.0%}",
        f"  citation rate:      {metrics.citation_rate:.0%} ({metrics.cited_checked} answered)",
        f"  retrieval hit rate: {metrics.retrieval_hit_rate:.0%} "
        f"({metrics.retrieval_checked} checked)",
        f"  answer-keyword rate:{metrics.answer_keyword_rate:.0%} "
        f"({metrics.answer_keyword_checked} checked)",
        f"  retrieval latency:  p50 {latency(metrics.retrieval_p50_ms)} / "
        f"p95 {latency(metrics.retrieval_p95_ms)}",
    ]
    if metrics.failures:
        lines.append("  failures:")
        lines.extend(f"    - {f}" for f in metrics.failures)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Runs one provider and optionally writes artifacts.

    Always exits 0: this is an informative benchmark, not a CI gate.
    """
    parser = argparse.ArgumentParser(
        description="Run the provider benchmark over a course dataset."
    )
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument(
        "--course",
        default=None,
        help="Restrict retrieval to a single course; omit to search the whole collection.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Label for this run in the output/report; defaults to $LLM_PROVIDER (or openai).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the computed metrics to this JSON file (e.g. eval/bench-openai.json).",
    )
    parser.add_argument(
        "--latency-out",
        type=Path,
        default=None,
        help=(
            "Write per-stage latency p50/p95 to this JSON file. "
            "Only meaningful when LATENCY_ENABLED is set during the run."
        ),
    )
    args = parser.parse_args(argv)

    metrics = run_benchmark(dataset_path=args.dataset, course=args.course, provider=args.provider)
    print(format_summary(metrics))
    if args.out is not None:
        write_results(metrics, args.out)
        print(f"  wrote results: {args.out}")
    if args.latency_out is not None:
        from core.obs import get_samples, write_latency

        write_latency(get_samples(), args.latency_out)
        print(f"  wrote latency: {args.latency_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
