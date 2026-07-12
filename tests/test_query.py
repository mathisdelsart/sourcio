"""Offline tests for multi-query retrieval expansion.

No API calls and no real models. ``get_llm`` is stubbed to a fake chat model,
``embed_query`` to a dummy vector, and the Qdrant client to a fake that returns
canned points keyed by query. Covers:

- ``expand_query``: original + rewrites, dedup, robustness to malformed/raising
  output (always falls back to ``[question]``, never raises).
- ``retrieve_multi``: fuses/dedups across sub-queries, still refuses when nothing
  clears the threshold, and composes with the reranker.
- The default-off path leaves ``retrieve`` (and ``answer``) unchanged.
"""

from types import SimpleNamespace

import core.answer as answer_mod
import core.query as query_mod
import core.retrieval as retrieval

# --- expand_query ----------------------------------------------------------


def _fake_llm(content):
    """A chat model whose ``.invoke()`` returns an object with ``.content``."""
    return SimpleNamespace(invoke=lambda messages, config=None: SimpleNamespace(content=content))


def _patch_llm(monkeypatch, content):
    monkeypatch.setattr(
        query_mod, "get_llm", lambda role="default", api_key=None: _fake_llm(content)
    )


def test_expand_query_returns_original_plus_rewrites(monkeypatch):
    _patch_llm(monkeypatch, "What is a wavelet?\nDefine wavelet basis\nWavelet vs Fourier")
    out = query_mod.expand_query("Explain wavelets", n=3)
    assert out[0] == "Explain wavelets"  # original is always first
    assert out == [
        "Explain wavelets",
        "What is a wavelet?",
        "Define wavelet basis",
        "Wavelet vs Fourier",
    ]


def test_expand_query_strips_bullets_and_numbering(monkeypatch):
    _patch_llm(monkeypatch, "1. first phrasing\n- second phrasing\n* third phrasing")
    out = query_mod.expand_query("q", n=3)
    assert out == ["q", "first phrasing", "second phrasing", "third phrasing"]


def test_expand_query_caps_at_n(monkeypatch):
    _patch_llm(monkeypatch, "a\nb\nc\nd\ne")
    out = query_mod.expand_query("q", n=2)
    # Original + at most n rewrites.
    assert out == ["q", "a", "b"]


def test_expand_query_dedups_case_insensitively(monkeypatch):
    _patch_llm(monkeypatch, "Explain Wavelets\nwavelet basis\nWAVELET BASIS")
    out = query_mod.expand_query("explain wavelets", n=5)
    # The rewrite equal to the original (modulo case) and the duplicate basis
    # line are both dropped.
    assert out == ["explain wavelets", "wavelet basis"]


def test_expand_query_falls_back_when_llm_raises(monkeypatch):
    def _raising_llm(role="default", api_key=None):
        class _LLM:
            def invoke(self, messages, config=None):
                raise RuntimeError("provider down")

        return _LLM()

    monkeypatch.setattr(query_mod, "get_llm", _raising_llm)
    assert query_mod.expand_query("q", n=3) == ["q"]


def test_expand_query_falls_back_on_empty_output(monkeypatch):
    _patch_llm(monkeypatch, "   \n\n   ")
    assert query_mod.expand_query("q", n=3) == ["q"]


def test_expand_query_falls_back_on_non_string_content(monkeypatch):
    _patch_llm(monkeypatch, None)
    assert query_mod.expand_query("q", n=3) == ["q"]


def test_expand_query_zero_n_returns_original_only(monkeypatch):
    # n<=0 short-circuits without touching the LLM.
    def _boom(role="default", api_key=None):
        raise AssertionError("LLM must not be called when n<=0")

    monkeypatch.setattr(query_mod, "get_llm", _boom)
    assert query_mod.expand_query("q", n=0) == ["q"]


# --- retrieve_multi (fusion) ----------------------------------------------


def _point(point_id, score, text, *, course="Wavelet Transform", chapter="Intro", page=11):
    return SimpleNamespace(
        id=point_id,
        score=score,
        payload={"course": course, "chapter": chapter, "page": page, "text": text},
    )


