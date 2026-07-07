"""Offline tests for the hybrid dense+sparse retrieval plumbing.

Covers the sparse-embedding conversion, sparse-aware indexing (named vectors),
and the LLM-free A/B retrieval-hit harness. No network, no real model: the
encoders and the Qdrant client are stubbed and call args are asserted.
"""

from types import SimpleNamespace

from qdrant_client import models

import ingestion.embed as embed
import ingestion.index as index
from eval.ab_retrieval import ABResult, run_ab
from eval.run_eval import EvalCase

# --- Sparse embeddings ------------------------------------------------------


def test_to_sparse_drops_zeros_and_casts_ids():
    sparse = embed._to_sparse({"5": 0.3, "12": 0.0, "7": 1.5})
    # Zero-weight token is dropped; ids become ints; values become floats.
    pairs = dict(zip(sparse.indices, sparse.values, strict=True))
    assert pairs == {5: 0.3, 7: 1.5}
    assert all(isinstance(i, int) for i in sparse.indices)
    assert all(isinstance(v, float) for v in sparse.values)


def test_embed_sparse_texts_uses_lexical_weights(monkeypatch):
    captured = {}

    class _FakeSparseModel:
        def encode(self, texts, **kwargs):
            captured["texts"] = texts
            captured["kwargs"] = kwargs
            return {"lexical_weights": [{"1": 0.5, "9": 0.25} for _ in texts]}

    monkeypatch.setattr(embed, "_sparse_model", lambda: _FakeSparseModel())
    out = embed.embed_sparse_texts(["a", "b"])
    assert len(out) == 2
    assert out[0].indices == [1, 9]
    assert out[0].values == [0.5, 0.25]
    # Only the sparse output is requested from bge-m3.
    assert captured["kwargs"]["return_sparse"] is True
    assert captured["kwargs"]["return_dense"] is False


def test_embed_sparse_query_returns_single(monkeypatch):
    monkeypatch.setattr(
        embed,
        "embed_sparse_texts",
        lambda texts: [embed.SparseEmbedding(indices=[3], values=[1.0]) for _ in texts],
    )
    sv = embed.embed_sparse_query("q")
    assert sv.indices == [3]
    assert sv.values == [1.0]


# --- Sparse-aware indexing --------------------------------------------------


class _FakeIndexClient:
    def __init__(self):
        self.created = None
        self.upserted = None
        self._exists = False

    def collection_exists(self, name):
        return self._exists

    def create_collection(self, **kwargs):
        self.created = kwargs

    def upsert(self, **kwargs):
        self.upserted = kwargs


def _chunk(cid, text="t"):
    return index.Chunk(id=cid, course="C", page=1, text=text, chapter=None)


def _patch_index(monkeypatch, client, *, sparse_dim=4):
    monkeypatch.setattr(index, "_client", lambda: client)
    monkeypatch.setattr(index, "embedding_dim", lambda: sparse_dim)
    monkeypatch.setattr(index, "embed_texts", lambda texts: [[0.1] * sparse_dim for _ in texts])
    monkeypatch.setattr(
        index,
        "embed_sparse_texts",
        lambda texts: [embed.SparseEmbedding(indices=[1, 2], values=[0.5, 0.7]) for _ in texts],
    )
    settings = SimpleNamespace(qdrant_collection="courses", sparse_vector_name="sparse")
    monkeypatch.setattr(index, "get_settings", lambda: settings)


def test_dense_only_collection_creation_unchanged(monkeypatch):
    client = _FakeIndexClient()
    _patch_index(monkeypatch, client)
    index.index_chunks([_chunk("a")])
    # Default path: a single unnamed cosine vector, no sparse config.
    assert isinstance(client.created["vectors_config"], models.VectorParams)
    assert "sparse_vectors_config" not in client.created
    # Point carries the bare dense vector (not a named dict).
    point = client.upserted["points"][0]
    assert point.vector == [0.1] * 4


