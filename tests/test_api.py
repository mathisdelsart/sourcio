"""Tests for the FastAPI service.

No real LLM, vector store, or network call is made: the underlying grounded
function and graph nodes are monkeypatched in the ``api.main`` namespace, and the
service is bound to an in-memory SQLite database, so the routes are exercised in
isolation. The module is skipped when the optional ``api`` extra (FastAPI) is not
installed, so CI without extras collects cleanly.
"""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import api.main as api_main  # noqa: E402
from api.main import app  # noqa: E402


@pytest.fixture
def client():
    """Bind the API to a fresh in-memory SQLite DB and yield a test client.

    A single shared in-memory connection (``StaticPool``) is used so every
    request sees the same database for the duration of the test.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    api_main.configure_engine(engine)
    # The app's lifespan would otherwise overwrite the engine; pre-binding above
    # leaves ``_engine`` set, so the lifespan no-ops and our in-memory DB is used.
    with TestClient(app) as test_client:
        yield test_client
    api_main._engine = None


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ask_returns_grounded_answer_and_sources(client, monkeypatch):
    captured = {}

    def fake_answer(question, *, k=5):
        captured["question"] = question
        captured["k"] = k
        return {
            "answer": "A wavelet is ... (Course, p.11)",
            "refused": False,
            "sources": ["(Course, p.11)"],
            "raw": "A wavelet is ... [1]",
        }

    monkeypatch.setattr(api_main, "answer", fake_answer)

    response = client.post(
        "/ask", json={"student_id": "s1", "question": "What is a wavelet?", "k": 3}
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "answer": "A wavelet is ... (Course, p.11)",
        "refused": False,
        "sources": ["(Course, p.11)"],
    }
    # The request reached the grounded function with its parameters intact.
    assert captured == {"question": "What is a wavelet?", "k": 3}
    # The internal raw model output is not exposed by the API.
    assert "raw" not in body


def test_ask_uses_default_k(client, monkeypatch):
    captured = {}

    def fake_answer(question, *, k=5):
        captured["k"] = k
        return {"answer": "ok", "refused": False, "sources": [], "raw": "ok"}

    monkeypatch.setattr(api_main, "answer", fake_answer)

    response = client.post("/ask", json={"student_id": "s1", "question": "anything"})
    assert response.status_code == 200
    assert captured["k"] == 5


def test_ask_surfaces_refusal(client, monkeypatch):
    def fake_answer(question, *, k=5):
        return {
            "answer": "This is not covered in the course material.",
            "refused": True,
            "sources": [],
            "raw": "This is not covered in the course material.",
        }

    monkeypatch.setattr(api_main, "answer", fake_answer)

    response = client.post("/ask", json={"student_id": "s1", "question": "off-topic"})
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert body["sources"] == []


def test_ask_persists_user_and_assistant_messages(client, monkeypatch):
    def fake_answer(question, *, k=5):
        return {
            "answer": "Grounded reply (Course, p.3)",
            "refused": False,
            "sources": ["(Course, p.3)"],
            "raw": "Grounded reply [1]",
        }

    monkeypatch.setattr(api_main, "answer", fake_answer)

    client.post("/ask", json={"student_id": "alice", "question": "Define X?"})

    history = client.get("/history/alice").json()
    assert [(t["role"], t["content"]) for t in history] == [
        ("user", "Define X?"),
        ("assistant", "Grounded reply (Course, p.3)"),
    ]


def test_history_is_chronological_across_turns(client, monkeypatch):
    counter = {"n": 0}

    def fake_answer(question, *, k=5):
        counter["n"] += 1
        return {
            "answer": f"answer-{counter['n']}",
            "refused": False,
            "sources": [],
            "raw": f"answer-{counter['n']}",
        }

    monkeypatch.setattr(api_main, "answer", fake_answer)

    client.post("/ask", json={"student_id": "bob", "question": "first"})
    client.post("/ask", json={"student_id": "bob", "question": "second"})

    history = client.get("/history/bob").json()
    contents = [t["content"] for t in history]
    assert contents == ["first", "answer-1", "second", "answer-2"]
    # created_at is surfaced as an ISO string for each turn.
    assert all(isinstance(t["created_at"], str) for t in history)


def test_history_respects_limit(client, monkeypatch):
    def fake_answer(question, *, k=5):
        return {"answer": "a", "refused": False, "sources": [], "raw": "a"}

    monkeypatch.setattr(api_main, "answer", fake_answer)

    client.post("/ask", json={"student_id": "carol", "question": "q1"})
    client.post("/ask", json={"student_id": "carol", "question": "q2"})

    # Each /ask writes two rows; limit=2 returns only the most recent two.
    limited = client.get("/history/carol", params={"limit": 2}).json()
    assert [t["content"] for t in limited] == ["q2", "a"]


def test_history_unknown_student_is_empty(client):
    assert client.get("/history/nobody").json() == []


def test_student_get_or_create_reuses_same_student(client, monkeypatch):
    def fake_answer(question, *, k=5):
        return {"answer": "ok", "refused": False, "sources": [], "raw": "ok"}

    monkeypatch.setattr(api_main, "answer", fake_answer)

    # Two asks for the same external id must accumulate into one history,
    # proving the student is reused rather than duplicated.
    client.post("/ask", json={"student_id": "dave", "question": "one"})
    client.post("/ask", json={"student_id": "dave", "question": "two"})

    history = client.get("/history/dave").json()
    user_turns = [t["content"] for t in history if t["role"] == "user"]
    assert user_turns == ["one", "two"]


def test_exercise_returns_problem_without_solution(client, monkeypatch):
    captured = {}

    def fake_generate(state):
        captured["message"] = state["message"]
        return {
            "exercise": {"problem": "Compute X.", "solution": "X = 42.", "refused": False},
            "retrieved": ["(Course, p.7)"],
        }

    monkeypatch.setattr(api_main, "generate", fake_generate)

    response = client.post("/exercise", json={"student_id": "s1", "notion": "integrals"})
    assert response.status_code == 200
    body = response.json()
    assert body == {"problem": "Compute X.", "refused": False}
    assert captured["message"] == "integrals"
    # The reference solution must never leak to the client.
    assert "solution" not in body


def test_exercise_surfaces_refusal(client, monkeypatch):
    def fake_generate(state):
        return {
            "exercise": {
                "problem": "This is not covered in the course material.",
                "solution": "",
                "refused": True,
            },
            "retrieved": [],
        }

    monkeypatch.setattr(api_main, "generate", fake_generate)

    response = client.post("/exercise", json={"student_id": "s1", "notion": "off-topic"})
    assert response.status_code == 200
    assert response.json()["refused"] is True


def test_exercise_does_not_write_to_history(client, monkeypatch):
    # Exercises are persisted by the agent node, not by the API: /exercise must
    # not create assistant/user Message rows.
    def fake_generate(state):
        return {
            "exercise": {"problem": "Compute X.", "solution": "s", "refused": False},
            "retrieved": [],
        }

    monkeypatch.setattr(api_main, "generate", fake_generate)

    client.post("/exercise", json={"student_id": "erin", "notion": "limits"})
    assert client.get("/history/erin").json() == []


def test_grade_returns_score_and_feedback(client, monkeypatch):
    captured = {}

    def fake_grade(state):
        captured["state"] = state
        return {"grade": {"score": 80, "feedback": "Good method."}}

    monkeypatch.setattr(api_main, "grade", fake_grade)

    response = client.post(
        "/grade",
        json={"student_id": "s1", "message": "X = 42", "exercise": {"solution": "X = 42"}},
    )
    assert response.status_code == 200
    assert response.json() == {"score": 80, "feedback": "Good method."}
    # Both the answer and the optional reference exercise reached the node.
    assert captured["state"]["message"] == "X = 42"
    assert captured["state"]["exercise"] == {"solution": "X = 42"}


def test_grade_without_exercise(client, monkeypatch):
    captured = {}

    def fake_grade(state):
        captured["state"] = state
        return {"grade": {"score": 0, "feedback": "No reference provided."}}

    monkeypatch.setattr(api_main, "grade", fake_grade)

    response = client.post("/grade", json={"student_id": "s1", "message": "X = 42"})
    assert response.status_code == 200
    assert response.json()["feedback"] == "No reference provided."
    # No exercise key is forwarded when the request omits it.
    assert "exercise" not in captured["state"]


def test_grade_does_not_write_to_history(client, monkeypatch):
    def fake_grade(state):
        return {"grade": {"score": 50, "feedback": "ok"}}

    monkeypatch.setattr(api_main, "grade", fake_grade)

    client.post("/grade", json={"student_id": "frank", "message": "answer"})
    assert client.get("/history/frank").json() == []


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/ask", {}),
        ("/ask", {"question": "no student"}),
        ("/ask", {"student_id": "s1"}),
        ("/exercise", {}),
        ("/exercise", {"notion": "no student"}),
        ("/grade", {}),
        ("/grade", {"message": "no student"}),
    ],
)
def test_missing_required_field_is_422(client, path, body):
    response = client.post(path, json=body)
    assert response.status_code == 422