class _FakeQdrantClient:
    """Returns canned points selected by the embedded query vector tag."""

    # Map from a query string to the points returned for it.
    by_query: dict = {}
    last_kwargs: dict | None = None
    has_sparse: bool = False

    def __init__(self, *args, **kwargs):
        pass

    def query_points(self, **kwargs):
        _FakeQdrantClient.last_kwargs = kwargs
        # The dummy embedding carries the query string so we can route points.
        tag = kwargs.get("query")
        points = _FakeQdrantClient.by_query.get(tag, [])
        return SimpleNamespace(points=list(points))

    def get_collection(self, name):
        sparse = {"sparse": object()} if _FakeQdrantClient.has_sparse else {}
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(sparse_vectors=sparse))
        )


def _settings(monkeypatch, **overrides):
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
        "multi_query": False,
        "multi_query_n": 3,
    }
    base.update(overrides)
    settings = SimpleNamespace(**base)
    monkeypatch.setattr(retrieval, "get_settings", lambda: settings)
    return settings


def _patch_retrieval_env(monkeypatch):
    _FakeQdrantClient.last_kwargs = None
    _FakeQdrantClient.has_sparse = False
    _FakeQdrantClient.by_query = {}
    # The dummy "embedding" is just the query text, so the fake client can route.
    monkeypatch.setattr(retrieval, "embed_query", lambda text: text)
    monkeypatch.setattr("qdrant_client.QdrantClient", _FakeQdrantClient)


def test_retrieve_multi_fuses_and_dedups_across_subqueries(monkeypatch):
    _patch_retrieval_env(monkeypatch)
    _settings(monkeypatch, multi_query=True, multi_query_n=2)
    monkeypatch.setattr(
        retrieval, "expand_query", lambda q, n, api_key=None: [q, "rewrite-a", "rewrite-b"]
    )

    _FakeQdrantClient.by_query = {
        "q": [_point("p1", 0.90, "alpha")],
        "rewrite-a": [
            _point("p1", 0.95, "alpha"),  # same chunk, higher score
            _point("p2", 0.70, "bravo"),
        ],
        "rewrite-b": [_point("p3", 0.80, "charlie")],
    }

    results = retrieval.retrieve_multi("q", k=5)
    ids = [r.chunk.id for r in results]
    # De-duplicated by chunk id, sorted by best score: p1(0.95) > p3(0.80) > p2(0.70).
    assert ids == ["p1", "p3", "p2"]
    # p1 keeps the BEST score seen across sub-queries.
    assert results[0].score == 0.95


def test_retrieve_multi_truncates_to_k(monkeypatch):
    _patch_retrieval_env(monkeypatch)
    _settings(monkeypatch, multi_query=True)
    monkeypatch.setattr(retrieval, "expand_query", lambda q, n, api_key=None: [q, "r1"])
    _FakeQdrantClient.by_query = {
        "q": [_point("p1", 0.9, "a"), _point("p2", 0.8, "b")],
        "r1": [_point("p3", 0.7, "c")],
    }
    results = retrieval.retrieve_multi("q", k=2)
    assert [r.chunk.id for r in results] == ["p1", "p2"]


def test_retrieve_multi_refuses_when_nothing_clears_threshold(monkeypatch):
    # Every sub-query returns no points (the dense threshold dropped everything),
    # so the fused pool is empty -> the answer layer refuses.
    _patch_retrieval_env(monkeypatch)
    _settings(monkeypatch, multi_query=True)
    monkeypatch.setattr(retrieval, "expand_query", lambda q, n, api_key=None: [q, "r1", "r2"])
    _FakeQdrantClient.by_query = {}  # no query yields candidates
    assert retrieval.retrieve_multi("off-topic") == []


def test_retrieve_multi_keeps_threshold_per_subquery(monkeypatch):
    _patch_retrieval_env(monkeypatch)
    settings = _settings(monkeypatch, multi_query=True)
    monkeypatch.setattr(retrieval, "expand_query", lambda q, n, api_key=None: [q])
    _FakeQdrantClient.by_query = {"q": [_point("p1", 0.9, "a")]}
    retrieval.retrieve_multi("q")
    # Each sub-query still passes the configured similarity threshold to Qdrant.
    assert _FakeQdrantClient.last_kwargs["score_threshold"] == settings.similarity_threshold


