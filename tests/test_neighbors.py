"""Tests for opt-in neighbor-chunk context expansion in retrieval.

No API calls and no real embedding model: ``embed_query`` is stubbed to a dummy
vector and the Qdrant client is replaced by a fake that records both the
``query_points`` kwargs (the ranked retrieval) and the ``scroll`` kwargs (the
neighbor fetch), returning canned points/records.
"""

from types import SimpleNamespace

import pytest
from qdrant_client.models import Filter, Range

import core.retrieval as retrieval


def _point(point_id, score, text, *, course="Wavelet Transform", chapter="Intro", page=11):
    return SimpleNamespace(
        id=point_id,
        score=score,
        payload={"course": course, "chapter": chapter, "page": page, "text": text},
    )


def _record(point_id, text, *, course="Wavelet Transform", chapter="Intro", page=10):
    """A scroll record: payload only, no score."""
    return SimpleNamespace(
        id=point_id,
        payload={"course": course, "chapter": chapter, "page": page, "text": text},
    )


class _FakeQdrantClient:
    """Captures query_points and scroll kwargs and returns canned data."""

    last_kwargs: dict | None = None
    scroll_calls: list[dict] = []
    points: list = [_point("p1", 0.91, "the chunk text")]
    # Records returned by each scroll call (one per retrieved result).
    scroll_records: list = []
    # When set, scroll raises to exercise the error-degradation path.
    scroll_raises: bool = False
    has_sparse: bool = False

    def __init__(self, *args, **kwargs):
        pass

    def query_points(self, **kwargs):
        _FakeQdrantClient.last_kwargs = kwargs
        return SimpleNamespace(points=list(_FakeQdrantClient.points))

    def scroll(self, **kwargs):
        _FakeQdrantClient.scroll_calls.append(kwargs)
        if _FakeQdrantClient.scroll_raises:
            raise RuntimeError("qdrant unavailable")
        return list(_FakeQdrantClient.scroll_records), None

    def get_collection(self, name):
        sparse = {"sparse": object()} if _FakeQdrantClient.has_sparse else {}
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(sparse_vectors=sparse))
        )


