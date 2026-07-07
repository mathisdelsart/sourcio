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

    def facet(self, *, collection_name, key, limit, facet_filter=None):  # noqa: ARG002
        hits = [
            SimpleNamespace(value="Wavelet Transform", count=10),
            SimpleNamespace(value="Algebra", count=3),
        ]
        return SimpleNamespace(hits=hits)


class _RaisingFacetClient:
    """A client whose facet raises (missing collection), to force the fallback."""

    def __init__(self, *args, **kwargs):
        pass

    def facet(self, *, collection_name, key, limit, facet_filter=None):  # noqa: ARG002
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

    def scroll(  # noqa: ARG002
        self, *, collection_name, limit, with_payload, with_vectors, offset, scroll_filter=None
    ):
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
    # A real caller always scopes by owner; the fake ignores the filter and returns
    # its presets, so this still exercises the facet/sort mechanics.
    _use_client(monkeypatch, _FakeFacetClient)
    assert courses_mod.list_courses(owner="tester") == ["Algebra", "Wavelet Transform"]


def test_list_courses_scopes_facet_strictly_to_owner(monkeypatch):
    class _CapturingFacetClient:
        last_filter = "unset"

        def __init__(self, *args, **kwargs):
            pass

        def facet(self, *, collection_name, key, facet_filter, limit):  # noqa: ARG002
            type(self).last_filter = facet_filter
            return SimpleNamespace(hits=[SimpleNamespace(value="C", count=1)])

    _use_client(monkeypatch, _CapturingFacetClient)
    courses_mod.list_courses(owner="uA")
    flt = _CapturingFacetClient.last_filter
    # Strict isolation: a single "owner == mine" must condition, no shared branch.
    assert flt is not None and flt.should is None and len(flt.must) == 1
    assert flt.must[0].key == "owner" and flt.must[0].match.value == "uA"


def test_list_courses_fail_closed_without_owner(monkeypatch):
    # No owner -> fail closed: return [] WITHOUT querying (never enumerate every
    # account's courses). The client's facet must not even be called.
    class _BoomFacetClient:
        def __init__(self, *args, **kwargs):
            pass

        def facet(self, *args, **kwargs):  # noqa: ARG002
            raise AssertionError("no Qdrant call must happen when the owner is None")

        def scroll(self, *args, **kwargs):  # noqa: ARG002
            raise AssertionError("no Qdrant call must happen when the owner is None")

    _use_client(monkeypatch, _BoomFacetClient)
    assert courses_mod.list_courses() == []
    assert courses_mod.list_courses(owner=None) == []


def test_list_courses_scroll_fallback_when_no_facet(monkeypatch):
    _use_client(monkeypatch, _ScrollOnlyClient)
    assert courses_mod.list_courses(owner="tester") == ["Algebra", "Wavelet Transform"]


def test_list_courses_empty_when_facet_raises(monkeypatch):
    # facet raises (missing collection) and the scroll fallback returns nothing.
    _use_client(monkeypatch, _RaisingFacetClient)
    assert courses_mod.list_courses(owner="tester") == []


def test_list_courses_empty_facet_response(monkeypatch):
    class _EmptyFacetClient:
        def __init__(self, *args, **kwargs):
            pass

        def facet(self, *, collection_name, key, limit, facet_filter=None):  # noqa: ARG002
            return SimpleNamespace(hits=[])

    _use_client(monkeypatch, _EmptyFacetClient)
    assert courses_mod.list_courses(owner="tester") == []


class _FilterAwareFacetClient:
    """A facet client that honours the strict owner filter against canned points.

    Each point has an ``owner`` and a ``course``; ``facet`` returns the distinct
    courses of the points that match the owner filter, so a test can assert an
    account discovers only its own courses (never another account's, never legacy).
    """

    points = [
        {"owner": "uA", "course": "Algebra"},
        {"owner": "uB", "course": "Biology"},
        {"owner": None, "course": "Legacy"},
    ]

    def __init__(self, *args, **kwargs):
        pass

    def facet(self, *, collection_name, key, facet_filter, limit):  # noqa: ARG002
        want = facet_filter.must[0].match.value if facet_filter is not None else None
        seen = {p["course"] for p in self.points if p["owner"] == want}
        return SimpleNamespace(hits=[SimpleNamespace(value=v, count=1) for v in seen])


def test_list_courses_cross_account_isolation(monkeypatch):
    _use_client(monkeypatch, _FilterAwareFacetClient)
    # uA sees only its own course; never uB's, never the owner-less legacy course.
    assert courses_mod.list_courses(owner="uA") == ["Algebra"]
    assert courses_mod.list_courses(owner="uB") == ["Biology"]


