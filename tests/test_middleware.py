"""Tests for the hardening middleware: security headers and rate limiting.

No LLM, vector store, or network call is made: the service is bound to an
in-memory SQLite database and the grounded function is monkeypatched, so the
``/ask`` route is exercised in isolation. The module is skipped when the optional
``api`` extra (FastAPI) is not installed, so CI without extras collects cleanly.
"""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import api.main as api_main  # noqa: E402
import api.middleware as api_middleware  # noqa: E402
from api.main import app  # noqa: E402
from core.config import Settings  # noqa: E402


def _reset_rate_limiter():
    """Clear the live rate-limiter's per-client state.

    The app (and thus its middleware instances) is a module-level singleton, so
    the limiter's counter would otherwise leak request history between tests.
    Walk the built middleware stack and reset any rate limiter found.
    """
    node = getattr(app, "middleware_stack", None)
    while node is not None:
        if isinstance(node, api_middleware.RateLimitMiddleware):
            node._counter = api_middleware._FixedWindowCounter()
        node = getattr(node, "app", None)


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
        _reset_rate_limiter()
        yield test_client
    api_main._engine = None


def _set_settings(monkeypatch, **overrides):
    """Drive the middleware's settings without touching the real environment.

    The middleware reads ``core.config.get_settings`` re-exported in the
    ``api.middleware`` namespace, so patching it there controls the configured
    rate limit and HSTS toggle for the duration of a test.
    """
    settings = Settings(**overrides)
    monkeypatch.setattr(api_middleware, "get_settings", lambda: settings)


def _stub_answer(monkeypatch):
    """Mock the grounded function so /ask never hits an LLM or the network."""
    monkeypatch.setattr(
        api_main,
        "answer",
        lambda question, *, k=5, course=None, chapter=None: {
            "answer": "ok",
            "refused": False,
            "sources": [],
            "raw": "ok",
        },
    )


# --- Security headers --------------------------------------------------------


def test_security_headers_present_on_normal_response(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-xss-protection"] == "0"
    assert "permissions-policy" in response.headers


def test_hsts_absent_by_default(client):
    response = client.get("/health")
    assert "strict-transport-security" not in response.headers


def test_hsts_present_when_enabled(client, monkeypatch):
    _set_settings(monkeypatch, enable_hsts=True)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["strict-transport-security"].startswith("max-age=")


# --- Rate limiting -----------------------------------------------------------


def test_rate_limit_disabled_by_default_allows_traffic(client, monkeypatch):
    # Default config (limit 0): many requests in a row all succeed.
    _stub_answer(monkeypatch)
    for _ in range(20):
        response = client.post("/ask", json={"student_id": "s1", "question": "q"})
        assert response.status_code == 200


def test_rate_limit_returns_429_after_threshold(client, monkeypatch):
    _set_settings(monkeypatch, rate_limit_per_minute=3)
    _stub_answer(monkeypatch)

    # The first three requests in the window are allowed.
    for _ in range(3):
        ok = client.post("/ask", json={"student_id": "s1", "question": "q"})
        assert ok.status_code == 200

    # The fourth exceeds the limit and is rejected with 429 + Retry-After.
    blocked = client.post("/ask", json={"student_id": "s1", "question": "q"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    # The rejection still carries the security headers (outer header layer).
    assert blocked.headers["x-content-type-options"] == "nosniff"


def test_rate_limit_health_is_also_counted(client, monkeypatch):
    # The limiter applies to every route, including /health.
    _set_settings(monkeypatch, rate_limit_per_minute=2)
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 429


# --- Counter unit behavior ---------------------------------------------------


def test_counter_allows_up_to_limit_then_blocks():
    counter = api_middleware._FixedWindowCounter()
    now = 1000.0
    allowed = [counter.check("ip", 2, now)[0] for _ in range(3)]
    assert allowed == [True, True, False]


def test_counter_window_resets_after_expiry():
    counter = api_middleware._FixedWindowCounter()
    assert counter.check("ip", 1, 1000.0)[0] is True
    # Same window: blocked.
    assert counter.check("ip", 1, 1010.0)[0] is False
    # After the 60s window elapses, the old hit ages out and traffic resumes.
    assert counter.check("ip", 1, 1061.0)[0] is True


def test_counter_keys_are_independent():
    counter = api_middleware._FixedWindowCounter()
    assert counter.check("a", 1, 1000.0)[0] is True
    # A different client key has its own budget.
    assert counter.check("b", 1, 1000.0)[0] is True
    assert counter.check("a", 1, 1000.0)[0] is False


def test_counter_prunes_idle_clients():
    counter = api_middleware._FixedWindowCounter()
    counter.check("ip", 5, 1000.0)
    assert "ip" in counter._hits
    # A request far in the future (past the prune interval) drops the stale key.
    counter.check("other", 5, 1000.0 + 400.0)
    assert "ip" not in counter._hits
