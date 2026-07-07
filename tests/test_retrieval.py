"""Tests for course/chapter filtering in retrieval.

No API calls and no real embedding model: ``embed_query`` is stubbed to a dummy
vector and the Qdrant client is replaced by a fake that records the filter it
was given and returns canned points.
"""

from types import SimpleNamespace

import pytest
from qdrant_client.models import Filter

import core.retrieval as retrieval


def _point(point_id, score, text, *, course="Wavelet Transform", chapter="Intro", page=11):
    return SimpleNamespace(
        id=point_id,
        score=score,
        payload={"course": course, "chapter": chapter, "page": page, "text": text},
    )


class _FakeQdrantClient:
    """Captures query_points kwargs and returns canned points."""

    last_kwargs: dict | None = None
    points: list = [_point("p1", 0.91, "the chunk text")]
    # Whether get_collection reports a named sparse vector (hybrid availability).
    has_sparse: bool = False

    def __init__(self, *args, **kwargs):
        pass

    def query_points(self, **kwargs):
        _FakeQdrantClient.last_kwargs = kwargs
        return SimpleNamespace(points=list(_FakeQdrantClient.points))

    def get_collection(self, name):
        sparse = {"sparse": object()} if _FakeQdrantClient.has_sparse else {}
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(sparse_vectors=sparse))
        )


