"""Structured, request-scoped logging for the API (pure stdlib).

This module wires up a single-line JSON log formatter on the root logger so
production logs are machine-parseable (one JSON object per line). Each record
carries a timestamp, level, logger name, and message; when a request is in
flight, the active request id (propagated through ``request_id_var``) is added
so log lines can be correlated across a single request.

Everything here uses only the standard library: no third-party logging
dependency is introduced. ``configure_logging`` is idempotent and safe to call
on every startup.
"""

import json
import logging
from contextvars import ContextVar

# Holds the current request's id for the duration of a request. A contextvar is
# used (rather than thread-locals) so the value is correct under async handlers
# and is naturally isolated per request/task. ``None`` means "no active request"
# (e.g. logs emitted at startup), in which case the id is simply omitted.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Marker so ``configure_logging`` only attaches one formatter/handler per
# process even if called repeatedly (startup, tests, re-imports).
_HANDLER_FLAG = "_grounded_rag_json_handler"

# Standard ``LogRecord`` attributes; anything else on the record is treated as
# structured "extra" context and merged into the JSON payload.
_RESERVED_RECORD_KEYS = frozenset(
    vars(logging.makeLogRecord({})).keys() | {"message", "asctime", "taskName"}
)


class JsonFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object.

    The payload always includes ``timestamp`` (ISO-8601 UTC), ``level``,
    ``logger`` and ``message``. The active ``request_id`` is included when one is
    set. Any extra fields passed via ``logger.info(..., extra={...})`` are merged
    in as long as they do not collide with reserved record attributes. If the
    record carries exception info, a ``exc_info`` string is added (server-side
    only; it is never returned to clients).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id

        # Merge structured context provided via ``extra={...}``.
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_KEYS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """Format the record time as an ISO-8601 UTC timestamp."""
        import datetime as _dt

        dt = _dt.datetime.fromtimestamp(record.created, tz=_dt.UTC)
        return dt.isoformat()


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger, at most once per process.

    ``level`` is a standard level name (e.g. ``"INFO"``, ``"DEBUG"``); an unknown
    value falls back to ``INFO`` so a misconfiguration never crashes startup. The
    function is idempotent: a sentinel handler is reused across calls, so the
    level can be updated without stacking duplicate handlers (which would print
    each line multiple times).
    """
    root = logging.getLogger()
    resolved = logging.getLevelName(str(level).upper())
    if not isinstance(resolved, int):
        resolved = logging.INFO
    root.setLevel(resolved)

    for handler in root.handlers:
        if getattr(handler, _HANDLER_FLAG, False):
            handler.setLevel(resolved)
            return

    handler = logging.StreamHandler()
    setattr(handler, _HANDLER_FLAG, True)
    handler.setFormatter(JsonFormatter())
    handler.setLevel(resolved)
    root.addHandler(handler)
