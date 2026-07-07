"""Offline tests for opt-in HyDE (Hypothetical Document Embeddings) retrieval.

No API calls and no real models. ``get_llm`` is stubbed to a fake chat model,
``embed_query`` to a dummy vector that carries its input text, and the Qdrant
client to a fake that returns canned points keyed by the embedded text. Covers:

- ``hyde_passage``: returns the LLM passage, and falls back to the original
  question on raising/empty/non-string output (never raises).
- HyDE retrieval embeds the hypothetical passage (not the question) for the
  dense branch, still refuses when nothing clears the threshold, and composes
  with the reranker (which still scores against the original question).
- The default-off path leaves ``retrieve`` and ``answer`` unchanged.
"""

from types import SimpleNamespace

import core.answer as answer_mod
import core.query as query_mod
import core.retrieval as retrieval

# --- hyde_passage ----------------------------------------------------------


def _fake_llm(content):
    """A chat model whose ``.invoke()`` returns an object with ``.content``."""
    return SimpleNamespace(invoke=lambda messages, config=None: SimpleNamespace(content=content))


def _patch_llm(monkeypatch, content):
    monkeypatch.setattr(query_mod, "get_llm", lambda role="default": _fake_llm(content))


def test_hyde_passage_returns_llm_passage(monkeypatch):
    passage = "A wavelet is a localized oscillation used to analyze signals at multiple scales."
    _patch_llm(monkeypatch, "  " + passage + "  ")
    assert query_mod.hyde_passage("What is a wavelet?") == passage


def test_hyde_passage_falls_back_when_llm_raises(monkeypatch):
    def _raising_llm(role="default"):
        class _LLM:
            def invoke(self, messages, config=None):
                raise RuntimeError("provider down")

        return _LLM()

    monkeypatch.setattr(query_mod, "get_llm", _raising_llm)
    assert query_mod.hyde_passage("q") == "q"


def test_hyde_passage_falls_back_on_empty_output(monkeypatch):
    _patch_llm(monkeypatch, "   \n\n   ")
    assert query_mod.hyde_passage("q") == "q"


def test_hyde_passage_falls_back_on_non_string_content(monkeypatch):
    _patch_llm(monkeypatch, None)
    assert query_mod.hyde_passage("q") == "q"


# --- HyDE retrieval --------------------------------------------------------


def _point(point_id, score, text, *, course="Wavelet Transform", chapter="Intro", page=11):
    return SimpleNamespace(
        id=point_id,
        score=score,
        payload={"course": course, "chapter": chapter, "page": page, "text": text},
    )


class _FakeQdrantClient:
    """Returns canned points selected by the embedded query text tag."""

    by_query: dict = {}
    last_kwargs: dict | None = None
    has_sparse: bool = False

    def __init__(self, *args, **kwargs):
        pass

    def query_points(self, **kwargs):
        _FakeQdrantClient.last_kwargs = kwargs
        # The dummy embedding carries the embedded text so we can route points.
        # The hybrid path passes an (unhashable) FusionQuery; treat that as "no
        # canned route" since hybrid tests assert on the embedded branch texts.
        tag = kwargs.get("query")
        try:
            points = _FakeQdrantClient.by_query.get(tag, [])
        except TypeError:
            points = []
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
        "hyde": False,
    }
    base.update(overrides)
    settings = SimpleNamespace(**base)
    monkeypatch.setattr(retrieval, "get_settings", lambda: settings)
    return settings


def _patch_retrieval_env(monkeypatch):
    _FakeQdrantClient.last_kwargs = None
    _FakeQdrantClient.has_sparse = False
    _FakeQdrantClient.by_query = {}
    # The dummy "embedding" is just the embedded text, so the fake can route.
    monkeypatch.setattr(retrieval, "embed_query", lambda text: text)
    monkeypatch.setattr(retrieval, "QdrantClient", _FakeQdrantClient)


