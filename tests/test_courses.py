"""Tests for course discovery (``core.courses``) and the ``GET /courses`` route.

No real Qdrant, LLM, or network call is made: the ``QdrantClient`` is replaced
with a fake exposing only ``facet``/``scroll``, and the API is bound to an
in-memory SQLite database. The facet path, the scroll fallback, and graceful
handling of an empty/missing collection are all exercised in isolation.
"""

from types import SimpleNamespace

import pytest

import core.courses as courses_mod


class _FakeFacetClient:
    """A Qdrant client whose facet API returns preset distinct course values."""

    def __init__(self, *args, **kwargs):
        pass

    def facet(self, *, collection_name, key, limit):  # noqa: ARG002
        hits = [
            SimpleNamespace(value="Wavelet Transform", count=10),
            SimpleNamespace(value="Algebra", count=3),
        ]
        return SimpleNamespace(hits=hits)


class _RaisingFacetClient:
    """A client whose facet raises (missing collection), to force the fallback."""

    def __init__(self, *args, **kwargs):
        pass

    def facet(self, *, collection_name, key, limit):  # noqa: ARG002
        raise RuntimeError("collection not found")

    def scroll(self, **kwargs):  # noqa: ARG002
        return [], None


class _ScrollOnlyClient:
    """A client without a facet API, exercising the paged scroll fallback.

    Returns two pages of points (some without a ``course`` payload) then signals
    the end with a ``None`` offset, so the fallback must page and de-duplicate.
    """

    facet = None

    def __init__(self, *args, **kwargs):
        self.calls = 0

    def scroll(self, *, collection_name, limit, with_payload, with_vectors, offset):  # noqa: ARG002
        self.calls += 1
        if offset is None:
            points = [
                SimpleNamespace(payload={"course": "Algebra"}),
                SimpleNamespace(payload={"course": "Algebra"}),
                SimpleNamespace(payload={}),
            ]
            return points, "next"
        points = [
            SimpleNamespace(payload={"course": "Wavelet Transform"}),
            SimpleNamespace(payload=None),
        ]
        return points, None


def _use_client(monkeypatch, client_cls):
    """Patch the QdrantClient symbol used inside ``list_courses``."""
    import qdrant_client

    monkeypatch.setattr(qdrant_client, "QdrantClient", client_cls)


def test_list_courses_uses_facet_sorted_distinct(monkeypatch):
    _use_client(monkeypatch, _FakeFacetClient)
    assert courses_mod.list_courses() == ["Algebra", "Wavelet Transform"]


def test_list_courses_scroll_fallback_when_no_facet(monkeypatch):
    _use_client(monkeypatch, _ScrollOnlyClient)
    assert courses_mod.list_courses() == ["Algebra", "Wavelet Transform"]


def test_list_courses_empty_when_facet_raises(monkeypatch):
    # facet raises (missing collection) and the scroll fallback returns nothing.
    _use_client(monkeypatch, _RaisingFacetClient)
    assert courses_mod.list_courses() == []


def test_list_courses_empty_facet_response(monkeypatch):
    class _EmptyFacetClient:
        def __init__(self, *args, **kwargs):
            pass

        def facet(self, *, collection_name, key, limit):  # noqa: ARG002
            return SimpleNamespace(hits=[])

    _use_client(monkeypatch, _EmptyFacetClient)
    assert courses_mod.list_courses() == []


# --- /courses route ----------------------------------------------------------
# Gated on the optional `api` extra (FastAPI). The core `list_courses` tests
# above always run; only the route tests below need the API stack installed.

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
def test_courses_route_returns_list(client, monkeypatch):
    monkeypatch.setattr(api_main, "list_courses", lambda: ["Algebra", "Wavelet Transform"])
    response = client.get("/courses")
    assert response.status_code == 200
    assert response.json() == {"courses": ["Algebra", "Wavelet Transform"]}


@requires_api
def test_courses_route_empty(client, monkeypatch):
    monkeypatch.setattr(api_main, "list_courses", lambda: [])
    response = client.get("/courses")
    assert response.status_code == 200
    assert response.json() == {"courses": []}


@requires_api
def test_courses_open_when_no_key(client, monkeypatch):
    _set_api_key(monkeypatch, "")
    monkeypatch.setattr(api_main, "list_courses", lambda: ["Algebra"])
    response = client.get("/courses")
    assert response.status_code == 200


@requires_api
def test_courses_rejects_missing_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "list_courses", lambda: ["Algebra"])
    response = client.get("/courses")
    assert response.status_code == 401


@requires_api
def test_courses_rejects_wrong_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "list_courses", lambda: ["Algebra"])
    response = client.get("/courses", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


@requires_api
def test_courses_accepts_correct_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "list_courses", lambda: ["Algebra"])
    response = client.get("/courses", headers={"X-API-Key": "secret-key"})
    assert response.status_code == 200
    assert response.json() == {"courses": ["Algebra"]}
