"""Tests for the conversation-session (thread) endpoints.

No LLM, vector store, or network call is involved: sessions are pure
persistence and the optional ``/ask`` attachment is exercised with the answer
function patched to a stub. The API is bound to an in-memory SQLite database so
the routes run in isolation. The module is skipped when the optional ``api``
extra (FastAPI) is not installed, so CI without extras collects cleanly.
"""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import api.main as api_main  # noqa: E402
from api.main import app  # noqa: E402
from db.models import Message as MessageModel  # noqa: E402
from db.models import Session as SessionModel  # noqa: E402


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


# --- create / list -----------------------------------------------------------


def test_create_session_returns_thread(client):
    response = client.post("/sessions", json={"student_id": "s1", "title": "Wavelets"})
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], int)
    assert body["title"] == "Wavelets"
    assert body["created_at"]


def test_create_session_allows_untitled(client):
    response = client.post("/sessions", json={"student_id": "s1"})
    assert response.status_code == 201
    assert response.json()["title"] is None


def test_list_sessions_newest_first(client):
    first = client.post("/sessions", json={"student_id": "s1", "title": "A"}).json()
    second = client.post("/sessions", json={"student_id": "s1", "title": "B"}).json()

    response = client.get("/sessions/s1")
    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert ids == [second["id"], first["id"]]


def test_list_sessions_unknown_student_is_empty(client):
    response = client.get("/sessions/nobody")
    assert response.status_code == 200
    assert response.json() == []


def test_list_sessions_scoped_to_student(client):
    client.post("/sessions", json={"student_id": "s1", "title": "A"})
    client.post("/sessions", json={"student_id": "s2", "title": "B"})

    rows = client.get("/sessions/s1").json()
    assert [row["title"] for row in rows] == ["A"]


# --- messages scoped to a thread ---------------------------------------------


def test_session_messages_unknown_thread_404(client):
    client.post("/sessions", json={"student_id": "s1"})
    response = client.get("/sessions/s1/9999/messages")
    assert response.status_code == 404


def test_session_messages_cross_student_404(client):
    thread = client.post("/sessions", json={"student_id": "s1"}).json()
    # s2 cannot read s1's thread.
    response = client.get(f"/sessions/s2/{thread['id']}/messages")
    assert response.status_code == 404


def test_session_messages_chronological(client):
    thread = client.post("/sessions", json={"student_id": "s1"}).json()
    # Seed messages directly so the test needs no LLM.
    with api_main.get_session(api_main._engine) as session:
        from db.session import add_message, get_or_create_student

        student = get_or_create_student(session, "s1")
        add_message(
            session,
            student_id=student.id,
            role="user",
            content="first",
            session_id=thread["id"],
        )
        add_message(
            session,
            student_id=student.id,
            role="assistant",
            content="second",
            session_id=thread["id"],
        )

    response = client.get(f"/sessions/s1/{thread['id']}/messages")
    assert response.status_code == 200
    rows = response.json()
    assert [row["content"] for row in rows] == ["first", "second"]
    assert [row["role"] for row in rows] == ["user", "assistant"]


# --- /ask attaches to a thread -----------------------------------------------


def _stub_answer(monkeypatch):
    """Patch the answer function so /ask runs without an LLM or Qdrant."""
    monkeypatch.setattr(
        api_main,
        "answer",
        lambda *a, **k: {"answer": "Grounded reply.", "refused": False, "sources": []},
    )


def test_ask_attaches_turn_to_session(client, monkeypatch):
    _stub_answer(monkeypatch)
    thread = client.post("/sessions", json={"student_id": "s1"}).json()

    response = client.post(
        "/ask",
        json={"student_id": "s1", "question": "What is a wavelet?", "session_id": thread["id"]},
    )
    assert response.status_code == 200

    # The two turns are attached to the thread, and the thread messages endpoint
    # returns them in order.
    rows = client.get(f"/sessions/s1/{thread['id']}/messages").json()
    assert [row["content"] for row in rows] == ["What is a wavelet?", "Grounded reply."]

    with api_main.get_session(api_main._engine) as session:
        msgs = session.scalars(
            select(MessageModel).where(MessageModel.session_id == thread["id"])
        ).all()
        assert len(msgs) == 2
        assert all(m.session_id == thread["id"] for m in msgs)


