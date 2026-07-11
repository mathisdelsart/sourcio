"""Health, readiness and public-config probes.

These routes are intentionally free of the ``require_api_key`` and data-user
guards: an orchestrator (or the frontend, before it has a token) must be able to
reach them without credentials.
"""

from fastapi import APIRouter, HTTPException, status

import api.main as api_main

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict[str, str]:
    """Readiness probe: report whether the service can serve traffic.

    Distinct from ``/health`` (liveness): readiness reflects that startup wiring
    completed, primarily that the database engine is bound. It performs a light,
    dependency-free check (no LLM, no network) so it is safe to poll frequently
    from an orchestrator. Returns 200 with ``{"status": "ready"}`` when the
    engine is configured, otherwise 503 with ``{"status": "not ready"}``.
    """
    if api_main._engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is not ready: database engine is not configured.",
        )
    return {"status": "ready"}


@router.get("/config")
def public_config() -> dict[str, bool]:
    """Expose non-sensitive server flags the frontend needs before authenticating.

    Fully open (no API key, no bearer token), like ``/health``: the frontend must
    be able to learn whether login is mandatory *before* the user has a token, so
    it can decide to show a blocking login gate. Currently returns only
    ``{"require_auth": bool}`` — whether every data endpoint requires a valid
    bearer token and enforces per-user student ownership.
    """
    return {"require_auth": api_main.get_settings().require_auth}
