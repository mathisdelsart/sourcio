"""Shared runtime surface for the API: the database engine and the swappable
business functions the route modules call.

This is a **leaf** module: it imports only from ``core``/``agent``/``db``, never
from ``api.main`` or ``api.routers``. The routers and ``api.deps`` resolve the
business functions through this module at call time (e.g. ``runtime.answer``),
and the test suite monkeypatches them here. Keeping this surface in a leaf module
(rather than in ``api.main``, which imports the routers) is what breaks the
``main -> routers -> main`` import cycle: nothing imports back into ``api.main``.

The names below are re-exported for that call-time indirection; ``__all__`` marks
them as intentional re-exports so the linter does not flag them as unused.
"""

from typing import Any

from sqlalchemy import Engine

from agent.nodes.generate import generate
from agent.nodes.grade import grade
from agent.nodes.quiz import generate_quiz, grade_quiz_answer, summarize_quiz
from agent.nodes.reexplain import reexplain, stream_reexplain
from core.answer import answer, stream_answer
from core.config import get_settings
from core.courses import list_chapters, list_courses
from core.documents import (
    delete_documents,
    list_documents,
    read_stored_file,
    rename_chapter,
    rename_course,
    save_upload,
    stream_ingest,
)
from core.sources import get_source
from db.session import (
    configure_session_factory,
    create_engine_from_settings,
    get_session,
    init_db,
)

__all__ = [
    "answer",
    "configure_engine",
    "create_engine_from_settings",
    "delete_documents",
    "generate",
    "generate_quiz",
    "get_session",
    "get_settings",
    "get_source",
    "grade",
    "grade_quiz_answer",
    "list_chapters",
    "list_courses",
    "list_documents",
    "read_stored_file",
    "reexplain",
    "rename_chapter",
    "rename_course",
    "save_upload",
    "stream_answer",
    "stream_ingest",
    "stream_reexplain",
    "summarize_quiz",
]

# Bound on startup (or injected by tests via :func:`configure_engine`). Keeping
# the engine module-level lets tests swap in an in-memory SQLite database.
_engine: Engine | None = None


def configure_engine(engine: Engine) -> None:
    """Bind the API to ``engine``, create tables, and configure the session factory.

    Tests call this with an in-memory SQLite engine; startup calls it with the
    engine built from ``Settings.database_url``.
    """
    global _engine
    _engine = engine
    init_db(engine)
    configure_session_factory(engine)


def ensure_engine() -> None:
    """Bind the default engine (built from settings) if none is configured yet.

    Called once on startup; a no-op after :func:`configure_engine` has run --
    including when a test has already injected an in-memory engine.
    """
    if _engine is None:
        configure_engine(create_engine_from_settings())


# The placeholder secret shipped for local development. It MUST be overridden
# before enabling ``require_auth`` — otherwise anyone knowing this public default
# could forge a valid access token.
_INSECURE_JWT_DEFAULT = "dev-insecure-change-me"
# Minimum length accepted for a JWT signing secret when auth is required. A short
# secret is brute-forceable and defeats the point of signing.
_MIN_JWT_SECRET_LEN = 16


def _validate_jwt_secret(settings: Any) -> None:
    """Fail fast when auth is required but the JWT secret is unsafe.

    Only enforced when ``require_auth`` is on (a public/shared deployment). The
    default placeholder secret or any secret shorter than
    :data:`_MIN_JWT_SECRET_LEN` characters is rejected with a clear
    ``RuntimeError`` so the operator sets a strong ``JWT_SECRET`` instead of
    silently running with a forgeable one. With ``require_auth`` off (local dev)
    the placeholder is left alone so nothing changes for single-user runs.
    """
    if not settings.require_auth:
        return
    secret = settings.jwt_secret
    if secret == _INSECURE_JWT_DEFAULT or len(secret) < _MIN_JWT_SECRET_LEN:
        raise RuntimeError(
            "REQUIRE_AUTH is enabled but JWT_SECRET is unsafe "
            "(the insecure default or shorter than "
            f"{_MIN_JWT_SECRET_LEN} characters). Set a strong, random JWT_SECRET "
            "before running with authentication enabled."
        )