def test_retrieve_hyde_embeds_the_hypothetical_passage(monkeypatch):
    _patch_retrieval_env(monkeypatch)
    _settings(monkeypatch)
    monkeypatch.setattr(retrieval, "hyde_passage", lambda q: "HYPOTHETICAL ANSWER")
    # Only the hypothetical passage routes to a candidate; the bare question does not.
    _FakeQdrantClient.by_query = {"HYPOTHETICAL ANSWER": [_point("p1", 0.9, "alpha")]}

    results = retrieval.retrieve("What is alpha?", k=5, hyde=True)
    assert [r.chunk.id for r in results] == ["p1"]
    # The dense branch embedded the hypothetical passage, not the question.
    assert _FakeQdrantClient.last_kwargs["query"] == "HYPOTHETICAL ANSWER"


def test_retrieve_without_hyde_embeds_the_question(monkeypatch):
    _patch_retrieval_env(monkeypatch)
    _settings(monkeypatch)

    def _boom(q):
        raise AssertionError("hyde_passage must not be called when hyde=False")

    monkeypatch.setattr(retrieval, "hyde_passage", _boom)
    _FakeQdrantClient.by_query = {"What is alpha?": [_point("p1", 0.9, "alpha")]}

    results = retrieval.retrieve("What is alpha?", k=5)
    assert [r.chunk.id for r in results] == ["p1"]
    assert _FakeQdrantClient.last_kwargs["query"] == "What is alpha?"


def test_retrieve_hyde_refuses_when_nothing_clears_threshold(monkeypatch):
    # The threshold dropped everything (no points for the embedded passage), so
    # the result is empty -> the answer layer refuses. Refusal preserved.
    _patch_retrieval_env(monkeypatch)
    _settings(monkeypatch)
    monkeypatch.setattr(retrieval, "hyde_passage", lambda q: "off-topic hypothetical")
    _FakeQdrantClient.by_query = {}
    assert retrieval.retrieve("off-topic", hyde=True) == []
    # The configured similarity threshold was still passed through.
    assert _FakeQdrantClient.last_kwargs["score_threshold"] == 0.5


def test_retrieve_hyde_falls_back_to_question_on_llm_failure(monkeypatch):
    # hyde_passage never raises; when the real LLM fails it returns the question,
    # so HyDE degrades to a plain dense query on the question text.
    _patch_retrieval_env(monkeypatch)
    _settings(monkeypatch)

    def _raising_llm(role="default"):
        class _LLM:
            def invoke(self, messages, config=None):
                raise RuntimeError("provider down")

        return _LLM()

    monkeypatch.setattr(query_mod, "get_llm", _raising_llm)
    _FakeQdrantClient.by_query = {"the question": [_point("p1", 0.9, "alpha")]}

    results = retrieval.retrieve("the question", hyde=True)
    assert [r.chunk.id for r in results] == ["p1"]
    assert _FakeQdrantClient.last_kwargs["query"] == "the question"


def test_retrieve_hyde_composes_with_reranker(monkeypatch):
    _patch_retrieval_env(monkeypatch)
    _settings(monkeypatch, reranker_model="fake-model", rerank_candidates=20)
    monkeypatch.setattr(retrieval, "hyde_passage", lambda q: "HYPO")
    _FakeQdrantClient.by_query = {
        "HYPO": [_point("p1", 0.91, "alpha"), _point("p2", 0.80, "bravo")],
    }
    fake_scores = {"alpha": 0.1, "bravo": 0.9}
    seen = {}

    def scorer(question, texts):
        seen["question"] = question
        return [fake_scores[t] for t in texts]

    results = retrieval.retrieve("the real question", k=1, hyde=True, scorer=scorer)
    # Cross-encoder reordered: bravo wins.
    assert [r.chunk.id for r in results] == ["p2"]
    assert results[0].score == 0.9
    # The reranker widened the fetch limit, and scored against the question.
    assert _FakeQdrantClient.last_kwargs["limit"] == 20
    assert seen["question"] == "the real question"


