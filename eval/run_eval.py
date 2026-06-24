"""System evaluation harness: faithfulness and relevance ("judge #2").

Runs offline / in CI, not on every user request. This is the system-quality
guard against hallucination, distinct from the product-side grading of a
student's answer.

For each reference question in ``eval/dataset.jsonl``:

* call the answer function;
* if the entry expects a refusal, check that the system refused;
* otherwise ask a faithfulness judge whether the produced answer is fully
  supported by the retrieved sources and whether it is relevant to the question.

The aggregated metrics (refusal accuracy, faithfulness rate, relevance rate)
are printed and compared against configurable thresholds, so CI can fail the
build on a regression.

The answer function and the judge are injectable so the harness can be unit
tested without any API call. The default wiring uses the real ``answer.answer``
and ``config.get_llm("judge")``; tests pass fakes instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

DATASET_PATH = Path(__file__).with_name("dataset.jsonl")

# Default pass thresholds. The build fails if any metric drops below these.
DEFAULT_REFUSAL_ACCURACY = 1.0
DEFAULT_FAITHFULNESS_RATE = 1.0
DEFAULT_RELEVANCE_RATE = 1.0

# Types injected by tests or wired to real implementations by default.
AnswerFn = Callable[[str], dict]
JudgeFn = Callable[[str, str, Sequence[str]], object]

_JUDGE_SYSTEM = (
    "You are a strict evaluator of a course tutor's answer.\n"
    "You are given a question, the tutor's answer, and the numbered source "
    "passages the tutor was allowed to use.\n"
    "Decide two things:\n"
    "- faithful: true only if every claim in the answer is fully supported by "
    "the sources, with no outside knowledge and no contradiction.\n"
    "- relevant: true only if the answer actually addresses the question.\n"
    'Reply with a single JSON object: {"faithful": <bool>, "relevant": <bool>}.'
)


@dataclass(frozen=True)
class EvalCase:
    """One reference question from the dataset."""

    question: str
    expect_refusal: bool
    note: str = ""


@dataclass
class CaseResult:
    """Outcome of evaluating a single case."""

    question: str
    expect_refusal: bool
    refused: bool
    # The two judge verdicts are only set for answerable (non-refusal) cases
    # that were actually answered; they stay None otherwise.
    faithful: bool | None = None
    relevant: bool | None = None

    @property
    def refusal_correct(self) -> bool:
        """True if the system's refuse/answer decision matched the expectation."""
        return self.refused == self.expect_refusal


@dataclass
class Verdict:
    """A judge's decision about a single answer."""

    faithful: bool
    relevant: bool


@dataclass
class Metrics:
    """Aggregated evaluation metrics over all cases."""

    refusal_accuracy: float
    faithfulness_rate: float
    relevance_rate: float
    judged: int = 0
    total: int = 0
    failures: list[str] = field(default_factory=list)


