"""In-memory, thread-safe registry of background jobs (ingestion and answers).

Ingesting a document (extract -> chunk -> embed -> index) can take minutes for a
large PDF, and must not be tied to the lifetime of the upload HTTP request: a
browser refresh or navigation would otherwise abort the request and stop the
server mid-ingest. The upload endpoint therefore spawns a daemon thread that
runs the ingest and reports progress here, while the client polls a status
endpoint to follow — or, after a refresh, re-attach to — the running job.

The same problem applies to answering a question: a slow LLM answer streamed over
SSE is cancelled the instant the browser navigates away or refreshes. So an "Ask"
runs as a background *answer* job too — a daemon thread drains ``stream_answer``
into the record (accumulated partial text + current stage, then the final answer,
sources and citations) while the client polls to follow or re-attach after a
refresh. Answer jobs are owner-scoped (:func:`get_answer_job` verifies the caller
owns the job) so one user can never read another's answer.

The registry is a module-level ``dict`` guarded by a single ``threading.Lock``.
This is correct for the app's single-process deployment (the Makefile runs one
``uvicorn --reload`` and the Dockerfile runs a single ``uvicorn``). It is NOT
shared across worker processes: under a multi-worker gunicorn/uvicorn deployment
a job created in one worker would be invisible to another, so a shared store
(e.g. Redis) would be required — see this multi-worker caveat before scaling out.

A job record is a plain ``dict`` so it serializes straight to JSON from the API.
Fields:

- ``job_id``: the job's own id (also the registry key), so a listed record is
  self-identifying.
- ``status``: ``"running"`` -> ``"done"`` | ``"error"`` (lifecycle).
- ``type``: the kind of the latest progress event (``"start"`` / ``"progress"``
  / ``"done"`` / ``"error"``), mirrored from :func:`core.documents.stream_ingest`
  so the existing progress-bar UI keeps rendering off a single shape.
- ``total, done, indexed, skipped, reason, message, elapsed``: progress counters
  merged from each ingest event.
- ``course, chapter, filename``: what is being ingested (also used as a UI label).
- ``created_at, finished_at``: ISO-8601 UTC timestamps (``finished_at`` is set
  once the job reaches a terminal status).
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

# Finished jobs are retained briefly so a client that reconnects right after
# completion still sees the terminal status, then pruned to bound memory.
_RETENTION = timedelta(minutes=30)

# Statuses that mean the job will not change again.
_TERMINAL = ("done", "error")

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string (same source used elsewhere)."""
    return datetime.now(UTC).isoformat()


def _prune_locked() -> None:
    """Drop finished jobs older than the retention window. Caller holds the lock."""
    now = datetime.now(UTC)
    stale = [
        job_id
        for job_id, record in _jobs.items()
        if record.get("finished_at")
        and now - datetime.fromisoformat(record["finished_at"]) > _RETENTION
    ]
    for job_id in stale:
        del _jobs[job_id]


def create_job(course: str, chapter: str | None, filename: str) -> str:
    """Register a new ingestion job and return its opaque id.

    The record starts in ``"running"`` with zeroed counters so a client polling
    immediately (before the first event) sees a coherent "starting" state. Old
    finished jobs are pruned on creation to keep the registry bounded.
    """
    job_id = uuid.uuid4().hex
    record: dict[str, Any] = {
        "job_id": job_id,
        "kind": "ingest",
        "status": "running",
        "type": "start",
        "course": course,
        "chapter": chapter,
        "filename": filename,
        "total": 0,
        "done": 0,
        "indexed": 0,
        "skipped": 0,
        "reason": None,
        "message": None,
        "elapsed": 0.0,
        "created_at": _now_iso(),
        "finished_at": None,
    }
    with _lock:
        _prune_locked()
        _jobs[job_id] = record
    return job_id


def update_job(job_id: str, event: dict[str, Any]) -> None:
    """Merge ``event`` into the job record (no-op for an unknown/pruned id).

    ``event`` is either a raw progress event from ``stream_ingest`` (carrying
    ``type`` and counters) or a lifecycle patch such as ``{"status": "done"}``.
    Reaching a terminal ``status`` stamps ``finished_at`` once.
    """
    with _lock:
        record = _jobs.get(job_id)
        if record is None:
            return
        record.update(event)
        if record.get("status") in _TERMINAL and record.get("finished_at") is None:
            record["finished_at"] = _now_iso()


def get_job(job_id: str) -> dict[str, Any] | None:
    """Return a copy of the job record, or ``None`` if unknown/pruned."""
    with _lock:
        record = _jobs.get(job_id)
        return dict(record) if record is not None else None


def list_jobs() -> list[dict[str, Any]]:
    """Return copies of the current ingestion job records (newest first).

    Only ``kind == "ingest"`` records are listed, so answer jobs (which are
    owner-scoped and read one at a time) never leak into the documents view.
    """
    with _lock:
        return sorted(
            (dict(record) for record in _jobs.values() if record.get("kind") == "ingest"),
            key=lambda r: r["created_at"],
            reverse=True,
        )


def create_answer_job(owner: str | None, question: str) -> str:
    """Register a new background answer job and return its opaque id.

    The record starts in ``"running"`` at the ``"retrieving"`` stage with an empty
    ``answer`` so a client polling immediately sees a coherent "starting" state.
    ``owner`` is the requesting student id; :func:`get_answer_job` requires the
    caller to present the same owner, so one user cannot read another's answer.
    Old finished jobs are pruned on creation to keep the registry bounded.
    """
    job_id = uuid.uuid4().hex
    record: dict[str, Any] = {
        "job_id": job_id,
        "kind": "answer",
        "owner": owner,
        "question": question,
        "status": "running",
        "stage": "retrieving",
        # Partial text, grown token-by-token by the worker; final text on done.
        "answer": "",
        "refused": False,
        "sources": [],
        "citations": [],
        # Count of retrieved sources, surfaced once the "reading" stage begins.
        "source_count": None,
        "message": None,
        "created_at": _now_iso(),
        "finished_at": None,
    }
    with _lock:
        _prune_locked()
        _jobs[job_id] = record
    return job_id


def get_answer_job(job_id: str, owner: str | None) -> dict[str, Any] | None:
    """Return a copy of an answer job, or ``None`` if unknown/pruned/foreign.

    Returns ``None`` (so the API replies 404) when the id is unknown or pruned,
    the record is not an answer job, or ``owner`` does not match the id the job
    was created for — a user can only read their own answer job.
    """
    with _lock:
        record = _jobs.get(job_id)
        if record is None or record.get("kind") != "answer":
            return None
        if record.get("owner") != owner:
            return None
        return dict(record)
