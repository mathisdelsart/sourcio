"""LLM-free A/B retrieval-quality harness: dense-only vs hybrid.

Measures retrieval quality for the in-course questions in
``eval/dataset.jsonl`` under two retrieval modes:

* ``dense``  -- the default dense-only path;
* ``hybrid`` -- dense + bge-m3 sparse (BM25-style) fused with RRF.

No LLM is involved. The ground-truth relevance signal is the *existing*
keyword criterion from ``run_eval.retrieval_hit``: a retrieved chunk is
"relevant" when it contains at least one of the case's ``expect_keywords``.
No new labels are invented -- the rank-aware metrics are built on that same
per-chunk signal.

For each in-course case the harness derives a per-rank binary relevance vector
for each mode and computes three standard ranking metrics on top of the
existing hit-rate:

* **Recall@k** -- share of the relevant chunks the retriever surfaced that fall
  within the top ``k`` (relative to the relevant chunks it surfaced at all,
  since no corpus-wide relevance labels exist);
* **MRR** -- reciprocal rank of the first relevant chunk (0 if none);
* **NDCG@k** -- DCG of the top ``k`` normalised by the ideal DCG, with binary
  gains and a log2 rank discount.

It reports the mean of each metric per mode plus the dense->hybrid delta. The
retriever is injectable so the math is unit tested offline with a stub; the
real numbers require a sparse-enabled Qdrant collection (ingested with
``--sparse``) -- see ``README`` / the module CLI help.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from eval.run_eval import DATASET_PATH, EvalCase, load_dataset, retrieval_hit

# A retriever returns the retrieved chunk texts for a question, in order. The
# bool flag selects the retrieval mode: True = hybrid, False = dense-only.
ABRetrieveFn = Callable[[str, bool], Sequence[str]]

# Default cut-off for the rank-aware metrics (Recall@k / NDCG@k).
DEFAULT_K = 5


# --- pure ranking-metric helpers (no I/O) ---------------------------------
# ``relevances`` is the per-rank relevance of the retrieved list, in order:
# a 1 (or truthy) at position i means the i-th retrieved chunk is relevant,
# 0 (or falsy) means it is not. Relevance is derived upstream from the same
# keyword criterion as ``run_eval.retrieval_hit`` -- no new labels.


def recall_at_k(relevances: Sequence[float], k: int) -> float:
    """Fraction of the relevant items that fall within the top ``k``.

    Binary set-based recall: ``(# relevant in top k) / (# relevant overall)``
    where "overall" means the relevant items the retriever actually surfaced in
    ``relevances`` (no corpus-wide relevance labels exist for this dataset).
    Returns 0.0 when ``k <= 0`` or when nothing relevant was retrieved.
    """
    total_relevant = sum(1 for r in relevances if r)
    if total_relevant == 0 or k <= 0:
        return 0.0
    found = sum(1 for r in relevances[:k] if r)
    return found / total_relevant


def reciprocal_rank(relevances: Sequence[float]) -> float:
    """Reciprocal rank of the first relevant item (``1/rank``), else 0.0.

    Averaged across queries this is the Mean Reciprocal Rank (MRR). Ranks are
    1-based, so a relevant item at the top yields 1.0.
    """
    for index, rel in enumerate(relevances, start=1):
        if rel:
            return 1.0 / index
    return 0.0


def dcg_at_k(relevances: Sequence[float], k: int) -> float:
    """Discounted cumulative gain over the top ``k`` with a log2 discount.

    Uses linear (binary) gains and the standard ``1 / log2(rank + 1)`` discount.
    Returns 0.0 when ``k <= 0``.
    """
    if k <= 0:
        return 0.0
    return sum(rel / math.log2(rank + 1) for rank, rel in enumerate(relevances[:k], start=1))


def ndcg_at_k(relevances: Sequence[float], k: int) -> float:
    """Normalised DCG over the top ``k`` (DCG divided by the ideal DCG).

    The ideal ranking places every relevant item first; with binary gains the
    ideal DCG is the DCG of ``min(k, #relevant)`` ones. Returns 0.0 when nothing
    relevant was retrieved (the ideal DCG is then 0) or when ``k <= 0``.
    """
    ideal = dcg_at_k(sorted(relevances, reverse=True), k)
    if ideal == 0.0:
        return 0.0
    return dcg_at_k(relevances, k) / ideal


def relevances_of(retrieved_texts: Sequence[str], expect_keywords: Sequence[str]) -> list[int]:
    """Per-rank binary relevance derived from the existing keyword criterion.

    A retrieved chunk is relevant (1) when it satisfies the same
    ``run_eval.retrieval_hit`` rule applied to that single chunk -- i.e. it
    contains at least one expected keyword -- and 0 otherwise. This is the only
    ground-truth signal; no new labels are introduced.
    """
    return [1 if retrieval_hit([text], expect_keywords) else 0 for text in retrieved_texts]


@dataclass
class ModeMetrics:
    """Mean rank-aware retrieval metrics for one mode over the checked cases.

    ``hit_rate`` is the existing keyword hit-rate (a case "hits" when any
    expected keyword appears in any retrieved chunk). ``recall_at_k``, ``mrr``
    and ``ndcg_at_k`` are the means of the per-case ranking metrics built on the
    same per-rank relevance signal. All default to 0.0 when no case is checked.
    """

    hit_rate: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    ndcg_at_k: float = 0.0

    def to_dict(self) -> dict:
        """Plain JSON-serializable view of the four mean metrics."""
        return asdict(self)


@dataclass
class ABResult:
    """A/B retrieval comparison over the in-course, keyworded cases.

    Carries the legacy hit counts (``dense_hits`` / ``hybrid_hits`` / ``checked``)
    for backward compatibility plus the richer per-mode rank-aware metrics
    (``dense`` / ``hybrid``) and the cut-off ``k`` they were computed at.
    """

    checked: int
    dense_hits: int
    hybrid_hits: int
    k: int = DEFAULT_K
    dense: ModeMetrics = field(default_factory=ModeMetrics)
    hybrid: ModeMetrics = field(default_factory=ModeMetrics)

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

    @property
    def deltas(self) -> ModeMetrics:
        """Per-metric hybrid-minus-dense delta (positive means hybrid helps)."""
        return ModeMetrics(
            hit_rate=self.hybrid.hit_rate - self.dense.hit_rate,
            recall_at_k=self.hybrid.recall_at_k - self.dense.recall_at_k,
            mrr=self.hybrid.mrr - self.dense.mrr,
            ndcg_at_k=self.hybrid.ndcg_at_k - self.dense.ndcg_at_k,
        )

    def to_dict(self) -> dict:
        """JSON-serializable view including the derived rates, metrics and deltas.

        The legacy keys (``checked``, ``dense_hits``, ``hybrid_hits``,
        ``dense_hit_rate``, ``hybrid_hit_rate``, ``delta``) are preserved so
        existing consumers keep working; the new ``k``, ``dense``/``hybrid``
        metric blocks and ``deltas`` are added alongside.
        """
        return {
            "checked": self.checked,
            "dense_hits": self.dense_hits,
            "hybrid_hits": self.hybrid_hits,
            "k": self.k,
            "dense_hit_rate": self.dense_hit_rate,
            "hybrid_hit_rate": self.hybrid_hit_rate,
            "delta": self.delta,
            "dense": self.dense.to_dict(),
            "hybrid": self.hybrid.to_dict(),
            "deltas": self.deltas.to_dict(),
        }


def _checkable(cases: Sequence[EvalCase]) -> list[EvalCase]:
    """Keep only in-course cases that declare expected keywords."""
    return [c for c in cases if not c.expect_refusal and c.expect_keywords]


def _mean(values: Sequence[float]) -> float:
    """Arithmetic mean, 0.0 for an empty sequence."""
    return sum(values) / len(values) if values else 0.0


def run_ab(cases: Sequence[EvalCase], retrieve_fn: ABRetrieveFn, k: int = DEFAULT_K) -> ABResult:
    """Compare dense vs hybrid retrieval over the keyworded cases.

    For each checkable case the retriever is called once per mode and the same
    per-chunk keyword relevance is derived for both, so the two modes are
    compared on identical ground truth. Beyond the legacy hit counts, the mean
    Recall@k, MRR and NDCG@k are aggregated per mode (alongside the keyword
    hit-rate) and exposed via :class:`ModeMetrics` and the dense->hybrid deltas.
    """
    checkable = _checkable(cases)
    dense_hits = 0
    hybrid_hits = 0
    dense_recall: list[float] = []
    dense_rr: list[float] = []
    dense_ndcg: list[float] = []
    hybrid_recall: list[float] = []
    hybrid_rr: list[float] = []
    hybrid_ndcg: list[float] = []

    for case in checkable:
        dense_rel = relevances_of(retrieve_fn(case.question, False), case.expect_keywords)
        hybrid_rel = relevances_of(retrieve_fn(case.question, True), case.expect_keywords)

        if any(dense_rel):
            dense_hits += 1
        if any(hybrid_rel):
            hybrid_hits += 1

        dense_recall.append(recall_at_k(dense_rel, k))
        dense_rr.append(reciprocal_rank(dense_rel))
        dense_ndcg.append(ndcg_at_k(dense_rel, k))
        hybrid_recall.append(recall_at_k(hybrid_rel, k))
        hybrid_rr.append(reciprocal_rank(hybrid_rel))
        hybrid_ndcg.append(ndcg_at_k(hybrid_rel, k))

    n = len(checkable)
    dense = ModeMetrics(
        hit_rate=dense_hits / n if n else 0.0,
        recall_at_k=_mean(dense_recall),
        mrr=_mean(dense_rr),
        ndcg_at_k=_mean(dense_ndcg),
    )
    hybrid = ModeMetrics(
        hit_rate=hybrid_hits / n if n else 0.0,
        recall_at_k=_mean(hybrid_recall),
        mrr=_mean(hybrid_rr),
        ndcg_at_k=_mean(hybrid_ndcg),
    )
    return ABResult(
        checked=n,
        dense_hits=dense_hits,
        hybrid_hits=hybrid_hits,
        k=k,
        dense=dense,
        hybrid=hybrid,
    )


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
    """Render a human-readable A/B summary of all four metrics per mode."""
    k = result.k

    def row(label: str, dense_v: float, hybrid_v: float, delta_v: float) -> str:
        return (
            f"  {label:<13} dense {dense_v:6.1%}   hybrid {hybrid_v:6.1%}   delta {delta_v:+6.1%}"
        )

    d, h, delta = result.dense, result.hybrid, result.deltas
    return "\n".join(
        [
            "A/B retrieval quality (dense vs hybrid)",
            f"  cases checked: {result.checked} (k={k})",
            f"  hit-rate:      dense {result.dense_hit_rate:6.1%}   "
            f"hybrid {result.hybrid_hit_rate:6.1%}   delta {result.delta:+6.1%}",
            row(f"recall@{k}:", d.recall_at_k, h.recall_at_k, delta.recall_at_k),
            row("mrr:", d.mrr, h.mrr, delta.mrr),
            row(f"ndcg@{k}:", d.ndcg_at_k, h.ndcg_at_k, delta.ndcg_at_k),
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Requires a Qdrant collection ingested with ``--sparse`` for the hybrid mode
    to differ from dense; against a dense-only collection hybrid falls back to
    dense and the delta is zero (documented, not a failure).
    """
    parser = argparse.ArgumentParser(
        description=(
            "LLM-free A/B retrieval quality (hit-rate, Recall@k, MRR, NDCG@k): "
            "dense-only vs hybrid (RRF)."
        )
    )
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument(
        "--k",
        type=int,
        default=DEFAULT_K,
        help=f"Rank cut-off for Recall@k and NDCG@k (default {DEFAULT_K}).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the A/B result to this JSON file (e.g. eval/ab_retrieval.json).",
    )
    args = parser.parse_args(argv)

    cases = load_dataset(args.dataset)
    result = run_ab(cases, _default_retrieve_fn(), k=args.k)
    print(format_summary(result))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        print(f"  wrote results: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