def test_retrieve_hyde_uses_hypothetical_for_dense_question_for_sparse(monkeypatch):
    # Hybrid path: dense branch embeds the hypothetical passage, sparse branch
    # uses the question. Two prefetch branches are issued.
    _patch_retrieval_env(monkeypatch)
    _FakeQdrantClient.has_sparse = True
    _settings(monkeypatch, hybrid_retrieval=True)
    monkeypatch.setattr(retrieval, "hyde_passage", lambda q: "HYPO")

    embedded = {}

    def _dense(text):
        embedded["dense"] = text
        return text

    def _sparse(text):
        embedded["sparse"] = text
        return SimpleNamespace(indices=[1], values=[1.0])

    monkeypatch.setattr(retrieval, "embed_query", _dense)
    # _hybrid_points imports embed_sparse_query lazily from ingestion.embed.
    import ingestion.embed as embed_mod

    monkeypatch.setattr(embed_mod, "embed_sparse_query", _sparse)

    retrieval.retrieve("the question", hyde=True)
    # Dense branch embedded the hypothetical passage; sparse used the question.
    assert embedded["dense"] == "HYPO"
    assert embedded["sparse"] == "the question"


# --- dispatcher precedence + default-off ----------------------------------


def test_answer_uses_hyde_when_enabled(monkeypatch):
    called = {"single": 0, "multi": 0, "hyde_flag": None}

    def fake_retrieve(q, *, k=5, course=None, chapter=None, owner=None, hyde=False):
        called["single"] += 1
        called["hyde_flag"] = hyde
        return []

    def fake_multi(q, *, k=5, course=None, chapter=None, owner=None):
        called["multi"] += 1
        return []

    monkeypatch.setattr(answer_mod, "retrieve", fake_retrieve)
    monkeypatch.setattr(answer_mod, "retrieve_multi", fake_multi)
    monkeypatch.setattr(
        answer_mod,
        "get_settings",
        lambda: SimpleNamespace(multi_query=False, multi_query_n=3, hyde=True),
    )
    out = answer_mod.answer("q")
    assert out["refused"] is True
    assert called["single"] == 1 and called["multi"] == 0
    assert called["hyde_flag"] is True


def test_answer_multi_query_takes_precedence_over_hyde(monkeypatch):
    called = {"single": 0, "multi": 0}

    def fake_retrieve(q, *, k=5, course=None, chapter=None, owner=None, hyde=False):
        called["single"] += 1
        return []

    def fake_multi(q, *, k=5, course=None, chapter=None, owner=None):
        called["multi"] += 1
        return []

    monkeypatch.setattr(answer_mod, "retrieve", fake_retrieve)
    monkeypatch.setattr(answer_mod, "retrieve_multi", fake_multi)
    monkeypatch.setattr(
        answer_mod,
        "get_settings",
        lambda: SimpleNamespace(multi_query=True, multi_query_n=3, hyde=True),
    )
    out = answer_mod.answer("q")
    assert out["refused"] is True
    # multi_query wins; HyDE path is not taken.
    assert called == {"single": 0, "multi": 1}


def test_answer_default_off_uses_plain_single_query(monkeypatch):
    called = {"single": 0, "multi": 0, "hyde_flag": None}

    def fake_retrieve(q, *, k=5, course=None, chapter=None, owner=None, hyde=False):
        called["single"] += 1
        called["hyde_flag"] = hyde
        return []

    def fake_multi(q, *, k=5, course=None, chapter=None, owner=None):
        called["multi"] += 1
        return []

    monkeypatch.setattr(answer_mod, "retrieve", fake_retrieve)
    monkeypatch.setattr(answer_mod, "retrieve_multi", fake_multi)
    # Real default settings: both multi_query and hyde are off.
    out = answer_mod.answer("q")
    assert out["refused"] is True
    assert called["single"] == 1 and called["multi"] == 0
    assert called["hyde_flag"] is False
