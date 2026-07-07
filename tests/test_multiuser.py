"""Tests for the opt-in enforced multi-user mode (``REQUIRE_AUTH``).

When the flag is OFF (the default) the API stays anonymous: callers are keyed by
a device ``student_id`` and authentication is optional, exactly as in the MVP —
the regression guard below asserts this. When the flag is ON, every data
endpoint requires a valid bearer token (401 otherwise) and enforces per-user
student ownership: a caller can only touch students that belong to their own
account (403 on a foreign student), giving true tenant isolation.

No LLM, vector store, or network call is involved: the grounded function is
monkeypatched and the API is bound to an in-memory SQLite database. The flag is
toggled by monkeypatching ``api.main.get_settings`` (the same cache-safe pattern
used by the API-key tests), so no process environment or lru-cache is touched.
The module is skipped when the optional ``api`` extra is not installed.
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("jwt")
pytest.importorskip("bcrypt")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import api.main as api_main  # noqa: E402
from api.main import app  # noqa: E402
from core.config import Settings  # noqa: E402
from db.models import Student  # noqa: E402
from db.session import get_session  # noqa: E402


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


@pytest.fixture(autouse=True)
def _stub_answer(monkeypatch):
    """Stub the grounded answer so /ask never reaches an LLM or vector store."""
    monkeypatch.setattr(
        api_main,
        "answer",
        lambda question, *, k=5, course=None, chapter=None, owner=None, language=None: {
            "answer": "ok",
            "refused": False,
            "sources": [],
            "raw": "ok",
        },
    )


def _set_require_auth(monkeypatch, value):
    """Toggle enforced multi-user mode without touching the real cached settings.

    The flag-aware dependency and the ownership helpers all call
    ``get_settings()`` from the ``api.main`` namespace, so replacing it there is
    enough. The default (unmonkeypatched) settings keep ``require_auth`` False, so
    every other test keeps running in the anonymous MVP mode.
    """
    settings = Settings(require_auth=value)
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)


def _token(client, username="owner", password="supersecret"):
    """Register then log in, returning a bearer access token."""
    client.post("/auth/register", json={"username": username, "password": password})
    return client.post("/auth/login", json={"username": username, "password": password}).json()[
        "access_token"
    ]


def _auth(token):
    """Build an Authorization header for a bearer token."""
    return {"Authorization": f"Bearer {token}"}


def _student(external_id):
    """Load the persisted student by its external id (or None)."""
    with get_session(api_main._engine) as session:
        return session.scalar(select(Student).where(Student.external_id == external_id))


# --- require_auth ON: a bearer token is mandatory ----------------------------


def test_data_endpoints_require_token_when_enforced(client, monkeypatch):
    # Register/login must happen while the flag is off (the real jwt_secret is
    # used for both signing and verifying regardless), then enforce.
    _set_require_auth(monkeypatch, True)
    assert client.post("/ask", json={"student_id": "s", "question": "q"}).status_code == 401
    assert client.get("/history/s").status_code == 401
    assert client.get("/sessions/s").status_code == 401


def test_broken_token_is_rejected_when_enforced(client, monkeypatch):
    _set_require_auth(monkeypatch, True)
    response = client.post(
        "/ask",
        json={"student_id": "s", "question": "q"},
        headers={"Authorization": "Bearer not.a.jwt"},
    )
    assert response.status_code == 401


# --- require_auth ON: per-user tenant isolation ------------------------------


def test_owner_can_use_student_but_foreign_user_is_forbidden(client, monkeypatch):
    token_a = _token(client, "usera")
    token_b = _token(client, "userb")
    _set_require_auth(monkeypatch, True)

    # A claims the student and can read its history.
    assert (
        client.post(
            "/ask", json={"student_id": "a-device", "question": "q"}, headers=_auth(token_a)
        ).status_code
        == 200
    )
    assert client.get("/history/a-device", headers=_auth(token_a)).status_code == 200

    # B is rejected on both a write and a read of A's student.
    write = client.post(
        "/ask", json={"student_id": "a-device", "question": "q"}, headers=_auth(token_b)
    )
    assert write.status_code == 403
    read = client.get("/history/a-device", headers=_auth(token_b))
    assert read.status_code == 403


def test_first_authenticated_caller_claims_unclaimed_student(client, monkeypatch):
    token = _token(client, "claimer")
    me = client.get("/auth/me", headers=_auth(token)).json()
    _set_require_auth(monkeypatch, True)

    response = client.post(
        "/ask", json={"student_id": "fresh", "question": "q"}, headers=_auth(token)
    )
    assert response.status_code == 200
    assert _student("fresh").user_id == me["id"]


def test_stream_rejects_foreign_student_before_streaming(client, monkeypatch):
    def _fake_stream(question, *, k=5, course=None, chapter=None, owner=None, language=None):
        yield {"type": "sources", "sources": [], "refused": False, "answer": "ok"}

    monkeypatch.setattr(api_main, "stream_answer", _fake_stream)
    token_a = _token(client, "streama")
    token_b = _token(client, "streamb")
    _set_require_auth(monkeypatch, True)

    client.post("/ask", json={"student_id": "sa-device", "question": "q"}, headers=_auth(token_a))
    response = client.post(
        "/ask/stream", json={"student_id": "sa-device", "question": "q"}, headers=_auth(token_b)
    )
    assert response.status_code == 403


# --- GET /config -------------------------------------------------------------


def test_config_reports_require_auth_true_without_auth(client, monkeypatch):
    _set_require_auth(monkeypatch, True)
    response = client.get("/config")
    assert response.status_code == 200
    assert response.json() == {"require_auth": True}


def test_config_reports_require_auth_false_by_default(client):
    response = client.get("/config")
    assert response.status_code == 200
    assert response.json() == {"require_auth": False}


# --- require_auth OFF (default): anonymous flow is unchanged ------------------


def test_anonymous_flow_still_works_when_disabled(client):
    # Explicit regression guard: with the flag off (default), no token is needed.
    assert client.post("/ask", json={"student_id": "anon", "question": "q"}).status_code == 200
    history = client.get("/history/anon")
    assert history.status_code == 200
    assert [turn["role"] for turn in history.json()] == ["user", "assistant"]
    assert _student("anon").user_id is None


# --- Cross-account document isolation (the reported leak) --------------------


def _owner_scoped_documents(corpus):
    """Build a list_documents stub that returns only the given owner's material.

    ``corpus`` maps ``owner -> [course names]``. Mirrors the real strict scoping:
    a listing only ever contains the caller's own courses, never another
    account's — even when a course name is shared between accounts.
    """

    def _stub(owner=None):
        if owner is None:  # fail closed: no identity -> nothing
            return []
        return [
            {"course": name, "total_pages": 1, "chapters": [], "files": []}
            for name in corpus.get(owner, [])
        ]

    return _stub


def test_documents_do_not_leak_across_accounts_when_enforced(client, monkeypatch):
    # Reproduces the reported bug: account A must never see account B's documents,
    # and a course name shared by both must not leak B's material into A's listing.
    corpus = {
        "a-device": ["Wavelets", "Shared"],
        "b-device": ["Biology", "Shared"],
    }
    monkeypatch.setattr(api_main, "list_documents", _owner_scoped_documents(corpus))
    monkeypatch.setattr(api_main, "list_courses", lambda owner=None: sorted(corpus.get(owner, [])))

    token_a = _token(client, "doca")
    token_b = _token(client, "docb")
    _set_require_auth(monkeypatch, True)

    # Each account claims its own device student, then lists documents.
    a_docs = client.get("/documents", params={"student_id": "a-device"}, headers=_auth(token_a))
    b_docs = client.get("/documents", params={"student_id": "b-device"}, headers=_auth(token_b))
    assert a_docs.status_code == 200 and b_docs.status_code == 200
    a_courses = {c["course"] for c in a_docs.json()}
    b_courses = {c["course"] for c in b_docs.json()}

    # A sees only its own courses (incl. its own "Shared"), never B's "Biology".
    assert a_courses == {"Wavelets", "Shared"}
    assert "Biology" not in a_courses
    assert b_courses == {"Biology", "Shared"}
    assert "Wavelets" not in b_courses

    # Same guarantee on the course picker (GET /courses).
    a_list = client.get("/courses", params={"student_id": "a-device"}, headers=_auth(token_a))
    assert set(a_list.json()["courses"]) == {"Shared", "Wavelets"}


def test_documents_reject_foreign_student_id_when_enforced(client, monkeypatch):
    # A logged-in caller cannot list another account's documents by passing that
    # account's student_id: ownership is enforced with a 403 before any read.
    monkeypatch.setattr(api_main, "list_documents", _owner_scoped_documents({"b-device": ["B"]}))

    token_a = _token(client, "forbida")
    token_b = _token(client, "forbidb")
    # B claims its device student first.
    _set_require_auth(monkeypatch, True)
    client.post("/ask", json={"student_id": "b-device", "question": "q"}, headers=_auth(token_b))

    # A tries to read B's material by passing B's student_id -> 403, never B's docs.
    stolen = client.get("/documents", params={"student_id": "b-device"}, headers=_auth(token_a))
    assert stolen.status_code == 403


def test_chapters_reject_foreign_student_id_when_enforced(client, monkeypatch):
    # A logged-in caller cannot list another account's chapters by passing that
    # account's student_id: ownership is enforced with a 403 before any read.
    monkeypatch.setattr(api_main, "list_chapters", lambda course, owner=None: ["Ch"])

    token_a = _token(client, "cha@example.com")
    token_b = _token(client, "chb@example.com")
    _set_require_auth(monkeypatch, True)
    # B claims its device student first.
    client.post("/ask", json={"student_id": "b-device", "question": "q"}, headers=_auth(token_b))

    # A tries to read B's chapters by passing B's student_id -> 403, never B's data.
    stolen = client.get(
        "/chapters",
        params={"course": "X", "student_id": "b-device"},
        headers=_auth(token_a),
    )
    assert stolen.status_code == 403
