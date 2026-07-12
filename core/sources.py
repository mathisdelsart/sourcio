"""Lookup of a single source chunk by its Qdrant point id.

Lets a UI turn a citation into a readable excerpt: given the id of a chunk that
was cited in an answer, return that chunk's full text and its course/chapter/page
metadata so the underlying source can be displayed.

This is read-only and grounded in what is actually indexed. It builds a Qdrant
client from settings (same construction as ``core.courses`` and retrieval),
retrieves the point by id, and maps its payload to a plain dict. A missing point,
a missing collection, or any connection error yields ``None`` rather than raising,
so the endpoint degrades gracefully before any course has been ingested.
"""

from core.config import get_settings
from core.qdrant import client_from_settings


def get_source(chunk_id: str, owner: str | None = None) -> dict | None:
    """Return the cited chunk's text and citation metadata, or None if absent.

    Builds a Qdrant client from settings and retrieves the point named by
    ``chunk_id`` from the configured collection (payload only, no vectors).
    Returns ``{id, course, chapter, page, text}`` mapped from the point's
    payload, or ``None`` when the id is unknown, the collection is missing, or
    any retrieval error occurs. Never raises.

    When ``owner`` is given the point is strictly owner-scoped (the same rule as
    ``core.retrieval.owner_scope_filter``): the chunk is returned only if its
    payload ``owner`` equals ``owner``. A chunk that exists but belongs to a
    *different* account — or is owner-less (legacy/CLI corpus) — is treated as
    absent (returns ``None``, so the route 404s), so a caller cannot read another
    account's material by guessing its deterministic chunk id. When ``owner`` is
    ``None`` the lookup is **fail-closed**: it returns ``None`` without querying,
    since a source lookup is a per-account read and running it unscoped could
    reveal any account's chunk. The API always supplies the caller's effective id;
    only a request with no identity reaches here as None.
    """
    # Fail closed: with no owner there is no caller to scope to, so report the
    # source as absent rather than revealing a chunk that may belong to anyone.
    if owner is None:
        return None

    client = client_from_settings()
    collection = get_settings().qdrant_collection

    try:
        points = client.retrieve(
            collection_name=collection,
            ids=[chunk_id],
            with_payload=True,
            with_vectors=False,
        )
    except Exception:
        # The collection may not exist yet, or the server may be unreachable:
        # treat the source as absent rather than failing the request.
        return None

    if not points:
        return None

    point = points[0]
    payload = point.payload or {}
    # Strict owner-scope check (mirrors ``owner_scope_filter``): the chunk is
    # visible only to its own owner. A point owned by a different account, or one
    # with no owner (legacy/CLI corpus), is reported as absent so its existence
    # never leaks.
    if payload.get("owner") != owner:
        return None
    return {
        "id": str(point.id),
        "course": payload.get("course"),
        "chapter": payload.get("chapter"),
        "page": payload.get("page"),
        "text": payload.get("text"),
    }