@pytest.fixture(autouse=True)
def _no_model_no_network(monkeypatch):
    _FakeQdrantClient.last_kwargs = None
    _FakeQdrantClient.scroll_calls = []
    _FakeQdrantClient.points = [_point("p1", 0.91, "the chunk text")]
    _FakeQdrantClient.scroll_records = []
    _FakeQdrantClient.scroll_raises = False
    _FakeQdrantClient.has_sparse = False
    monkeypatch.setattr(retrieval, "embed_query", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr("qdrant_client.QdrantClient", _FakeQdrantClient)


def _set_settings(monkeypatch, **overrides):
    """Override the settings seen by retrieval without loading real ones."""
    base = {
        "qdrant_url": "http://localhost:6333",
        "qdrant_api_key": None,
        "qdrant_collection": "courses",
        "similarity_threshold": 0.5,
        "reranker_model": "",
        "rerank_candidates": 20,
        "hybrid_retrieval": False,
        "sparse_vector_name": "sparse",
        "hybrid_prefetch": 50,
        "neighbor_expansion": False,
        "neighbor_window": 1,
    }
    base.update(overrides)
    settings = SimpleNamespace(**base)
    monkeypatch.setattr(retrieval, "get_settings", lambda: settings)
    return settings


# --- Default OFF: byte-identical, no extra calls ---------------------------


def test_disabled_by_default_issues_no_scroll(monkeypatch):
    _set_settings(monkeypatch, neighbor_expansion=False)
    results = retrieval.retrieve("q")
    assert _FakeQdrantClient.scroll_calls == []
    # Behavior byte-identical to the plain dense path: only the ranked hit.
    assert [r.chunk.id for r in results] == ["p1"]
    assert results[0].score == 0.91


def test_explicit_opt_out_overrides_settings(monkeypatch):
    # Settings say expand, but the caller forces it off -> no scroll.
    _set_settings(monkeypatch, neighbor_expansion=True)
    results = retrieval.retrieve("q", expand_neighbors=False)
    assert _FakeQdrantClient.scroll_calls == []
    assert [r.chunk.id for r in results] == ["p1"]


# --- ON: neighbors fetched via course+page-range filter, merged after ------


def test_neighbors_fetched_with_course_and_page_range_filter(monkeypatch):
    _set_settings(monkeypatch, neighbor_expansion=True, neighbor_window=1)
    _FakeQdrantClient.points = [_point("p1", 0.91, "hit", page=11)]
    _FakeQdrantClient.scroll_records = [
        _record("n1", "before", page=10),
        _record("n2", "after", page=12),
    ]
    results = retrieval.retrieve("q")

    # One scroll issued for the single retrieved result.
    assert len(_FakeQdrantClient.scroll_calls) == 1
    flt = _FakeQdrantClient.scroll_calls[0]["scroll_filter"]
    assert isinstance(flt, Filter)
    # course match + page range in must.
    course_conds = {c.key for c in flt.must if c.match is not None}
    assert "course" in course_conds
    assert any(c.key == "chapter" for c in flt.must if c.match is not None)
    page_conds = [c for c in flt.must if getattr(c, "range", None) is not None]
    assert len(page_conds) == 1
    rng = page_conds[0].range
    assert isinstance(rng, Range)
    assert rng.gte == 10 and rng.lte == 12
    # The page itself is excluded via must_not.
    assert flt.must_not is not None
    assert any(c.key == "page" and c.match.value == 11 for c in flt.must_not)

    # Originals first, then neighbors appended after, in order.
    assert [r.chunk.id for r in results] == ["p1", "n1", "n2"]
    # Neighbors carry no similarity score (context, not matches).
    assert results[1].score == 0.0 and results[2].score == 0.0


def test_neighbors_deduped_against_originals_and_each_other(monkeypatch):
    _set_settings(monkeypatch, neighbor_expansion=True, neighbor_window=2)
    _FakeQdrantClient.points = [
        _point("p1", 0.91, "hit a", page=11),
        _point("p2", 0.80, "hit b", page=12),
    ]
    # Both scroll calls return the same records, including one that duplicates an
    # original (p1) and one duplicated across the two calls (n1).
    _FakeQdrantClient.scroll_records = [
        _record("p1", "dup-of-original", page=11),
        _record("n1", "neighbor", page=13),
    ]
    results = retrieval.retrieve("q")
    ids = [r.chunk.id for r in results]
    # Originals kept first and in order; n1 appears exactly once; p1 not repeated.
    assert ids == ["p1", "p2", "n1"]


def test_neighbors_capped_in_total(monkeypatch):
    _set_settings(monkeypatch, neighbor_expansion=True, neighbor_window=1)
    _FakeQdrantClient.points = [_point("p1", 0.91, "hit", page=11)]
    # More candidate neighbors than the cap.
    _FakeQdrantClient.scroll_records = [
        _record(f"n{i}", f"text {i}", page=10) for i in range(retrieval._MAX_NEIGHBORS + 5)
    ]
    results = retrieval.retrieve("q")
    neighbors = [r for r in results if r.score == 0.0]
    assert len(neighbors) == retrieval._MAX_NEIGHBORS
    # The scroll limit is bounded by the remaining cap on the first call.
    assert _FakeQdrantClient.scroll_calls[0]["limit"] == retrieval._MAX_NEIGHBORS


# --- Refusal preserved: empty retrieval never expands ----------------------


def test_empty_retrieval_returns_refusal_and_does_not_expand(monkeypatch):
    _set_settings(monkeypatch, neighbor_expansion=True)
    _FakeQdrantClient.points = []  # out-of-course: nothing clears the threshold
    results = retrieval.retrieve("q")
    assert results == []
    # No neighbor fetch attempted on an empty (refused) retrieval.
    assert _FakeQdrantClient.scroll_calls == []


# --- Resilience: a neighbor-fetch error degrades to un-expanded results -----


def test_neighbor_fetch_error_returns_unexpanded(monkeypatch):
    _set_settings(monkeypatch, neighbor_expansion=True)
    _FakeQdrantClient.points = [_point("p1", 0.91, "hit", page=11)]
    _FakeQdrantClient.scroll_raises = True
    results = retrieval.retrieve("q")
    # The ranked result is returned intact; the error never propagates.
    assert [r.chunk.id for r in results] == ["p1"]
    assert results[0].score == 0.91


# --- Composes with reranking (expansion runs after rerank truncates to k) ---


def test_expansion_runs_after_reranking(monkeypatch):
    _set_settings(
        monkeypatch, neighbor_expansion=True, reranker_model="fake-model", rerank_candidates=20
    )
    _FakeQdrantClient.points = [
        _point("p1", 0.91, "alpha", page=11),
        _point("p2", 0.80, "bravo", page=20),
    ]
    _FakeQdrantClient.scroll_records = [_record("n1", "neighbor", page=21)]
    fake_scores = {"alpha": 0.1, "bravo": 0.9}
    results = retrieval.retrieve(
        "q", k=1, scorer=lambda question, texts: [fake_scores[t] for t in texts]
    )
    # Reranker keeps only bravo (k=1); expansion then runs on that single result.
    assert [r.chunk.id for r in results] == ["p2", "n1"]
    assert len(_FakeQdrantClient.scroll_calls) == 1


def test_chapterless_result_omits_chapter_condition(monkeypatch):
    _set_settings(monkeypatch, neighbor_expansion=True, neighbor_window=1)
    _FakeQdrantClient.points = [
        SimpleNamespace(
            id="p1",
            score=0.91,
            payload={"course": "C", "chapter": None, "page": 5, "text": "hit"},
        )
    ]
    _FakeQdrantClient.scroll_records = [_record("n1", "n", course="C", chapter=None, page=4)]
    retrieval.retrieve("q")
    flt = _FakeQdrantClient.scroll_calls[0]["scroll_filter"]
    # No chapter condition when the result has no chapter.
    assert not any(c.key == "chapter" for c in flt.must if c.match is not None)
