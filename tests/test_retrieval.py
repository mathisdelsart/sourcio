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

    def __init__(self, *args, **kwargs):
        pass

    def query_points(self, **kwargs):
        _FakeQdrantClient.last_kwargs = kwargs
        return SimpleNamespace(points=list(_FakeQdrantClient.points))


@pytest.fixture(autouse=True)
def _no_model_no_network(monkeypatch):
    _FakeQdrantClient.last_kwargs = None
    _FakeQdrantClient.points = [_point("p1", 0.91, "the chunk text")]
    # Never load the real embedding model.
    monkeypatch.setattr(retrieval, "embed_query", lambda text: [0.1, 0.2, 0.3])
    # Never reach a real Qdrant server.
    monkeypatch.setattr(retrieval, "QdrantClient", _FakeQdrantClient)


def _set_settings(monkeypatch, **overrides):
    """Override the settings seen by retrieval without loading real ones."""
    base = {
        "qdrant_url": "http://localhost:6333",
        "qdrant_collection": "courses",
        "similarity_threshold": 0.5,
        "reranker_model": "",
        "rerank_candidates": 20,
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

    def fake_retrieve(question, *, k=5, course=None, chapter=None):
        captured.update(question=question, k=k, course=course, chapter=chapter)
        return []  # empty -> refusal, so no LLM is invoked

    monkeypatch.setattr(answer_mod, "retrieve", fake_retrieve)
    out = answer_mod.answer("q", course="Wavelet Transform", chapter="Intro")
    assert out["refused"] is True
    assert captured == {
        "question": "q",
        "k": 5,
        "course": "Wavelet Transform",
        "chapter": "Intro",
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