def test_ask_without_session_stays_unthreaded(client, monkeypatch):
    _stub_answer(monkeypatch)
    response = client.post("/ask", json={"student_id": "s1", "question": "q"})
    assert response.status_code == 200

    with api_main.get_session(api_main._engine) as session:
        msgs = session.scalars(select(MessageModel)).all()
        assert len(msgs) == 2
        assert all(m.session_id is None for m in msgs)


def test_ask_with_foreign_session_is_treated_as_unthreaded(client, monkeypatch):
    _stub_answer(monkeypatch)
    thread = client.post("/sessions", json={"student_id": "s1"}).json()
    # s2 references s1's thread (or a stale id): the request succeeds and the
    # turn is simply unthreaded rather than failing with 404.
    response = client.post(
        "/ask",
        json={"student_id": "s2", "question": "q", "session_id": thread["id"]},
    )
    assert response.status_code == 200
    # The message was not attached to s1's thread.
    assert client.get(f"/sessions/s1/{thread['id']}/messages").json() == []


def test_exercise_and_quiz_activity_attach_to_session(client, monkeypatch):
    # Exercise and quiz activity items are filed under the active thread, just
    # like /ask turns, and carry their distinct roles.
    monkeypatch.setattr(
        api_main,
        "generate",
        lambda state: {
            "exercise": {"problem": "Compute X.", "solution": "s", "refused": False},
            "retrieved": [],
        },
    )
    monkeypatch.setattr(
        api_main,
        "generate_quiz",
        lambda notion, n, student_id, *, course=None, chapter=None, language=None: {
            "quiz_id": 1,
            "notion": notion,
            "questions": [{"id": 1, "problem": "Q1?"}],
            "refused": False,
        },
    )
    thread = client.post("/sessions", json={"student_id": "s1"}).json()

    client.post(
        "/exercise",
        json={"student_id": "s1", "notion": "limits", "session_id": thread["id"]},
    )
    client.post(
        "/quiz",
        json={"student_id": "s1", "notion": "groups", "n": 1, "session_id": thread["id"]},
    )

    rows = client.get(f"/sessions/s1/{thread['id']}/messages").json()
    assert [(row["role"], row["content"]) for row in rows] == [
        ("exercise", "Compute X."),
        ("quiz", "groups (1 question)"),
    ]


# --- existing flat history unaffected ----------------------------------------


def test_flat_history_still_works(client, monkeypatch):
    _stub_answer(monkeypatch)
    client.post("/ask", json={"student_id": "s1", "question": "q1"})
    thread = client.post("/sessions", json={"student_id": "s1"}).json()
    client.post(
        "/ask",
        json={"student_id": "s1", "question": "q2", "session_id": thread["id"]},
    )

    # The flat history returns all turns regardless of thread.
    rows = client.get("/history/s1").json()
    contents = [row["content"] for row in rows]
    assert "q1" in contents
    assert "q2" in contents