# --- list_chapters -----------------------------------------------------------


class _FakeChapterFacetClient:
    """A client whose facet returns preset chapter values (incl. a blank one)."""

    def __init__(self, *args, **kwargs):
        pass

    def facet(self, *, collection_name, key, limit, facet_filter=None):  # noqa: ARG002
        hits = [
            SimpleNamespace(value="Chapter 3", count=5),
            SimpleNamespace(value="Chapter 1", count=2),
            # A blank chapter (material indexed without one) must be dropped.
            SimpleNamespace(value="", count=1),
        ]
        return SimpleNamespace(hits=hits)


def test_list_chapters_uses_facet_sorted_distinct_non_empty(monkeypatch):
    _use_client(monkeypatch, _FakeChapterFacetClient)
    assert courses_mod.list_chapters("Algebra", owner="tester") == ["Chapter 1", "Chapter 3"]


def test_list_chapters_scopes_facet_to_course_and_owner(monkeypatch):
    class _CapturingFacetClient:
        last_filter = "unset"

        def __init__(self, *args, **kwargs):
            pass

        def facet(self, *, collection_name, key, facet_filter, limit):  # noqa: ARG002
            type(self).last_filter = (key, facet_filter)
            return SimpleNamespace(hits=[SimpleNamespace(value="C1", count=1)])

    _use_client(monkeypatch, _CapturingFacetClient)
    courses_mod.list_chapters("Algebra", owner="uA")
    key, flt = _CapturingFacetClient.last_filter
    assert key == "chapter"
    # Combined filter: course == Algebra AND (nested) owner == uA (strict isolation).
    assert flt is not None and flt.should is None and len(flt.must) == 2
    course_cond, owner_sub = flt.must
    assert course_cond.key == "course" and course_cond.match.value == "Algebra"
    # Owner scope is nested via owner_scope_filter: a sub-filter owner == uA.
    assert owner_sub.must[0].key == "owner" and owner_sub.must[0].match.value == "uA"


def test_list_chapters_fail_closed_without_owner(monkeypatch):
    # No owner -> fail closed: return [] WITHOUT querying (never enumerate every
    # account's chapters). The client must not even be constructed/queried.
    class _BoomFacetClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("no Qdrant client must be built when the owner is None")

    _use_client(monkeypatch, _BoomFacetClient)
    assert courses_mod.list_chapters("Algebra") == []
    assert courses_mod.list_chapters("Algebra", owner=None) == []


class _ChapterScrollOnlyClient:
    """A client without a facet API, exercising the paged scroll fallback."""

    facet = None

    def __init__(self, *args, **kwargs):
        pass

    def scroll(  # noqa: ARG002
        self, *, collection_name, limit, with_payload, with_vectors, offset, scroll_filter=None
    ):
        if offset is None:
            points = [
                SimpleNamespace(payload={"chapter": "Chapter 2"}),
                SimpleNamespace(payload={"chapter": "Chapter 2"}),
                SimpleNamespace(payload={}),  # no chapter -> skipped
            ]
            return points, "next"
        points = [
            SimpleNamespace(payload={"chapter": "Chapter 1"}),
            SimpleNamespace(payload=None),
        ]
        return points, None


def test_list_chapters_scroll_fallback_when_no_facet(monkeypatch):
    _use_client(monkeypatch, _ChapterScrollOnlyClient)
    assert courses_mod.list_chapters("Algebra", owner="tester") == ["Chapter 1", "Chapter 2"]


def test_list_chapters_empty_when_facet_raises(monkeypatch):
    # facet raises (missing collection) and the scroll fallback returns nothing.
    _use_client(monkeypatch, _RaisingFacetClient)
    assert courses_mod.list_chapters("Algebra", owner="tester") == []


