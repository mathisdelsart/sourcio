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


# --- owner scoping (M1) ------------------------------------------------------


class _OwnedRetrieveClient:
    """A client whose retrieved point carries an ``owner`` in its payload."""

    def __init__(self, *args, **kwargs):
        pass

    def retrieve(self, *, collection_name, ids, with_payload, with_vectors):  # noqa: ARG002
        point = SimpleNamespace(
            id="owned",
            payload={
                "owner": "alice",
                "course": "Wavelet Transform",
                "chapter": "Ch.3",
                "page": 12,
                "text": "A wavelet is a localized oscillation.",
            },
        )
        return [point]


def test_get_source_returns_chunk_for_matching_owner(monkeypatch):
    _use_client(monkeypatch, _OwnedRetrieveClient)
    chunk = sources_mod.get_source("owned", owner="alice")
    assert chunk is not None
    assert chunk["text"] == "A wavelet is a localized oscillation."
    # The owner is not surfaced in the response shape.
    assert "owner" not in chunk


def test_get_source_none_for_foreign_owner(monkeypatch):
    # A chunk owned by someone else is reported as absent (no existence leak).
    _use_client(monkeypatch, _OwnedRetrieveClient)
    assert sources_mod.get_source("owned", owner="mallory") is None


def test_get_source_owned_chunk_visible_when_no_owner_scope(monkeypatch):
    # owner=None (anonymous / legacy) keeps the unscoped behaviour.
    _use_client(monkeypatch, _OwnedRetrieveClient)
    assert sources_mod.get_source("owned") is not None


def test_get_source_shared_chunk_visible_to_any_owner(monkeypatch):
    # A point with no ``owner`` payload (shared/legacy corpus) is visible to all.
    _use_client(monkeypatch, _FakeRetrieveClient)
    assert sources_mod.get_source("known", owner="alice") is not None


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
    monkeypatch.setattr(api_main, "get_source", lambda chunk_id, owner=None: _CHUNK)
    response = client.get("/source/known")
    assert response.status_code == 200
    assert response.json() == _CHUNK


@requires_api
def test_source_route_404_for_unknown(client, monkeypatch):
    monkeypatch.setattr(api_main, "get_source", lambda chunk_id, owner=None: None)
    response = client.get("/source/missing")
    assert response.status_code == 404


@requires_api
def test_source_open_when_no_key(client, monkeypatch):
    _set_api_key(monkeypatch, "")
    monkeypatch.setattr(api_main, "get_source", lambda chunk_id, owner=None: _CHUNK)
    response = client.get("/source/known")
    assert response.status_code == 200


@requires_api
def test_source_rejects_missing_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "get_source", lambda chunk_id, owner=None: _CHUNK)
    response = client.get("/source/known")
    assert response.status_code == 401


@requires_api
def test_source_rejects_wrong_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "get_source", lambda chunk_id, owner=None: _CHUNK)
    response = client.get("/source/known", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


@requires_api
def test_source_accepts_correct_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "get_source", lambda chunk_id, owner=None: _CHUNK)
    response = client.get("/source/known", headers={"X-API-Key": "secret-key"})
    assert response.status_code == 200
    assert response.json() == _CHUNK


# --- /source route owner scoping (M1) ----------------------------------------
# The route resolves ``student_id`` into an effective owner and passes it to
# get_source, which only returns a chunk to its owner or when it is shared. Here
# get_source is stubbed to be owner-aware so the route wiring can be exercised
# without a real vector store.

_needs_auth = pytest.mark.skipif(not _HAS_API, reason="requires the 'api' extra (FastAPI)")


def _owner_aware_get_source(owned_by="alice-device"):
    """Return a get_source stub that reveals the chunk only to its owner/shared."""

    def _stub(chunk_id, owner=None):  # noqa: ARG001
        if owner is None or owner == owned_by:
            return _CHUNK
        return None

    return _stub


def _bearer(client, email, password="supersecret"):
    """Register then log in, returning an Authorization header dict."""
    client.post("/auth/register", json={"email": email, "password": password})
    token = client.post("/auth/login", json={"email": email, "password": password}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


@_needs_auth
def test_source_owner_sees_their_chunk(client, monkeypatch):
    pytest.importorskip("jwt")
    pytest.importorskip("bcrypt")
    monkeypatch.setattr(api_main, "get_source", _owner_aware_get_source())
    headers = _bearer(client, "srcowner@example.com")
    response = client.get("/source/known", params={"student_id": "alice-device"}, headers=headers)
    assert response.status_code == 200
    assert response.json() == _CHUNK


@_needs_auth
def test_source_foreign_authenticated_caller_gets_404(client, monkeypatch):
    # A logged-in caller who guesses another account's deterministic chunk id but
    # scopes with their own student id sees a 404, never the chunk (no leak).
    pytest.importorskip("jwt")
    pytest.importorskip("bcrypt")
    monkeypatch.setattr(api_main, "get_source", _owner_aware_get_source())
    headers = _bearer(client, "srcforeign@example.com")
    response = client.get("/source/known", params={"student_id": "bob-device"}, headers=headers)
    assert response.status_code == 404


@_needs_auth
def test_source_anonymous_unchanged(client, monkeypatch):
    # No auth, no student_id: the lookup stays unscoped (owner=None), unchanged.
    monkeypatch.setattr(api_main, "get_source", _owner_aware_get_source())
    response = client.get("/source/known")
    assert response.status_code == 200
    assert response.json() == _CHUNK
