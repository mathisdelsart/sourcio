"""Tests for API observability and hardening.

Covers the request-id middleware (generation and echo), the global handler for
unhandled errors (consistent JSON shape, request id, no stack-trace leak), the
``/ready`` readiness probe, and that structured logging configures without
error. No real LLM, vector store, or network call is made. The module is skipped
when the optional ``api`` extra (FastAPI) is not installed.
"""

import logging

import pytest

pytest.importorskip("fastapi")

import uuid  # noqa: E402

from fastapi import APIRouter  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import api.main as api_main  # noqa: E402
from api.logging_config import (  # noqa: E402
    JsonFormatter,
    configure_logging,
    request_id_var,
)
from api.main import app  # noqa: E402
from api.middleware import REQUEST_ID_HEADER  # noqa: E402


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


# --- request id --------------------------------------------------------------


def test_response_carries_generated_request_id(client):
    response = client.get("/health")
    assert response.status_code == 200
    request_id = response.headers.get(REQUEST_ID_HEADER)
    assert request_id
    # A freshly generated id is a valid uuid4 hex.
    uuid.UUID(hex=request_id)


def test_response_echoes_provided_request_id(client):
    provided = "trace-abc-123"
    response = client.get("/health", headers={REQUEST_ID_HEADER: provided})
    assert response.status_code == 200
    assert response.headers.get(REQUEST_ID_HEADER) == provided


def test_each_request_gets_a_distinct_request_id(client):
    first = client.get("/health").headers.get(REQUEST_ID_HEADER)
    second = client.get("/health").headers.get(REQUEST_ID_HEADER)
    assert first and second and first != second


# --- /ready ------------------------------------------------------------------


def test_ready_returns_200_when_engine_bound(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    # Readiness responses also carry a request id.
    assert response.headers.get(REQUEST_ID_HEADER)


def test_health_unchanged(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- global error handling ---------------------------------------------------

# A temporary, test-only router that raises, mounted just for these tests and
# removed afterwards so the application never ships a permanent error route.
_boom_router = APIRouter()


@_boom_router.get("/_boom_test_only")
def _boom() -> None:
    raise RuntimeError("super secret internal detail")


@pytest.fixture
def client_with_error_route():
    """A client whose app has a temporary route that raises, server errors caught."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    api_main.configure_engine(engine)
    app.include_router(_boom_router)
    try:
        # raise_server_exceptions=False so the registered handler runs instead of
        # the exception propagating into the test (default TestClient behavior).
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.router.routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) != "/_boom_test_only"
        ]
        api_main._engine = None


def test_unhandled_error_returns_standardized_json(client_with_error_route):
    response = client_with_error_route.get("/_boom_test_only")
    assert response.status_code == 500
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["type"] == "internal_server_error"
    assert isinstance(error["message"], str) and error["message"]
    # The request id is surfaced and matches the response header.
    assert error["request_id"] == response.headers.get(REQUEST_ID_HEADER)


def test_unhandled_error_does_not_leak_internals(client_with_error_route):
    response = client_with_error_route.get("/_boom_test_only")
    text = response.text
    # Neither the exception message nor a traceback reaches the client.
    assert "super secret internal detail" not in text
    assert "Traceback" not in text
    assert "RuntimeError" not in text


def test_unhandled_error_echoes_provided_request_id(client_with_error_route):
    provided = "err-trace-9"
    response = client_with_error_route.get(
        "/_boom_test_only", headers={REQUEST_ID_HEADER: provided}
    )
    assert response.status_code == 500
    assert response.json()["error"]["request_id"] == provided


# --- structured logging ------------------------------------------------------


def test_configure_logging_is_idempotent():
    root = logging.getLogger()
    configure_logging("INFO")
    before = len(root.handlers)
    configure_logging("DEBUG")
    configure_logging("INFO")
    after = len(root.handlers)
    # Repeated calls reuse the same handler rather than stacking duplicates.
    assert after == before


def test_configure_logging_tolerates_unknown_level():
    # An invalid level must not raise; it falls back to a sane default.
    configure_logging("NOT_A_LEVEL")
    assert isinstance(logging.getLogger().level, int)


def test_json_formatter_includes_request_id_when_set():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="api",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    token = request_id_var.set("rid-42")
    try:
        line = formatter.format(record)
    finally:
        request_id_var.reset(token)

    import json

    payload = json.loads(line)
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "api"
    assert payload["request_id"] == "rid-42"
    assert "timestamp" in payload


def test_json_formatter_omits_request_id_when_absent():
    import json

    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="api",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="no rid",
        args=(),
        exc_info=None,
    )
    payload = json.loads(formatter.format(record))
    assert "request_id" not in payload
