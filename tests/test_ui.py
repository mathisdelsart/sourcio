"""Unit tests for the pure UI helpers and the API client wrapper.

These exercise the Streamlit-free logic in ``ui/app.py`` with synthetic data:
no Streamlit import, no model and no Qdrant. The ``TutorClient`` is driven by a
mocked ``httpx`` transport, so no real network request is made. ``ui.app``
imports ``httpx`` (pulled in by the FastAPI/uvicorn stack), so the module is
guarded with ``importorskip`` to keep plain ``uv sync --group dev`` collecting
cleanly; CI installs the extras and runs these.
"""

import pytest

httpx = pytest.importorskip("httpx")

from ui.app import (  # noqa: E402
    DEFAULT_API_BASE_URL,
    TutorClient,
    format_sources,
    get_api_base_url,
    render_answer,
    render_exercise,
    render_grade,
    render_history,
)


def test_format_sources_renders_bullet_list():
    out = format_sources(["(Course, p.11)", "(Course, p.12)"])
    assert out == "- (Course, p.11)\n- (Course, p.12)"


def test_format_sources_handles_no_sources():
    assert format_sources([]) == "_No sources cited._"


def test_render_answer_grounded_includes_body_and_sources():
    result = {
        "answer": "Defined in (Course, p.11).",
        "refused": False,
        "sources": ["(Course, p.11)"],
    }
    out = render_answer(result)
    assert "Defined in (Course, p.11)." in out
    assert "**Sources**" in out
    assert "- (Course, p.11)" in out


def test_render_answer_shows_refusal_clearly():
    result = {
        "answer": "This is not covered in the course material.",
        "refused": True,
        "sources": [],
    }
    out = render_answer(result)
    assert out.startswith("**Refused.**")
    assert "This is not covered in the course material." in out


def test_render_exercise_omits_solution():
    exercise = {
        "problem": "Compute the Fourier transform of f.",
        "solution": "secret reference solution",
        "refused": False,
    }
    out = render_exercise(exercise)
    assert "Compute the Fourier transform of f." in out
    assert "secret reference solution" not in out


def test_render_exercise_shows_refusal():
    exercise = {"problem": "This is not covered in the course material.", "refused": True}
    out = render_exercise(exercise)
    assert out.startswith("**Refused.**")


def test_render_grade_includes_score_and_feedback():
    out = render_grade({"score": 80, "feedback": "Correct method, minor slip."})
    assert "**Score: 80/100**" in out
    assert "Correct method, minor slip." in out


def test_render_history_chronological_transcript():
    history = [
        {"role": "user", "content": "Define X?", "created_at": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "X is ...", "created_at": "2026-01-01T00:00:01"},
    ]
    out = render_history(history)
    assert out == "**User:** Define X?\n\n**Assistant:** X is ..."


def test_render_history_empty():
    assert render_history([]) == "_No history yet._"


def test_app_module_imports_without_streamlit():
    # The module must be importable without the optional ``ui`` extra; only
    # ``main`` touches Streamlit, and it is never called here.
    import ui.app as app

    assert callable(app.main)


# --- API client wrapper (mocked httpx transport, no real network) -----------


def _make_client(handler) -> TutorClient:
    """Build a TutorClient backed by a mock transport calling ``handler``."""
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://testserver")
    return TutorClient("http://testserver", client=http)


def test_get_api_base_url_default(monkeypatch):
    monkeypatch.delenv("API_BASE_URL", raising=False)
    assert get_api_base_url() == DEFAULT_API_BASE_URL


def test_get_api_base_url_from_env_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://example.com:9000/")
    assert get_api_base_url() == "http://example.com:9000"


def test_client_ask_posts_payload_and_returns_json():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"answer": "ok (Course, p.1)", "refused": False, "sources": ["(Course, p.1)"]}
        )

    client = _make_client(handler)
    out = client.ask("s1", "What is X?", k=3)

    assert out == {"answer": "ok (Course, p.1)", "refused": False, "sources": ["(Course, p.1)"]}
    assert seen["url"].endswith("/ask")
    assert seen["body"] == {"student_id": "s1", "question": "What is X?", "k": 3}


def test_client_exercise_posts_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"problem": "Compute X.", "refused": False})

    client = _make_client(handler)
    out = client.exercise("s1", "integrals")

    assert out == {"problem": "Compute X.", "refused": False}
    assert seen["body"] == {"student_id": "s1", "notion": "integrals"}


def test_client_grade_includes_exercise_when_given():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"score": 80, "feedback": "Good."})

    client = _make_client(handler)
    out = client.grade("s1", "X = 42", exercise={"solution": "X = 42"})

    assert out == {"score": 80, "feedback": "Good."}
    assert seen["body"] == {
        "student_id": "s1",
        "message": "X = 42",
        "exercise": {"solution": "X = 42"},
    }


def test_client_grade_omits_exercise_when_none():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"score": 0, "feedback": "No reference."})

    client = _make_client(handler)
    client.grade("s1", "X = 42")

    assert "exercise" not in seen["body"]


def test_client_history_gets_with_limit():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json=[
                {"role": "user", "content": "q", "created_at": "2026-01-01T00:00:00"},
            ],
        )

    client = _make_client(handler)
    out = client.history("alice", limit=5)

    assert out == [{"role": "user", "content": "q", "created_at": "2026-01-01T00:00:00"}]
    assert "/history/alice" in seen["url"]
    assert "limit=5" in seen["url"]


def test_client_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "bad request"})

    client = _make_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        client.ask("s1", "")
