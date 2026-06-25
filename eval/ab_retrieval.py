"""LLM-free A/B retrieval-hit-rate harness: dense-only vs hybrid.

Measures how often retrieval surfaces an expected keyword for the in-course
questions in ``eval/dataset.jsonl``, under two retrieval modes:

* ``dense``  -- the default dense-only path;
* ``hybrid`` -- dense + bge-m3 sparse (BM25-style) fused with RRF.

No LLM is involved: it only reuses the existing keyword-based
``retrieval_hit`` logic from ``run_eval`` and runs it under each mode, reporting
both hit-rates and their delta. The retriever is injectable so the math is unit
tested offline with a stub; the real numbers require a sparse-enabled Qdrant
collection (ingested with ``--sparse``) -- see ``README`` / the module CLI help.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from eval.run_eval import DATASET_PATH, EvalCase, load_dataset, retrieval_hit

# A retriever returns the retrieved chunk texts for a question, in order. The
# bool flag selects the retrieval mode: True = hybrid, False = dense-only.
ABRetrieveFn = Callable[[str, bool], Sequence[str]]


@dataclass
class ABResult:
    """A/B retrieval-hit comparison over the in-course, keyworded cases."""

    checked: int
    dense_hits: int
    hybrid_hits: int

    @property
    def dense_hit_rate(self) -> float:
        """Dense-only hit-rate (1.0 when no case is checked)."""
        return self.dense_hits / self.checked if self.checked else 1.0

    @property
    def hybrid_hit_rate(self) -> float:
        """Hybrid hit-rate (1.0 when no case is checked)."""
        return self.hybrid_hits / self.checked if self.checked else 1.0

    @property
    def delta(self) -> float:
        """Hybrid minus dense hit-rate (positive means hybrid helps)."""
        return self.hybrid_hit_rate - self.dense_hit_rate

    def to_dict(self) -> dict:
        """JSON-serializable view including the derived rates and delta."""
        data = asdict(self)
        data.update(
            dense_hit_rate=self.dense_hit_rate,
            hybrid_hit_rate=self.hybrid_hit_rate,
            delta=self.delta,
        )
        return data


def _checkable(cases: Sequence[EvalCase]) -> list[EvalCase]:
    """Keep only in-course cases that declare expected keywords."""
    return [c for c in cases if not c.expect_refusal and c.expect_keywords]


def run_ab(cases: Sequence[EvalCase], retrieve_fn: ABRetrieveFn) -> ABResult:
    """Compute dense vs hybrid retrieval hit counts over the keyworded cases.

    For each checkable case the retriever is called once per mode and the same
    keyword-substring ``retrieval_hit`` rule is applied, so the two modes are
    compared on identical ground truth.
    """
    checkable = _checkable(cases)
    dense_hits = 0
    hybrid_hits = 0
    for case in checkable:
        if retrieval_hit(retrieve_fn(case.question, False), case.expect_keywords):
            dense_hits += 1
        if retrieval_hit(retrieve_fn(case.question, True), case.expect_keywords):
            hybrid_hits += 1
    return ABResult(checked=len(checkable), dense_hits=dense_hits, hybrid_hits=hybrid_hits)


def _default_retrieve_fn() -> ABRetrieveFn:
    """Wire the real retrieval step under both modes, imported lazily.

    The hybrid toggle is threaded through the ``HYBRID_RETRIEVAL`` setting by
    rebuilding cached settings per mode, so a single process can A/B both paths
    without restarting. Importing inside the function keeps this module
    import-light (no Qdrant/embedding load) for the unit tests.
    """
    import os

    from core.config import get_settings
    from core.retrieval import retrieve

    def fetch(question: str, hybrid: bool) -> list[str]:
        os.environ["HYBRID_RETRIEVAL"] = "1" if hybrid else "0"
        get_settings.cache_clear()
        return [r.chunk.text for r in retrieve(question)]

    return fetch


def format_summary(result: ABResult) -> str:
    """Render a human-readable A/B summary."""
    return "\n".join(
        [
            "A/B retrieval-hit-rate (dense vs hybrid)",
            f"  cases checked: {result.checked}",
            f"  dense:         {result.dense_hit_rate:.0%} ({result.dense_hits}/{result.checked})",
            f"  hybrid:        {result.hybrid_hit_rate:.0%} "
            f"({result.hybrid_hits}/{result.checked})",
            f"  delta:         {result.delta:+.0%}",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Requires a Qdrant collection ingested with ``--sparse`` for the hybrid mode
    to differ from dense; against a dense-only collection hybrid falls back to
    dense and the delta is zero (documented, not a failure).
    """
    parser = argparse.ArgumentParser(
        description="LLM-free A/B retrieval-hit-rate: dense-only vs hybrid (RRF)."
    )
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the A/B result to this JSON file (e.g. eval/ab_retrieval.json).",
    )
    args = parser.parse_args(argv)

    cases = load_dataset(args.dataset)
    result = run_ab(cases, _default_retrieve_fn())
    print(format_summary(result))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        print(f"  wrote results: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
