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
    """A Qdrant client whose ``retrieve`` returns one preset (owned) point.

    The known point is owned by ``tester`` so a strictly owner-scoped lookup with
    that owner resolves it; this exercises the payload-mapping mechanics.
    """

    def __init__(self, *args, **kwargs):
        pass

    def retrieve(self, *, collection_name, ids, with_payload, with_vectors):  # noqa: ARG002
        if ids == ["known"]:
            point = SimpleNamespace(
                id="known",
                payload={
                    "owner": "tester",
                    "course": "Wavelet Transform",
                    "chapter": "Ch.3",
                    "page": 12,
                    "text": "A wavelet is a localized oscillation.",
                },
            )
            return [point]
        return []


class _OwnerlessRetrieveClient:
    """A client whose known point carries NO owner (legacy/CLI corpus)."""

    def __init__(self, *args, **kwargs):
        pass

    def retrieve(self, *, collection_name, ids, with_payload, with_vectors):  # noqa: ARG002
        point = SimpleNamespace(
            id="legacy",
            payload={
                "course": "Wavelet Transform",
                "chapter": "Ch.3",
                "page": 12,
                "text": "A wavelet is a localized oscillation.",
            },
        )
        return [point]


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
    # A real caller always scopes by owner; the known point is owned by "tester".
    _use_client(monkeypatch, _FakeRetrieveClient)
    assert sources_mod.get_source("known", owner="tester") == {
        "id": "known",
        "course": "Wavelet Transform",
        "chapter": "Ch.3",
        "page": 12,
        "text": "A wavelet is a localized oscillation.",
    }


def test_get_source_none_for_unknown_id(monkeypatch):
    _use_client(monkeypatch, _FakeRetrieveClient)
    assert sources_mod.get_source("missing", owner="tester") is None


def test_get_source_none_when_retrieve_raises(monkeypatch):
    # A missing collection / unreachable server is treated as "not found".
    _use_client(monkeypatch, _RaisingRetrieveClient)
    assert sources_mod.get_source("known", owner="tester") is None


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


def test_get_source_fail_closed_without_owner(monkeypatch):
    # No owner -> fail closed: return None WITHOUT querying Qdrant. Even a raising
    # client is never reached, so short-circuiting is what returns None here.
    _use_client(monkeypatch, _RaisingRetrieveClient)
    assert sources_mod.get_source("owned") is None
    assert sources_mod.get_source("owned", owner=None) is None


def test_get_source_legacy_chunk_invisible_to_owner(monkeypatch):
    # Strict isolation: an owner-less (legacy/CLI) chunk is NOT visible to any
    # specific account -- it is reported as absent.
    _use_client(monkeypatch, _OwnerlessRetrieveClient)
    assert sources_mod.get_source("legacy", owner="alice") is None


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
    """Return a get_source stub with strict, fail-closed owner semantics.

    Reveals the chunk only to its exact owner; a foreign owner or a ``None`` owner
    (no identity) is treated as absent, mirroring the real fail-closed lookup.
    """

    def _stub(chunk_id, owner=None):  # noqa: ARG001
        if owner is not None and owner == owned_by:
            return _CHUNK
        return None

    return _stub


def _bearer(client, username, password="supersecret"):
    """Register then log in, returning an Authorization header dict."""
    client.post("/auth/register", json={"username": username, "password": password})
    token = client.post("/auth/login", json={"username": username, "password": password}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


@_needs_auth
def test_source_owner_sees_their_chunk(client, monkeypatch):
    pytest.importorskip("jwt")
    pytest.importorskip("bcrypt")
    monkeypatch.setattr(api_main, "get_source", _owner_aware_get_source())
    headers = _bearer(client, "srcowner")
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
    headers = _bearer(client, "srcforeign")
    response = client.get("/source/known", params={"student_id": "bob-device"}, headers=headers)
    assert response.status_code == 404


@_needs_auth
def test_source_no_identity_fails_closed(client, monkeypatch):
    # No auth, no student_id: no identity -> owner=None -> fail closed (404),
    # never an unscoped lookup that could reveal any account's chunk.
    monkeypatch.setattr(api_main, "get_source", _owner_aware_get_source())
    response = client.get("/source/known")
    assert response.status_code == 404