def load_dataset(path: Path = DATASET_PATH) -> list[EvalCase]:
    """Parse the JSONL dataset into evaluation cases.

    Blank lines are ignored so the file can be edited freely.
    """
    cases: list[EvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        cases.append(
            EvalCase(
                question=obj["question"],
                expect_refusal=bool(obj["expect_refusal"]),
                note=obj.get("note", ""),
            )
        )
    return cases


def parse_verdict(raw: object) -> Verdict:
    """Parse a judge response into a :class:`Verdict`.

    Accepts a chat-model message (with a ``.content`` attribute), a raw string,
    or a mapping. The JSON object may be wrapped in surrounding text or a
    Markdown code fence; the first ``{...}`` block is used.
    """
    if isinstance(raw, dict):
        obj = raw
    else:
        text = getattr(raw, "content", raw)
        if not isinstance(text, str):
            raise ValueError(f"Cannot parse judge verdict from {type(raw)!r}")
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in judge output: {text!r}")
        obj = json.loads(match.group(0))

    return Verdict(faithful=bool(obj["faithful"]), relevant=bool(obj["relevant"]))


def aggregate(results: Sequence[CaseResult]) -> Metrics:
    """Compute refusal accuracy, faithfulness and relevance from case results.

    * refusal accuracy is over all cases (did refuse/answer match expectation?);
    * faithfulness and relevance are over the cases that were actually judged
      (answerable cases that produced an answer). With no judged case, both
      rates are reported as 1.0 (vacuously satisfied).
    """
    total = len(results)
    if total == 0:
        return Metrics(1.0, 1.0, 1.0, judged=0, total=0)

    refusal_ok = sum(1 for r in results if r.refusal_correct)
    judged = [r for r in results if r.faithful is not None]
    faithful_ok = sum(1 for r in judged if r.faithful)
    relevant_ok = sum(1 for r in judged if r.relevant)

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

    n_judged = len(judged)
    return Metrics(
        refusal_accuracy=refusal_ok / total,
        faithfulness_rate=faithful_ok / n_judged if n_judged else 1.0,
        relevance_rate=relevant_ok / n_judged if n_judged else 1.0,
        judged=n_judged,
        total=total,
        failures=failures,
    )


def _default_answer_fn() -> AnswerFn:
    """Wire the real grounded answer function, imported lazily.

    Importing inside the function keeps this module importable in CI (dev-only
    sync) without pulling retrieval/embedding dependencies at import time.
    """
    from answer import answer

    return lambda question: answer(question)


def _default_judge_fn() -> JudgeFn:
    """Wire the real faithfulness judge via the model-agnostic factory."""
    from config import get_llm

    llm = get_llm("judge")

    def judge(question: str, answer_text: str, sources: Sequence[str]) -> object:
        numbered = "\n\n".join(f"[{i}] {s}" for i, s in enumerate(sources, 1))
        prompt = (
            f"Question: {question}\n\nAnswer: {answer_text}\n\nSources:\n{numbered or '(none)'}"
        )
        return llm.invoke([("system", _JUDGE_SYSTEM), ("human", prompt)])

    return judge


def evaluate(
    cases: Sequence[EvalCase],
    answer_fn: AnswerFn,
    judge_fn: JudgeFn,
) -> list[CaseResult]:
    """Run every case through the answer function and, when answered, the judge.

    The judge receives the raw retrieved source texts, not the citation labels,
    so it can check support claim by claim.
    """
    results: list[CaseResult] = []
    for case in cases:
        out = answer_fn(case.question)
        refused = bool(out.get("refused"))
        result = CaseResult(
            question=case.question,
            expect_refusal=case.expect_refusal,
            refused=refused,
        )

        # Only judge cases meant to be answered that produced an answer.
        if not case.expect_refusal and not refused:
            sources = _source_texts(out)
            verdict = parse_verdict(judge_fn(case.question, out.get("answer", ""), sources))
            result.faithful = verdict.faithful
            result.relevant = verdict.relevant

        results.append(result)
    return results


def _source_texts(out: dict) -> list[str]:
    """Best-effort extraction of the source texts behind an answer.

    Prefers the retrieved chunk texts when present; falls back to the citation
    labels exposed in ``sources``.
    """
    retrieved = out.get("retrieved")
    if retrieved:
        texts: list[str] = []
        for r in retrieved:
            chunk = getattr(r, "chunk", None)
            texts.append(getattr(chunk, "text", "") if chunk is not None else str(r))
        return texts
    return list(out.get("sources", []))


def passed(metrics: Metrics, thresholds: Metrics) -> bool:
    """Return True if every metric meets or exceeds its threshold."""
    return (
        metrics.refusal_accuracy >= thresholds.refusal_accuracy
        and metrics.faithfulness_rate >= thresholds.faithfulness_rate
        and metrics.relevance_rate >= thresholds.relevance_rate
    )


def format_summary(metrics: Metrics, thresholds: Metrics, ok: bool) -> str:
    """Render a human-readable summary of the run."""
    lines = [
        "Faithfulness evaluation summary",
        f"  cases:            {metrics.total} ({metrics.judged} judged)",
        f"  refusal accuracy: {metrics.refusal_accuracy:.0%} "
        f"(threshold {thresholds.refusal_accuracy:.0%})",
        f"  faithfulness:     {metrics.faithfulness_rate:.0%} "
        f"(threshold {thresholds.faithfulness_rate:.0%})",
        f"  relevance:        {metrics.relevance_rate:.0%} "
        f"(threshold {thresholds.relevance_rate:.0%})",
    ]
    if metrics.failures:
        lines.append("  failures:")
        lines.extend(f"    - {f}" for f in metrics.failures)
    lines.append(f"  result: {'PASS' if ok else 'FAIL'}")
    return "\n".join(lines)


def run_eval(
    *,
    dataset_path: Path = DATASET_PATH,
    answer_fn: AnswerFn | None = None,
    judge_fn: JudgeFn | None = None,
    thresholds: Metrics | None = None,
) -> tuple[Metrics, bool]:
    """Run the full evaluation and return the metrics and the pass/fail flag.

    ``answer_fn`` and ``judge_fn`` default to the real implementations but are
    injectable so tests can pass fakes and avoid any API call.
    """
    if thresholds is None:
        thresholds = Metrics(
            DEFAULT_REFUSAL_ACCURACY,
            DEFAULT_FAITHFULNESS_RATE,
            DEFAULT_RELEVANCE_RATE,
        )
    if answer_fn is None:
        answer_fn = _default_answer_fn()
    if judge_fn is None:
        judge_fn = _default_judge_fn()

    cases = load_dataset(dataset_path)
    results = evaluate(cases, answer_fn, judge_fn)
    metrics = aggregate(results)
    ok = passed(metrics, thresholds)
    return metrics, ok


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Exits non-zero when a metric falls below threshold."""
    parser = argparse.ArgumentParser(description="Run the offline faithfulness evaluation.")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--min-refusal-accuracy", type=float, default=DEFAULT_REFUSAL_ACCURACY)
    parser.add_argument("--min-faithfulness", type=float, default=DEFAULT_FAITHFULNESS_RATE)
    parser.add_argument("--min-relevance", type=float, default=DEFAULT_RELEVANCE_RATE)
    args = parser.parse_args(argv)

    thresholds = Metrics(
        refusal_accuracy=args.min_refusal_accuracy,
        faithfulness_rate=args.min_faithfulness,
        relevance_rate=args.min_relevance,
    )
    metrics, ok = run_eval(dataset_path=args.dataset, thresholds=thresholds)
    print(format_summary(metrics, thresholds, ok))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
