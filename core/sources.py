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


def get_source(chunk_id: str) -> dict | None:
    """Return the cited chunk's text and citation metadata, or None if absent.

    Builds a Qdrant client from settings and retrieves the point named by
    ``chunk_id`` from the configured collection (payload only, no vectors).
    Returns ``{id, course, chapter, page, text}`` mapped from the point's
    payload, or ``None`` when the id is unknown, the collection is missing, or
    any retrieval error occurs. Never raises.
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
    return {
        "id": str(point.id),
        "course": payload.get("course"),
        "chapter": payload.get("chapter"),
        "page": payload.get("page"),
        "text": payload.get("text"),
    }
