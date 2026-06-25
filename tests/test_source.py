"""Tests for source lookup (``core.sources``) and the ``GET /source`` route.

No real Qdrant, LLM, or network call is made: the ``QdrantClient`` is replaced
with a fake exposing only ``retrieve``, and the API is bound to an in-memory
SQLite database. The hit path, the unknown-id path, and graceful handling of a
missing collection (raising client) are all exercised in isolation.
"""

from types import SimpleNamespace

import pytest

import core.sources as sources_mod


class _FakeRetrieveClient:
    """A Qdrant client whose ``retrieve`` returns one preset point for a known id."""

    def __init__(self, *args, **kwargs):
        pass

    def retrieve(self, *, collection_name, ids, with_payload, with_vectors):  # noqa: ARG002
        if ids == ["known"]:
            point = SimpleNamespace(
                id="known",
                payload={
                    "course": "Wavelet Transform",
                    "chapter": "Ch.3",
                    "page": 12,
                    "text": "A wavelet is a localized oscillation.",
                },
            )
            return [point]
        return []


class _RaisingRetrieveClient:
    """A client whose ``retrieve`` raises (missing collection / unreachable)."""

    def __init__(self, *args, **kwargs):
        pass

    def retrieve(self, **kwargs):  # noqa: ARG002
        raise RuntimeError("collection not found")


def _use_client(monkeypatch, client_cls):
    """Patch the QdrantClient symbol used inside ``get_source``."""
    import qdrant_client

    monkeypatch.setattr(qdrant_client, "QdrantClient", client_cls)


def test_get_source_returns_mapped_chunk_for_known_id(monkeypatch):
    _use_client(monkeypatch, _FakeRetrieveClient)
    assert sources_mod.get_source("known") == {
        "id": "known",
        "course": "Wavelet Transform",
        "chapter": "Ch.3",
        "page": 12,
        "text": "A wavelet is a localized oscillation.",
    }


def test_get_source_none_for_unknown_id(monkeypatch):
    _use_client(monkeypatch, _FakeRetrieveClient)
    assert sources_mod.get_source("missing") is None


def test_get_source_none_when_retrieve_raises(monkeypatch):
    # A missing collection / unreachable server is treated as "not found".
    _use_client(monkeypatch, _RaisingRetrieveClient)
    assert sources_mod.get_source("known") is None


# --- /source route -----------------------------------------------------------
# Gated on the optional `api` extra (FastAPI). The core `get_source` tests above
# always run; only the route tests below need the API stack installed.

_HAS_API = True
try:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    import api.main as api_main
    from api.main import app
except ImportError:  # pragma: no cover - exercised only without the api extra
    _HAS_API = False

requires_api = pytest.mark.skipif(not _HAS_API, reason="requires the 'api' extra (FastAPI)")


_CHUNK = {
    "id": "known",
    "course": "Wavelet Transform",
    "chapter": "Ch.3",
    "page": 12,
    "text": "A wavelet is a localized oscillation.",
}


@pytest.fixture
def client():
    """Bind the API to a fresh in-memory SQLite DB and yield a test client."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    api_main.configure_engine(engine)
    with TestClient(app) as test_client:
        yield test_client
    api_main._engine = None


def _set_api_key(monkeypatch, key):
    """Drive the configured API key without touching the real cached settings."""
    from core.config import Settings

    settings = Settings(api_key=key)
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)


@requires_api
def test_source_route_returns_chunk(client, monkeypatch):
    monkeypatch.setattr(api_main, "get_source", lambda chunk_id: _CHUNK)
    response = client.get("/source/known")
    assert response.status_code == 200
    assert response.json() == _CHUNK


@requires_api
def test_source_route_404_for_unknown(client, monkeypatch):
    monkeypatch.setattr(api_main, "get_source", lambda chunk_id: None)
    response = client.get("/source/missing")
    assert response.status_code == 404


@requires_api
def test_source_open_when_no_key(client, monkeypatch):
    _set_api_key(monkeypatch, "")
    monkeypatch.setattr(api_main, "get_source", lambda chunk_id: _CHUNK)
    response = client.get("/source/known")
    assert response.status_code == 200


@requires_api
def test_source_rejects_missing_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "get_source", lambda chunk_id: _CHUNK)
    response = client.get("/source/known")
    assert response.status_code == 401


@requires_api
def test_source_rejects_wrong_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "get_source", lambda chunk_id: _CHUNK)
    response = client.get("/source/known", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


@requires_api
def test_source_accepts_correct_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "get_source", lambda chunk_id: _CHUNK)
    response = client.get("/source/known", headers={"X-API-Key": "secret-key"})
    assert response.status_code == 200
    assert response.json() == _CHUNK