def test_delete_thread_removes_its_messages(client, monkeypatch):
    _stub_answer(monkeypatch)
    thread = client.post("/sessions", json={"student_id": "s1"}).json()
    client.post(
        "/ask",
        json={"student_id": "s1", "question": "q-threaded", "session_id": thread["id"]},
    )

    resp = client.delete(f"/sessions/s1/{thread['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}

    # The thread is gone...
    assert client.get(f"/sessions/s1/{thread['id']}/messages").status_code == 404
    assert client.get("/sessions/s1").json() == []
    # ...and its messages are gone too — no longer in the flat history.
    contents = [row["content"] for row in client.get("/history/s1").json()]
    assert "q-threaded" not in contents


def test_delete_thread_keeps_unthreaded_history(client, monkeypatch):
    _stub_answer(monkeypatch)
    client.post("/ask", json={"student_id": "s1", "question": "q-flat"})
    thread = client.post("/sessions", json={"student_id": "s1"}).json()
    client.post(
        "/ask",
        json={"student_id": "s1", "question": "q-threaded", "session_id": thread["id"]},
    )

    client.delete(f"/sessions/s1/{thread['id']}")

    # Only the thread's messages are removed; unthreaded turns stay.
    contents = [row["content"] for row in client.get("/history/s1").json()]
    assert "q-flat" in contents
    assert "q-threaded" not in contents


def test_delete_unknown_thread_404(client):
    assert client.delete("/sessions/s1/999").status_code == 404


# --- clear history -----------------------------------------------------------


def test_clear_history_removes_all_messages(client, monkeypatch):
    _stub_answer(monkeypatch)
    client.post("/ask", json={"student_id": "s1", "question": "q-flat"})
    thread = client.post("/sessions", json={"student_id": "s1"}).json()
    client.post(
        "/ask",
        json={"student_id": "s1", "question": "q-threaded", "session_id": thread["id"]},
    )

    resp = client.delete("/history/s1")
    assert resp.status_code == 200
    # Two turns (user + assistant) for each of the two questions.
    assert resp.json() == {"deleted": 4}
    assert client.get("/history/s1").json() == []
    # The thread row survives; only its messages were cleared.
    assert client.get(f"/sessions/s1/{thread['id']}/messages").json() == []


def test_clear_history_scoped_to_thread(client, monkeypatch):
    _stub_answer(monkeypatch)
    client.post("/ask", json={"student_id": "s1", "question": "q-flat"})
    thread = client.post("/sessions", json={"student_id": "s1"}).json()
    client.post(
        "/ask",
        json={"student_id": "s1", "question": "q-threaded", "session_id": thread["id"]},
    )

    resp = client.delete(f"/history/s1?session_id={thread['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 2}

    # The thread's turns are gone, the unthreaded ones remain.
    assert client.get(f"/sessions/s1/{thread['id']}/messages").json() == []
    contents = [row["content"] for row in client.get("/history/s1").json()]
    assert "q-flat" in contents
    assert "q-threaded" not in contents


def test_clear_history_unknown_student_is_noop(client):
    assert client.delete("/history/nobody").json() == {"deleted": 0}


def test_clear_history_foreign_thread_is_noop(client, monkeypatch):
    _stub_answer(monkeypatch)
    thread = client.post("/sessions", json={"student_id": "s1"}).json()
    client.post(
        "/ask",
        json={"student_id": "s1", "question": "q-threaded", "session_id": thread["id"]},
    )
    # Another student cannot clear s1's thread.
    resp = client.delete(f"/history/s2?session_id={thread['id']}")
    assert resp.json() == {"deleted": 0}
    assert client.get(f"/sessions/s1/{thread['id']}/messages").json() != []


# --- API-key authentication --------------------------------------------------

_API_KEY = "secret-key"


def _set_api_key(monkeypatch, key):
    from core.config import Settings

    settings = Settings(api_key=key)
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/sessions", {"student_id": "s1"}),
        ("get", "/sessions/s1", None),
        ("get", "/sessions/s1/1/messages", None),
        ("delete", "/history/s1", None),
    ],
)
def test_sessions_reject_missing_key(client, monkeypatch, method, path, body):
    _set_api_key(monkeypatch, _API_KEY)
    response = client.request(method, path, json=body)
    assert response.status_code == 401


def test_sessions_accept_correct_key(client, monkeypatch):
    _set_api_key(monkeypatch, _API_KEY)
    response = client.post("/sessions", json={"student_id": "s1"}, headers={"X-API-Key": _API_KEY})
    assert response.status_code == 201


# --- model link sanity -------------------------------------------------------


def test_session_links_to_student(client):
    thread = client.post("/sessions", json={"student_id": "s1", "title": "T"}).json()
    with api_main.get_session(api_main._engine) as session:
        row = session.scalar(select(SessionModel).where(SessionModel.id == thread["id"]))
        assert row is not None
        assert row.title == "T"
        assert row.student.external_id == "s1"
