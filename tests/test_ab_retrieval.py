"""Tests for the LLM-free A/B retrieval-quality harness.

Everything runs with stubs: the retriever is injected, so no Qdrant collection
or embedding model is loaded and no API call is made. The ranking metrics are
pure functions checked against hand-computed expected values.
"""

import math

from eval.ab_retrieval import (
    ABResult,
    ModeMetrics,
    dcg_at_k,
    format_summary,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    relevances_of,
    run_ab,
)
from eval.run_eval import EvalCase

# --- recall@k -------------------------------------------------------------


def test_recall_at_k_perfect_ranking():
    # Single relevant item at the top, within the cut-off -> all of it recovered.
    assert recall_at_k([1, 0, 0], 3) == 1.0


def test_recall_at_k_partial():
    # Three relevant overall, two of them fall within the top 3.
    assert recall_at_k([1, 0, 1, 0, 1], 3) == 2 / 3


def test_recall_at_k_no_relevant_is_zero():
    assert recall_at_k([0, 0, 0], 5) == 0.0


def test_recall_at_k_empty_is_zero():
    assert recall_at_k([], 5) == 0.0


def test_recall_at_k_non_positive_k_is_zero():
    assert recall_at_k([1, 1], 0) == 0.0


# --- reciprocal rank (MRR per query) --------------------------------------


def test_reciprocal_rank_first_position():
    assert reciprocal_rank([1, 0, 0]) == 1.0


def test_reciprocal_rank_third_position():
    assert reciprocal_rank([0, 0, 1]) == 1 / 3


def test_reciprocal_rank_no_relevant_is_zero():
    assert reciprocal_rank([0, 0, 0]) == 0.0


def test_reciprocal_rank_empty_is_zero():
    assert reciprocal_rank([]) == 0.0


# --- DCG / NDCG@k ---------------------------------------------------------


def test_dcg_at_k_known_value():
    # rel at ranks 1 and 3: 1/log2(2) + 1/log2(4) = 1 + 0.5 = 1.5
    assert dcg_at_k([1, 0, 1], 3) == 1.5


def test_dcg_at_k_non_positive_k_is_zero():
    assert dcg_at_k([1, 1], 0) == 0.0


def test_ndcg_at_k_perfect_ranking_is_one():
    # Relevant items already at the top -> DCG equals the ideal DCG.
    assert ndcg_at_k([1, 1, 0], 3) == 1.0


def test_ndcg_at_k_against_known_ideal():
    # Two relevant, placed at ranks 2 and 3.
    # DCG    = 1/log2(3) + 1/log2(4)
    # ideal  = 1/log2(2) + 1/log2(3)  (both relevant pushed to the top)
    dcg = 1 / math.log2(3) + 1 / math.log2(4)
    ideal = 1 / math.log2(2) + 1 / math.log2(3)
    assert ndcg_at_k([0, 1, 1], 3) == dcg / ideal


def test_ndcg_at_k_no_relevant_is_zero():
    assert ndcg_at_k([0, 0, 0], 3) == 0.0


def test_ndcg_at_k_empty_is_zero():
    assert ndcg_at_k([], 5) == 0.0


def test_ndcg_at_k_respects_cutoff():
    # Only relevant item sits beyond the cut-off -> nothing counted -> 0.
    assert ndcg_at_k([0, 0, 1], 2) == 0.0


# --- relevance derivation (same signal as run_eval.retrieval_hit) ---------


def test_relevances_of_marks_chunks_with_keywords():
    texts = [
        "A WAVELET transform is localized.",
        "unrelated filler chunk",
        "multiresolution analysis here",
    ]
    rels = relevances_of(texts, ["wavelet", "multiresolution"])
    assert rels == [1, 0, 1]


def test_relevances_of_no_keywords_is_all_zero():
    assert relevances_of(["anything", "else"], []) == [0, 0]


def test_relevances_of_empty_list():
    assert relevances_of([], ["wavelet"]) == []


# --- A/B aggregation over a stubbed dense-vs-hybrid retriever --------------


def _stub_retrieve(per_question: dict):
    """Build an injectable retriever from a per-question (dense, hybrid) map.

    ``per_question[question]`` is a ``(dense_texts, hybrid_texts)`` pair.
    """

    def retrieve(question: str, hybrid: bool):
        dense_texts, hybrid_texts = per_question[question]
        return hybrid_texts if hybrid else dense_texts

    return retrieve


def test_run_ab_skips_refusal_and_keywordless_cases():
    cases = [
        EvalCase("in", expect_refusal=False, expect_keywords=("haar",)),
        EvalCase("in-no-kw", expect_refusal=False),
        EvalCase("out", expect_refusal=True),
    ]
    retrieve = _stub_retrieve(
        {"in": (["a haar chunk"], ["a haar chunk"])},
    )
    result = run_ab(cases, retrieve, k=5)
    assert result.checked == 1