@pytest.fixture(autouse=True)
def _no_model_no_network(monkeypatch):
    _FakeQdrantClient.last_kwargs = None
    _FakeQdrantClient.points = [_point("p1", 0.91, "the chunk text")]
    _FakeQdrantClient.has_sparse = False
    # Never load the real embedding model (dense or sparse).
    monkeypatch.setattr(retrieval, "embed_query", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(
        "ingestion.embed.embed_sparse_query",
        lambda text: retrieval.SparseVector(indices=[1, 2], values=[0.5, 0.7]),
    )
    # Never reach a real Qdrant server.
    monkeypatch.setattr(retrieval, "QdrantClient", _FakeQdrantClient)


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


def test_no_filter_when_course_and_chapter_none():
    retrieval.retrieve("what is a wavelet?")
    assert _FakeQdrantClient.last_kwargs["query_filter"] is None


def test_course_filter_built_when_course_given():
    retrieval.retrieve("q", course="Wavelet Transform")
    flt = _FakeQdrantClient.last_kwargs["query_filter"]
    assert isinstance(flt, Filter)
    assert len(flt.must) == 1
    cond = flt.must[0]
    assert cond.key == "course"
    assert cond.match.value == "Wavelet Transform"


def test_combined_course_and_chapter_filter():
    retrieval.retrieve("q", course="Wavelet Transform", chapter="Intro")
    flt = _FakeQdrantClient.last_kwargs["query_filter"]
    assert isinstance(flt, Filter)
    keys = {(c.key, c.match.value) for c in flt.must}
    assert keys == {("course", "Wavelet Transform"), ("chapter", "Intro")}


def test_chapter_only_filter():
    retrieval.retrieve("q", chapter="Intro")
    flt = _FakeQdrantClient.last_kwargs["query_filter"]
    assert isinstance(flt, Filter)
    assert len(flt.must) == 1
    assert flt.must[0].key == "chapter"
    assert flt.must[0].match.value == "Intro"


def test_payload_maps_to_chunk():
    results = retrieval.retrieve("q")
    assert len(results) == 1
    r = results[0]
    assert r.score == 0.91
    assert r.chunk.id == "p1"
    assert r.chunk.course == "Wavelet Transform"
    assert r.chunk.chapter == "Intro"
    assert r.chunk.page == 11
    assert r.chunk.text == "the chunk text"
    assert r.citation() == "(Wavelet Transform, Intro, p.11)"


def test_answer_threads_course_and_chapter_to_retrieve(monkeypatch):
    import core.answer as answer_mod

    captured = {}

    def fake_retrieve(question, *, k=5, course=None, chapter=None, owner=None):
        captured.update(question=question, k=k, course=course, chapter=chapter, owner=owner)
        return []  # empty -> refusal, so no LLM is invoked

    monkeypatch.setattr(answer_mod, "retrieve", fake_retrieve)
    out = answer_mod.answer("q", course="Wavelet Transform", chapter="Intro", owner="uA")
    assert out["refused"] is True
    assert captured == {
        "question": "q",
        "k": 5,
        "course": "Wavelet Transform",
        "chapter": "Intro",
        "owner": "uA",
    }


# --- Reranker --------------------------------------------------------------


def _make_retrieved(chunk_id, text, score=0.0):
    chunk = retrieval.Chunk(id=chunk_id, course="C", page=1, text=text, chapter=None)
    return retrieval.Retrieved(chunk=chunk, score=score)


def test_rerank_helper_orders_by_score_and_truncates():
    candidates = [
        _make_retrieved("a", "low", score=0.9),
        _make_retrieved("b", "high", score=0.1),
        _make_retrieved("c", "mid", score=0.5),
    ]
    # Fake scorer: relevance keyed by text, ignoring the original similarity.
    fake_scores = {"low": 0.1, "high": 0.9, "mid": 0.5}

    def scorer(question, texts):
        return [fake_scores[t] for t in texts]

    out = retrieval.rerank("q", candidates, k=2, scorer=scorer)
    assert [r.chunk.id for r in out] == ["b", "c"]
    # The cross-encoder score replaces the original similarity.
    assert [r.score for r in out] == [0.9, 0.5]


def test_rerank_helper_handles_empty():
    assert retrieval.rerank("q", [], k=3, scorer=lambda q, t: []) == []


def test_dense_path_unchanged_when_no_reranker(monkeypatch):
    _set_settings(monkeypatch, reranker_model="")
    results = retrieval.retrieve("q")
    kwargs = _FakeQdrantClient.last_kwargs
    # Default path: threshold applied, only k candidates fetched.
    assert kwargs["limit"] == 5
    assert kwargs["score_threshold"] == 0.5
    assert [r.chunk.id for r in results] == ["p1"]
    assert results[0].score == 0.91


def test_reranker_reorders_and_truncates_to_k(monkeypatch):
    _set_settings(monkeypatch, reranker_model="fake-model", rerank_candidates=20)
    _FakeQdrantClient.points = [
        _point("p1", 0.91, "alpha"),
        _point("p2", 0.80, "bravo"),
        _point("p3", 0.70, "charlie"),
    ]
    # Reverse the dense order via the fake cross-encoder.
    fake_scores = {"alpha": 0.1, "bravo": 0.5, "charlie": 0.9}

    def scorer(question, texts):
        return [fake_scores[t] for t in texts]

    results = retrieval.retrieve("q", k=2, scorer=scorer)
    assert [r.chunk.id for r in results] == ["p3", "p2"]
    assert [r.score for r in results] == [0.9, 0.5]


def test_reranker_fetches_more_candidates_above_threshold(monkeypatch):
    # The reranker widens the candidate pool but keeps the dense similarity
    # threshold, so the cross-encoder only ever reorders in-course survivors.
    settings = _set_settings(monkeypatch, reranker_model="fake-model", rerank_candidates=20)
    retrieval.retrieve("q", k=5, scorer=lambda question, texts: [0.0] * len(texts))
    kwargs = _FakeQdrantClient.last_kwargs
    assert kwargs["limit"] == 20
    assert kwargs["score_threshold"] == settings.similarity_threshold


def test_reranker_returns_empty_when_no_candidates_pass_threshold(monkeypatch):
    # Out-of-course question: the dense pre-filter drops everything, so even with
    # a reranker configured the retrieval is empty -> the answer layer refuses.
    _set_settings(monkeypatch, reranker_model="fake-model", rerank_candidates=20)
    _FakeQdrantClient.points = []
    results = retrieval.retrieve("q", k=5, scorer=lambda question, texts: [0.0] * len(texts))
    assert results == []


def test_reranker_limit_at_least_k(monkeypatch):
    _set_settings(monkeypatch, reranker_model="fake-model", rerank_candidates=3)
    retrieval.retrieve("q", k=5, scorer=lambda question, texts: [0.0] * len(texts))
    assert _FakeQdrantClient.last_kwargs["limit"] == 5


def test_reranker_keeps_course_chapter_filter(monkeypatch):
    _set_settings(monkeypatch, reranker_model="fake-model")
    retrieval.retrieve(
        "q",
        course="Wavelet Transform",
        chapter="Intro",
        scorer=lambda question, texts: [0.0] * len(texts),
    )
    flt = _FakeQdrantClient.last_kwargs["query_filter"]
    assert isinstance(flt, Filter)
    keys = {(c.key, c.match.value) for c in flt.must}
    assert keys == {("course", "Wavelet Transform"), ("chapter", "Intro")}


# --- Hybrid dense + sparse (RRF) -------------------------------------------


def test_hybrid_disabled_uses_dense_query(monkeypatch):
    # With hybrid off, retrieve issues the plain dense query (no prefetch),
    # byte-identically to before.
    _set_settings(monkeypatch, hybrid_retrieval=False)
    _FakeQdrantClient.has_sparse = True  # availability is irrelevant when off
    retrieval.retrieve("q")
    kwargs = _FakeQdrantClient.last_kwargs
    assert "prefetch" not in kwargs
    assert kwargs["score_threshold"] == 0.5
    assert kwargs["limit"] == 5


def test_hybrid_falls_back_to_dense_when_no_sparse_vector(monkeypatch):
    # Hybrid requested but the collection is dense-only (the live demo index):
    # fall back gracefully to the dense query instead of crashing.
    _set_settings(monkeypatch, hybrid_retrieval=True)
    _FakeQdrantClient.has_sparse = False
    results = retrieval.retrieve("q")
    kwargs = _FakeQdrantClient.last_kwargs
    assert "prefetch" not in kwargs
    assert kwargs["score_threshold"] == 0.5
    assert [r.chunk.id for r in results] == ["p1"]


def test_hybrid_issues_fused_rrf_query_when_available(monkeypatch):
    _set_settings(monkeypatch, hybrid_retrieval=True, hybrid_prefetch=50)
    _FakeQdrantClient.has_sparse = True
    results = retrieval.retrieve("q", k=5)
    kwargs = _FakeQdrantClient.last_kwargs
    # The outer query is an RRF fusion over two prefetch branches.
    assert isinstance(kwargs["query"], retrieval.FusionQuery)
    assert kwargs["query"].fusion == retrieval.Fusion.RRF
    prefetch = kwargs["prefetch"]
    assert len(prefetch) == 2
    dense_branch, sparse_branch = prefetch
    # Dense branch: named dense vector, keeps the similarity threshold (refusal).
    assert dense_branch.using == "dense"
    assert dense_branch.score_threshold == 0.5
    assert dense_branch.limit == 50
    # Sparse branch: named sparse vector, sparse query, no dense threshold.
    assert sparse_branch.using == "sparse"
    assert isinstance(sparse_branch.query, retrieval.SparseVector)
    assert sparse_branch.query.indices == [1, 2]
    assert [r.chunk.id for r in results] == ["p1"]


def test_hybrid_refuses_when_nothing_clears_threshold(monkeypatch):
    # The dense branch keeps the similarity threshold, so an out-of-course
    # question yields no fused candidates -> the answer layer refuses.
    _set_settings(monkeypatch, hybrid_retrieval=True)
    _FakeQdrantClient.has_sparse = True
    _FakeQdrantClient.points = []
    results = retrieval.retrieve("q")
    assert results == []


def test_hybrid_keeps_course_chapter_filter(monkeypatch):
    _set_settings(monkeypatch, hybrid_retrieval=True)
    _FakeQdrantClient.has_sparse = True
    retrieval.retrieve("q", course="Wavelet Transform", chapter="Intro")
    kwargs = _FakeQdrantClient.last_kwargs
    # The filter is applied both on the outer query and on each prefetch branch.
    outer = kwargs["query_filter"]
    assert isinstance(outer, Filter)
    for branch in kwargs["prefetch"]:
        keys = {(c.key, c.match.value) for c in branch.filter.must}
        assert keys == {("course", "Wavelet Transform"), ("chapter", "Intro")}


def test_hybrid_composes_with_reranker(monkeypatch):
    # Hybrid base path + reranker on top: fused query issued, then rerank.
    _set_settings(
        monkeypatch, hybrid_retrieval=True, reranker_model="fake-model", rerank_candidates=20
    )
    _FakeQdrantClient.has_sparse = True
    _FakeQdrantClient.points = [
        _point("p1", 0.91, "alpha"),
        _point("p2", 0.80, "bravo"),
    ]
    fake_scores = {"alpha": 0.1, "bravo": 0.9}
    results = retrieval.retrieve(
        "q", k=1, scorer=lambda question, texts: [fake_scores[t] for t in texts]
    )
    kwargs = _FakeQdrantClient.last_kwargs
    assert isinstance(kwargs["query"], retrieval.FusionQuery)
    # Reranker widened the prefetch/limit and reordered: bravo wins.
    assert [r.chunk.id for r in results] == ["p2"]


def test_dense_query_names_vector_on_named_vector_collection(monkeypatch):
    # Sparse-enabled (named-vector) collection with hybrid OFF: the dense query
    # must name the dense vector, else Qdrant rejects it (no default vector).
    _set_settings(monkeypatch, hybrid_retrieval=False)
    _FakeQdrantClient.has_sparse = True
    retrieval.retrieve("q", k=5)
    assert _FakeQdrantClient.last_kwargs.get("using") == retrieval.DENSE_VECTOR_NAME


def test_dense_query_uses_default_vector_on_plain_collection(monkeypatch):
    # Plain dense-only collection: no named vector, so the default (using=None).
    _set_settings(monkeypatch, hybrid_retrieval=False)
    _FakeQdrantClient.has_sparse = False
    retrieval.retrieve("q", k=5)
    assert _FakeQdrantClient.last_kwargs.get("using") is None


# --- Per-account owner scoping ---------------------------------------------

from qdrant_client.models import (  # noqa: E402
    FieldCondition,
    IsEmptyCondition,
)


def _owner_sub_filter(flt: Filter) -> Filter | None:
    """Return the nested owner-scope sub-filter (the ``should`` branch) in ``flt``."""
    for cond in flt.must or []:
        if isinstance(cond, Filter):
            return cond
    return None


def test_owner_scope_filter_is_mine_or_unset():
    flt = retrieval.owner_scope_filter("uA")
    assert flt.must is None
    assert len(flt.should) == 2
    field, empty = flt.should
    assert isinstance(field, FieldCondition)
    assert field.key == "owner" and field.match.value == "uA"
    assert isinstance(empty, IsEmptyCondition)
    assert empty.is_empty.key == "owner"


def test_build_filter_appends_owner_scope_to_must():
    flt = retrieval._build_filter("Wavelet Transform", None, "uA")
    assert isinstance(flt, Filter)
    # course FieldCondition + the owner-scope sub-filter.
    courses = [c for c in flt.must if isinstance(c, FieldCondition) and c.key == "course"]
    assert courses and courses[0].match.value == "Wavelet Transform"
    sub = _owner_sub_filter(flt)
    assert sub is not None and len(sub.should) == 2


def test_build_filter_owner_only():
    flt = retrieval._build_filter(None, None, "uA")
    assert isinstance(flt, Filter)
    assert len(flt.must) == 1
    assert _owner_sub_filter(flt) is not None


def test_build_filter_none_without_owner():
    assert retrieval._build_filter(None, None, None) is None


def test_retrieve_threads_owner_into_query_filter():
    retrieval.retrieve("q", owner="uA")
    flt = _FakeQdrantClient.last_kwargs["query_filter"]
    assert isinstance(flt, Filter)
    assert _owner_sub_filter(flt) is not None


def _cond_ok(payload: dict, cond) -> bool:
    """Evaluate one leaf condition against a payload (owner-scope semantics only)."""
    if isinstance(cond, IsEmptyCondition):
        return payload.get(cond.is_empty.key) is None
    if isinstance(cond, FieldCondition) and cond.match is not None:
        return payload.get(cond.key) == cond.match.value
    return True


def _point_passes(payload: dict, flt: Filter | None) -> bool:
    """Apply a (possibly owner-scoped) filter to a payload the way Qdrant would."""
    if flt is None:
        return True
    for cond in flt.must or []:
        if isinstance(cond, Filter):  # nested owner-scope: should == OR
            if not any(_cond_ok(payload, c) for c in cond.should or []):
                return False
        elif not _cond_ok(payload, cond):
            return False
    return True


class _OwnerAwareClient:
    """A fake that honours the owner-scope filter against canned points.

    Lets a test assert the end-to-end semantics: mine is returned for me, another
    owner's is not, and an owner-less (legacy/shared) point is returned for all.
    """

    corpus = [
        SimpleNamespace(
            id="mine", score=0.9, payload={"course": "C", "page": 1, "text": "a", "owner": "uA"}
        ),
        SimpleNamespace(
            id="other", score=0.9, payload={"course": "C", "page": 2, "text": "b", "owner": "uB"}
        ),
        SimpleNamespace(
            id="legacy", score=0.9, payload={"course": "C", "page": 3, "text": "c", "owner": None}
        ),
    ]

    def __init__(self, *args, **kwargs):
        pass

    def query_points(self, **kwargs):
        flt = kwargs.get("query_filter")
        points = [p for p in self.corpus if _point_passes(p.payload, flt)]
        return SimpleNamespace(points=points)

    def get_collection(self, name):
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(sparse_vectors={})))


def test_owner_scoping_semantics(monkeypatch):
    _set_settings(monkeypatch)
    monkeypatch.setattr(retrieval, "QdrantClient", _OwnerAwareClient)

    mine = {r.chunk.id for r in retrieval.retrieve("q", owner="uA")}
    assert mine == {"mine", "legacy"}  # my own + shared/legacy, never uB's

    other = {r.chunk.id for r in retrieval.retrieve("q", owner="uB")}
    assert other == {"other", "legacy"}

    # Legacy (owner-less) material stays visible to every account.
    assert "legacy" in mine and "legacy" in other

    # No owner scoping -> the whole corpus (unchanged global behaviour).
    everyone = {r.chunk.id for r in retrieval.retrieve("q")}
    assert everyone == {"mine", "other", "legacy"}
