"""Tests for course/chapter filtering in retrieval.

No API calls and no real embedding model: ``embed_query`` is stubbed to a dummy
vector and the Qdrant client is replaced by a fake that records the filter it
was given and returns canned points.
"""

from types import SimpleNamespace

import pytest
from qdrant_client.models import Filter

import retrieval


class _FakeQdrantClient:
    """Captures query_points kwargs and returns canned points."""

    last_kwargs: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    def query_points(self, **kwargs):
        _FakeQdrantClient.last_kwargs = kwargs
        point = SimpleNamespace(
            id="p1",
            score=0.91,
            payload={
                "course": "Wavelet Transform",
                "chapter": "Intro",
                "page": 11,
                "text": "the chunk text",
            },
        )
        return SimpleNamespace(points=[point])


@pytest.fixture(autouse=True)
def _no_model_no_network(monkeypatch):
    _FakeQdrantClient.last_kwargs = None
    # Never load the real embedding model.
    monkeypatch.setattr(retrieval, "embed_query", lambda text: [0.1, 0.2, 0.3])
    # Never reach a real Qdrant server.
    monkeypatch.setattr(retrieval, "QdrantClient", _FakeQdrantClient)


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
    import answer as answer_mod

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
