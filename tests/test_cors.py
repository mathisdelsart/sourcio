"""CORS middleware behavior.

The app configures CORS at import time from ``Settings.cors_origins`` (default:
local dev origins), so these tests exercise the default configuration: an
allowed origin is echoed (incl. on the preflight), a disallowed origin is not.
"""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

client = TestClient(app)

ALLOWED = "http://localhost:3000"


def test_allowed_origin_is_echoed():
    response = client.get("/health", headers={"Origin": ALLOWED})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == ALLOWED


def test_preflight_for_allowed_origin_succeeds():
    response = client.options(
        "/ask",
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == ALLOWED


def test_disallowed_origin_is_not_echoed():
    response = client.get("/health", headers={"Origin": "http://evil.example.com"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") != "http://evil.example.com"


# --- CORS on error responses -------------------------------------------------
# A 500 is produced by Starlette's ServerErrorMiddleware, which runs *outside*
# the CORSMiddleware, so the error handler must re-attach CORS headers itself;
# otherwise the browser masks the real status/message as an unreachable backend.

# raise_server_exceptions=False lets the app's 500 handler run instead of the
# test client re-raising the error.
error_client = TestClient(app, raise_server_exceptions=False)


def test_500_carries_cors_header_for_allowed_origin(monkeypatch):
    import api.main as api_main

    def boom():
        raise RuntimeError("kaboom")

    monkeypatch.setattr(api_main, "list_courses", boom)
    response = error_client.get("/courses", headers={"Origin": ALLOWED})

    assert response.status_code == 500
    assert response.headers.get("access-control-allow-origin") == ALLOWED
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_500_does_not_echo_disallowed_origin(monkeypatch):
    import api.main as api_main

    def boom():
        raise RuntimeError("kaboom")

    monkeypatch.setattr(api_main, "list_courses", boom)
    response = error_client.get("/courses", headers={"Origin": "http://evil.example.com"})

    assert response.status_code == 500
    assert response.headers.get("access-control-allow-origin") != "http://evil.example.com"