def test_sparse_collection_creation_uses_named_vectors(monkeypatch):
    client = _FakeIndexClient()
    _patch_index(monkeypatch, client)
    index.index_chunks([_chunk("a")], sparse=True)
    cfg = client.created["vectors_config"]
    assert set(cfg) == {index.DENSE_VECTOR_NAME}
    assert isinstance(cfg[index.DENSE_VECTOR_NAME], models.VectorParams)
    sparse_cfg = client.created["sparse_vectors_config"]
    assert set(sparse_cfg) == {"sparse"}
    assert isinstance(sparse_cfg["sparse"], models.SparseVectorParams)


def test_sparse_upsert_builds_named_dense_and_sparse_point(monkeypatch):
    client = _FakeIndexClient()
    _patch_index(monkeypatch, client)
    index.index_chunks([_chunk("a")], sparse=True)
    point = client.upserted["points"][0]
    assert set(point.vector) == {index.DENSE_VECTOR_NAME, "sparse"}
    assert point.vector[index.DENSE_VECTOR_NAME] == [0.1] * 4
    sv = point.vector["sparse"]
    assert isinstance(sv, models.SparseVector)
    assert sv.indices == [1, 2]
    assert sv.values == [0.5, 0.7]


def test_sparse_skips_when_collection_exists(monkeypatch):
    client = _FakeIndexClient()
    _patch_index(monkeypatch, client)
    client._exists = True
    index.index_chunks([_chunk("a")], sparse=True)
    assert client.created is None  # not recreated
    assert client.upserted is not None  # still upserts


class _PayloadIndexClient(_FakeIndexClient):
    """Fake client that supports create_payload_index, recording its fields."""

    def __init__(self, *, raises=False):
        super().__init__()
        self.indexed_fields: list[str] = []
        self._raises = raises

    def create_payload_index(self, *, collection_name, field_name, field_schema):  # noqa: ARG002
        if self._raises:
            raise RuntimeError("index already exists")
        self.indexed_fields.append(field_name)


def test_ensure_payload_indexes_covers_course_and_document(monkeypatch):
    client = _PayloadIndexClient()
    _patch_index(monkeypatch, client)
    index.index_chunks([_chunk("a")])
    # Keyword indexes are created for every filterable payload field.
    assert set(client.indexed_fields) == {"course", "document", "owner"}


def test_ensure_payload_indexes_is_best_effort(monkeypatch):
    # A client whose create_payload_index raises (e.g. index already exists) must
    # not fail indexing: the upsert still happens.
    client = _PayloadIndexClient(raises=True)
    _patch_index(monkeypatch, client)
    index.index_chunks([_chunk("a")])
    assert client.upserted is not None


# --- A/B harness math -------------------------------------------------------


def _case(question, keywords):
    return EvalCase(question=question, expect_refusal=False, expect_keywords=tuple(keywords))


def test_ab_harness_counts_hits_per_mode():
    cases = [
        _case("q1", ["alpha"]),
        _case("q2", ["beta"]),
        # Out-of-course / no-keyword cases are ignored by the A/B check.
        EvalCase(question="oo", expect_refusal=True),
        EvalCase(question="nokw", expect_refusal=False, expect_keywords=()),
    ]

    def retrieve_fn(question, hybrid):
        # Dense misses q2; hybrid finds both via the sparse branch.
        table = {
            ("q1", False): ["alpha here"],
            ("q1", True): ["alpha here"],
            ("q2", False): ["nothing relevant"],
            ("q2", True): ["beta term"],
        }
        return table[(question, hybrid)]

    result = run_ab(cases, retrieve_fn)
    assert result.checked == 2
    assert result.dense_hits == 1
    assert result.hybrid_hits == 2
    assert result.dense_hit_rate == 0.5
    assert result.hybrid_hit_rate == 1.0
    assert result.delta == 0.5


def test_ab_result_vacuous_when_nothing_checked():
    result = ABResult(checked=0, dense_hits=0, hybrid_hits=0)
    assert result.dense_hit_rate == 1.0
    assert result.hybrid_hit_rate == 1.0
    assert result.delta == 0.0


def test_ab_result_to_dict_includes_rates():
    data = ABResult(checked=4, dense_hits=2, hybrid_hits=3).to_dict()
    assert data["dense_hit_rate"] == 0.5
    assert data["hybrid_hit_rate"] == 0.75
    assert data["delta"] == 0.25
