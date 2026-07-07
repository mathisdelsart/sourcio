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


def get_source(chunk_id: str, owner: str | None = None) -> dict | None:
    """Return the cited chunk's text and citation metadata, or None if absent.

    Builds a Qdrant client from settings and retrieves the point named by
    ``chunk_id`` from the configured collection (payload only, no vectors).
    Returns ``{id, course, chapter, page, text}`` mapped from the point's
    payload, or ``None`` when the id is unknown, the collection is missing, or
    any retrieval error occurs. Never raises.

    When ``owner`` is given the point is owner-scoped with the same "mine OR
    shared" rule used by retrieval (``core.retrieval.owner_scope_filter``): the
    chunk is returned only if its payload ``owner`` equals ``owner`` or is unset
    (the legacy/CLI-ingested shared corpus). A chunk that exists but belongs to a
    *different* account is treated as absent (returns ``None``, so the route
    404s), so a caller cannot read another account's material by guessing its
    deterministic chunk id. When ``owner`` is ``None`` (anonymous / no auth) the
    lookup is unscoped, preserving the local single-user behaviour.
    """
    # Imported lazily so importing this module stays cheap and the heavy client
    # is only loaded when a source is actually requested, matching the codebase
    # style for optional/heavy dependencies.
    from qdrant_client import QdrantClient

    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    collection = settings.qdrant_collection

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
    # Owner-scope check (mirrors ``owner_scope_filter``): the chunk is visible to
    # its owner or when it carries no owner (shared/legacy corpus). A point owned
    # by a different account is reported as absent so its existence never leaks.
    if owner is not None:
        point_owner = payload.get("owner")
        if point_owner is not None and point_owner != owner:
            return None
    return {
        "id": str(point.id),
        "course": payload.get("course"),
        "chapter": payload.get("chapter"),
        "page": payload.get("page"),
        "text": payload.get("text"),
    }