class _ChapterFilterAwareFacetClient:
    """A facet client that honours the strict course+owner filter over points.

    Returns the distinct chapters of the points matching *both* the owner and the
    course in the filter, so a test can assert an account discovers only its own
    course's chapters (never another account's, another course's, or legacy).
    """

    points = [
        {"owner": "uA", "course": "Algebra", "chapter": "Ch A1"},
        {"owner": "uA", "course": "Algebra", "chapter": "Ch A2"},
        {"owner": "uA", "course": "Biology", "chapter": "Ch B"},  # other course
        {"owner": "uB", "course": "Algebra", "chapter": "Ch X"},  # other owner
        {"owner": None, "course": "Algebra", "chapter": "Legacy"},  # owner-less
    ]

    def __init__(self, *args, **kwargs):
        pass

    def facet(self, *, collection_name, key, facet_filter, limit):  # noqa: ARG002
        # course == <course> is flat; owner == <owner> is nested (owner_scope_filter).
        course_cond, owner_sub = facet_filter.must
        want_course = course_cond.match.value
        want_owner = owner_sub.must[0].match.value
        seen = {
            p["chapter"]
            for p in self.points
            if p["owner"] == want_owner and p["course"] == want_course
        }
        return SimpleNamespace(hits=[SimpleNamespace(value=v, count=1) for v in seen])


def test_list_chapters_cross_account_and_course_isolation(monkeypatch):
    _use_client(monkeypatch, _ChapterFilterAwareFacetClient)
    # uA sees only its own Algebra chapters; never uB's, never Biology, never legacy.
    assert courses_mod.list_chapters("Algebra", owner="uA") == ["Ch A1", "Ch A2"]
    assert courses_mod.list_chapters("Algebra", owner="uB") == ["Ch X"]


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
    monkeypatch.setattr(
        api_main, "list_courses", lambda owner=None: ["Algebra", "Wavelet Transform"]
    )
    response = client.get("/courses")
    assert response.status_code == 200
    assert response.json() == {"courses": ["Algebra", "Wavelet Transform"]}


@requires_api
def test_courses_route_empty(client, monkeypatch):
    monkeypatch.setattr(api_main, "list_courses", lambda owner=None: [])
    response = client.get("/courses")
    assert response.status_code == 200
    assert response.json() == {"courses": []}


@requires_api
def test_courses_open_when_no_key(client, monkeypatch):
    _set_api_key(monkeypatch, "")
    monkeypatch.setattr(api_main, "list_courses", lambda owner=None: ["Algebra"])
    response = client.get("/courses")
    assert response.status_code == 200


@requires_api
def test_courses_rejects_missing_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "list_courses", lambda owner=None: ["Algebra"])
    response = client.get("/courses")
    assert response.status_code == 401


@requires_api
def test_courses_rejects_wrong_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "list_courses", lambda owner=None: ["Algebra"])
    response = client.get("/courses", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


@requires_api
def test_courses_accepts_correct_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "list_courses", lambda owner=None: ["Algebra"])
    response = client.get("/courses", headers={"X-API-Key": "secret-key"})
    assert response.status_code == 200
    assert response.json() == {"courses": ["Algebra"]}


# --- /chapters route ---------------------------------------------------------


@requires_api
def test_chapters_route_returns_list(client, monkeypatch):
    monkeypatch.setattr(
        api_main, "list_chapters", lambda course, owner=None: ["Chapter 1", "Chapter 2"]
    )
    response = client.get("/chapters", params={"course": "Algebra"})
    assert response.status_code == 200
    assert response.json() == {"chapters": ["Chapter 1", "Chapter 2"]}


@requires_api
def test_chapters_route_requires_course(client):
    # `course` is a required query param: omitting it is a 422, not a silent read.
    response = client.get("/chapters")
    assert response.status_code == 422


@requires_api
def test_chapters_route_empty(client, monkeypatch):
    monkeypatch.setattr(api_main, "list_chapters", lambda course, owner=None: [])
    response = client.get("/chapters", params={"course": "Algebra"})
    assert response.status_code == 200
    assert response.json() == {"chapters": []}


@requires_api
def test_chapters_route_passes_course_to_core(client, monkeypatch):
    seen = {}

    def _fake(course, owner=None):
        seen["course"] = course
        return ["Ch"]

    monkeypatch.setattr(api_main, "list_chapters", _fake)
    client.get("/chapters", params={"course": "Wavelet Transform"})
    assert seen["course"] == "Wavelet Transform"


@requires_api
def test_chapters_rejects_missing_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "list_chapters", lambda course, owner=None: ["Chapter 1"])
    response = client.get("/chapters", params={"course": "Algebra"})
    assert response.status_code == 401


@requires_api
def test_chapters_accepts_correct_key(client, monkeypatch):
    _set_api_key(monkeypatch, "secret-key")
    monkeypatch.setattr(api_main, "list_chapters", lambda course, owner=None: ["Chapter 1"])
    response = client.get(
        "/chapters", params={"course": "Algebra"}, headers={"X-API-Key": "secret-key"}
    )
    assert response.status_code == 200
    assert response.json() == {"chapters": ["Chapter 1"]}
