"""Tests for per-user data ownership (students linked to accounts).

Ownership is fully local: a logged-in user (bearer JWT) who hits a tutor
endpoint has the resolved ``Student`` linked to their account, while anonymous
requests keep creating unlinked students exactly as before. No LLM, vector
store, or network call is involved: the grounded function is monkeypatched and
the API is bound to an in-memory SQLite database. The module is skipped when the
optional ``api`` extra (FastAPI) is not installed, so CI without extras collects
cleanly.
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


def _token(client, username="owner", password="supersecret"):
    """Register then log in, returning a bearer access token."""
    client.post("/auth/register", json={"username": username, "password": password})
    return client.post("/auth/login", json={"username": username, "password": password}).json()[
        "access_token"
    ]


def _student(external_id):
    """Load the persisted student by its external id (or None)."""
    with get_session(api_main._engine) as session:
        return session.scalar(select(Student).where(Student.external_id == external_id))


# --- ownership linking -------------------------------------------------------


def test_authenticated_ask_links_student_to_user(client):
    token = _token(client, "alice")
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()

    response = client.post(
        "/ask",
        json={"student_id": "alice-device", "question": "q"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    student = _student("alice-device")
    assert student is not None
    assert student.user_id == me["id"]


def test_authenticated_exercise_links_student_to_user(client, monkeypatch):
    monkeypatch.setattr(
        api_main,
        "generate",
        lambda state: {"exercise": {"problem": "p", "refused": False, "id": 1}},
    )
    token = _token(client, "bob")
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()

    response = client.post(
        "/exercise",
        json={"student_id": "bob-device", "notion": "wavelets"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert _student("bob-device").user_id == me["id"]


def test_anonymous_ask_creates_unlinked_student(client):
    response = client.post("/ask", json={"student_id": "anon", "question": "q"})
    assert response.status_code == 200

    student = _student("anon")
    assert student is not None
    assert student.user_id is None


def test_existing_student_of_another_user_is_forbidden(client):
    # First user claims the student.
    token_a = _token(client, "first")
    me_a = client.get("/auth/me", headers={"Authorization": f"Bearer {token_a}"}).json()
    client.post(
        "/ask",
        json={"student_id": "shared", "question": "q"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert _student("shared").user_id == me_a["id"]

    # A second logged-in user touching the same student id is rejected with 403,
    # even with REQUIRE_AUTH off: being logged in always isolates. Ownership never
    # changes hands.
    token_b = _token(client, "second")
    response = client.post(
        "/ask",
        json={"student_id": "shared", "question": "q"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403
    assert _student("shared").user_id == me_a["id"]


def test_foreign_ask_is_rejected_before_answer_runs(client, monkeypatch):
    # L2: a foreign student id must 403 *before* any retrieval/LLM work. The
    # answer stub records whether it was invoked; it must stay untouched.
    calls: list[str] = []

    def _tracking_answer(question, *, k=5, course=None, chapter=None, owner=None, language=None):
        calls.append(question)
        return {"answer": "ok", "refused": False, "sources": [], "raw": "ok"}

    monkeypatch.setattr(api_main, "answer", _tracking_answer)

    # User A claims the student.
    token_a = _token(client, "l2a")
    client.post(
        "/ask",
        json={"student_id": "l2-shared", "question": "q"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert calls == ["q"]
    calls.clear()

    # User B touching A's student id is rejected with 403 and answer never runs.
    token_b = _token(client, "l2b")
    response = client.post(
        "/ask",
        json={"student_id": "l2-shared", "question": "leak?"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403
    assert calls == []


def test_logged_in_user_cannot_read_another_users_student(client):
    # Isolation on reads holds with REQUIRE_AUTH off too: user A owns the student,
    # user B is forbidden from reading its history.
    token_a = _token(client, "reada")
    token_b = _token(client, "readb")
    client.post(
        "/ask",
        json={"student_id": "a-owned", "question": "q"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert (
        client.get("/history/a-owned", headers={"Authorization": f"Bearer {token_a}"}).status_code
        == 200
    )
    assert (
        client.get("/history/a-owned", headers={"Authorization": f"Bearer {token_b}"}).status_code
        == 403
    )


# --- GET /me/students --------------------------------------------------------


def test_me_students_returns_only_callers_students(client):
    token_a = _token(client, "carol")
    token_b = _token(client, "dave")

    client.post(
        "/ask",
        json={"student_id": "carol-1", "question": "q"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    client.post(
        "/ask",
        json={"student_id": "carol-2", "question": "q"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    client.post(
        "/ask",
        json={"student_id": "dave-1", "question": "q"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    # An anonymous student must never surface in any user's list.
    client.post("/ask", json={"student_id": "anon", "question": "q"})

    response = client.get("/me/students", headers={"Authorization": f"Bearer {token_a}"})
    assert response.status_code == 200
    external_ids = {row["external_id"] for row in response.json()}
    assert external_ids == {"carol-1", "carol-2"}


def test_me_students_requires_token(client):
    assert client.get("/me/students").status_code == 401


def test_me_students_invalid_token_is_401(client):
    response = client.get("/me/students", headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401


# --- additive / backward-compatible ------------------------------------------


def test_anonymous_endpoints_work_without_auth(client):
    # The nullable column and optional-user dependency must not break the
    # existing anonymous flow: /ask, /history still respond normally.
    assert client.post("/ask", json={"student_id": "s1", "question": "q"}).status_code == 200
    history = client.get("/history/s1")
    assert history.status_code == 200
    assert [turn["role"] for turn in history.json()] == ["user", "assistant"]


def test_ask_with_broken_bearer_is_rejected(client):
    # A present-but-invalid token must not silently degrade to anonymous access.
    response = client.post(
        "/ask",
        json={"student_id": "s1", "question": "q"},
        headers={"Authorization": "Bearer not.a.jwt"},
    )
    assert response.status_code == 401


def test_logged_in_user_cannot_review_another_users_exercise(client, monkeypatch):
    # Review is ownership-gated like the other read routes: user A generates an
    # exercise, user B is forbidden from reviewing it (403), even with auth off.
    monkeypatch.setattr(
        api_main,
        "generate",
        lambda state: {"exercise": {"problem": "p", "solution": "s", "refused": False, "id": 1}},
    )
    token_a = _token(client, "exa")
    token_b = _token(client, "exb")
    ex = client.post(
        "/exercise",
        json={"student_id": "exa-owned", "notion": "groups"},
        headers={"Authorization": f"Bearer {token_a}"},
    ).json()
    # Owner can review (200 or 404 if the stubbed node did not persist a row);
    # the foreign user is always forbidden before any lookup.
    forbidden = client.get(
        f"/exercise/{ex['id'] or 1}/review",
        params={"student_id": "exa-owned"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert forbidden.status_code == 403


# --- background answer jobs (/ask/async, /ask/jobs) --------------------------


def _wait_for_ask_job(client, job_id, student_id, token=None, *, timeout=5.0):
    """Poll the ask-job endpoint until the worker thread reaches a terminal status."""
    import time

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(
            f"/ask/jobs/{job_id}", params={"student_id": student_id}, headers=headers
        )
        assert response.status_code == 200
        job = response.json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"ask job {job_id} did not finish within {timeout}s")


def test_foreign_caller_cannot_read_another_users_ask_job(client, monkeypatch):
    # A background answer job is owner-scoped: a second logged-in user cannot poll
    # a job started for another account's student, even with the right id.
    def fake_stream_answer(question, *, k=5, course=None, chapter=None, owner=None, language=None):
        yield {"type": "token", "text": "grounded [1]"}
        yield {
            "type": "sources",
            "sources": ["(Course, p.1)"],
            "citations": [{"n": 1, "id": "c1", "label": "(Course, p.1)"}],
            "refused": False,
            "answer": "grounded [1]",
        }

    monkeypatch.setattr(api_main, "stream_answer", fake_stream_answer)

    token_a = _token(client, "joba")
    started = client.post(
        "/ask/async",
        json={"student_id": "joba-owned", "question": "q"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    # Owner reads it (and it finishes fine).
    finished = _wait_for_ask_job(client, job_id, "joba-owned", token_a)
    assert finished["status"] == "done"

    # User B, presenting A's student id, is rejected with 403 before any lookup.
    token_b = _token(client, "jobb")
    forbidden = client.get(
        f"/ask/jobs/{job_id}",
        params={"student_id": "joba-owned"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert forbidden.status_code == 403