def test_run_ab_aggregates_means_and_deltas():
    # Two checkable cases. Hybrid ranks the relevant chunk higher than dense.
    cases = [
        EvalCase("q1", expect_refusal=False, expect_keywords=("haar",)),
        EvalCase("q2", expect_refusal=False, expect_keywords=("filter",)),
    ]
    per_question = {
        # q1: dense puts the relevant chunk at rank 3; hybrid at rank 1.
        "q1": (
            ["noise", "noise", "the haar wavelet"],
            ["the haar wavelet", "noise", "noise"],
        ),
        # q2: dense misses entirely; hybrid finds it at rank 1.
        "q2": (
            ["noise", "noise"],
            ["a filter bank", "noise"],
        ),
    }
    result = run_ab(cases, _stub_retrieve(per_question), k=5)

    assert result.checked == 2
    assert result.k == 5

    # Hit-rate: dense hits only q1 (1/2); hybrid hits both (2/2).
    assert result.dense_hits == 1
    assert result.hybrid_hits == 2
    assert result.dense.hit_rate == 1 / 2
    assert result.hybrid.hit_rate == 1.0
    # Legacy properties stay consistent.
    assert result.dense_hit_rate == 1 / 2
    assert result.hybrid_hit_rate == 1.0
    assert result.delta == 1 / 2

    # MRR. Dense: q1 -> 1/3, q2 -> 0 ; mean = 1/6. Hybrid: both 1.0 -> 1.0.
    assert result.dense.mrr == (1 / 3 + 0.0) / 2
    assert result.hybrid.mrr == 1.0

    # Recall@5. q1: one relevant of one -> 1.0 for both modes (rank 3 < 5).
    #           q2: dense 0.0, hybrid 1.0. Means: dense 1/2, hybrid 1.0.
    assert result.dense.recall_at_k == (1.0 + 0.0) / 2
    assert result.hybrid.recall_at_k == 1.0

    # NDCG@5. Dense q1: relevant at rank 3 -> DCG=1/log2(4), ideal=1/log2(2)=1
    #         -> 0.5 ; q2 -> 0. Mean = 0.25. Hybrid: both perfect -> 1.0.
    expected_dense_ndcg = ((1 / math.log2(4)) / 1.0 + 0.0) / 2
    assert result.dense.ndcg_at_k == expected_dense_ndcg
    assert result.hybrid.ndcg_at_k == 1.0

    # Deltas are hybrid minus dense, per metric.
    deltas = result.deltas
    assert deltas.hit_rate == 1 / 2
    assert deltas.mrr == 1.0 - (1 / 3) / 2
    assert deltas.recall_at_k == 1.0 - 0.5
    assert deltas.ndcg_at_k == 1.0 - expected_dense_ndcg


def test_run_ab_empty_checkable_is_all_zero():
    result = run_ab([EvalCase("out", expect_refusal=True)], _stub_retrieve({}), k=5)
    assert result.checked == 0
    assert result.dense == ModeMetrics()
    assert result.hybrid == ModeMetrics()
    # The legacy hit-rate properties stay vacuously perfect (1.0) when nothing
    # is checked, matching the prior behaviour.
    assert result.dense_hit_rate == 1.0
    assert result.hybrid_hit_rate == 1.0


# --- JSON shape and summary -----------------------------------------------


def test_to_dict_is_backward_compatible_and_enriched():
    result = ABResult(
        checked=2,
        dense_hits=1,
        hybrid_hits=2,
        k=5,
        dense=ModeMetrics(hit_rate=0.5, recall_at_k=0.5, mrr=0.25, ndcg_at_k=0.4),
        hybrid=ModeMetrics(hit_rate=1.0, recall_at_k=1.0, mrr=1.0, ndcg_at_k=1.0),
    )
    data = result.to_dict()
    # Legacy keys preserved for existing consumers.
    assert data["checked"] == 2
    assert data["dense_hits"] == 1
    assert data["hybrid_hits"] == 2
    assert data["dense_hit_rate"] == 0.5
    assert data["hybrid_hit_rate"] == 1.0
    assert data["delta"] == 0.5
    # New enriched keys.
    assert data["k"] == 5
    assert data["dense"] == {
        "hit_rate": 0.5,
        "recall_at_k": 0.5,
        "mrr": 0.25,
        "ndcg_at_k": 0.4,
    }
    assert data["hybrid"]["ndcg_at_k"] == 1.0
    assert data["deltas"]["recall_at_k"] == 0.5
    assert data["deltas"]["mrr"] == 0.75


def test_format_summary_mentions_all_metrics():
    result = ABResult(
        checked=2,
        dense_hits=1,
        hybrid_hits=2,
        k=5,
        dense=ModeMetrics(hit_rate=0.5, recall_at_k=0.5, mrr=0.25, ndcg_at_k=0.4),
        hybrid=ModeMetrics(hit_rate=1.0, recall_at_k=1.0, mrr=1.0, ndcg_at_k=1.0),
    )
    text = format_summary(result)
    assert "recall@5" in text
    assert "mrr" in text
    assert "ndcg@5" in text
    assert "hit-rate" in text