def test_retrieve_multi_composes_with_reranker(monkeypatch):
    _patch_retrieval_env(monkeypatch)
    _settings(monkeypatch, multi_query=True, reranker_model="fake-model", rerank_candidates=20)
    monkeypatch.setattr(retrieval, "expand_query", lambda q, n, api_key=None: [q, "r1"])
    _FakeQdrantClient.by_query = {
        "q": [_point("p1", 0.91, "alpha")],
        "r1": [_point("p2", 0.80, "bravo")],
    }
    # Cross-encoder reverses the similarity order: bravo wins.
    fake_scores = {"alpha": 0.1, "bravo": 0.9}
    results = retrieval.retrieve_multi(
        "q", k=1, scorer=lambda question, texts: [fake_scores[t] for t in texts]
    )
    assert [r.chunk.id for r in results] == ["p2"]
    assert results[0].score == 0.9
    # The reranker widened the per-query fetch limit.
    assert _FakeQdrantClient.last_kwargs["limit"] == 20


def test_retrieve_multi_reranks_against_original_question(monkeypatch):
    _patch_retrieval_env(monkeypatch)
    _settings(monkeypatch, multi_query=True, reranker_model="fake-model")
    monkeypatch.setattr(retrieval, "expand_query", lambda q, n, api_key=None: [q, "rewrite"])
    _FakeQdrantClient.by_query = {"the real question": [_point("p1", 0.9, "a")], "rewrite": []}
    seen = {}

    def scorer(question, texts):
        seen["question"] = question
        return [0.5] * len(texts)

    retrieval.retrieve_multi("the real question", scorer=scorer)
    assert seen["question"] == "the real question"


# --- default-off path is unchanged ----------------------------------------


def test_fuse_helper_keeps_best_score_and_orders():
    def r(cid, score):
        chunk = retrieval.Chunk(id=cid, course="C", page=1, text=cid, chapter=None)
        return retrieval.Retrieved(chunk=chunk, score=score)

    fused = retrieval._fuse([[r("a", 0.3), r("b", 0.9)], [r("a", 0.7), r("c", 0.5)]])
    assert [x.chunk.id for x in fused] == ["b", "a", "c"]
    assert next(x for x in fused if x.chunk.id == "a").score == 0.7  # best kept


def test_answer_uses_single_query_when_multi_query_off(monkeypatch):
    # Default settings (multi_query=False): answer() must call retrieve(), not
    # retrieve_multi(). Real get_settings is used; the default is off.
    called = {"single": 0, "multi": 0}

    def fake_retrieve(q, *, k=5, course=None, chapter=None, owner=None):
        called["single"] += 1
        return []

    def fake_multi(q, *, k=5, course=None, chapter=None, owner=None, api_key=None):
        called["multi"] += 1
        return []

    monkeypatch.setattr(answer_mod, "retrieve", fake_retrieve)
    monkeypatch.setattr(answer_mod, "retrieve_multi", fake_multi)
    out = answer_mod.answer("q")
    assert out["refused"] is True
    assert called == {"single": 1, "multi": 0}


def test_answer_uses_multi_query_when_enabled(monkeypatch):
    called = {"single": 0, "multi": 0}

    def fake_retrieve(q, *, k=5, course=None, chapter=None, owner=None):
        called["single"] += 1
        return []

    def fake_multi(q, *, k=5, course=None, chapter=None, owner=None, api_key=None):
        called["multi"] += 1
        return []

    monkeypatch.setattr(answer_mod, "retrieve", fake_retrieve)
    monkeypatch.setattr(answer_mod, "retrieve_multi", fake_multi)
    monkeypatch.setattr(
        answer_mod, "get_settings", lambda: SimpleNamespace(multi_query=True, multi_query_n=3)
    )
    out = answer_mod.answer("q")
    assert out["refused"] is True
    assert called == {"single": 0, "multi": 1}
