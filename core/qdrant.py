"""Shared Qdrant access: client construction and a bounded point scan.

Retrieval, course discovery, source lookup, the documents inventory and
ingestion all build the same ``QdrantClient(url=..., api_key=...)`` from settings
and (for the read-side enumerations) page through points with the same scan
bound. Centralizing both here keeps the connection wiring and the scan cap in a
single place instead of copied across five modules.
"""

from collections.abc import Iterator
from typing import Any

from core.config import get_settings

# Cap the scroll page size and the total points scanned, so enumerating an
# unexpectedly large collection can never run unbounded.
SCROLL_PAGE = 256
SCROLL_MAX_POINTS = 100_000


def client_from_settings():
    """Build a ``QdrantClient`` from settings (URL + optional Cloud API key).

    ``qdrant_client`` is imported lazily so importing this module stays cheap and
    the heavy client is only loaded when Qdrant is actually used.
    """
    from qdrant_client import QdrantClient

    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)


def iter_point_payloads(
    client,
    collection: str,
    scope_filter=None,
    *,
    with_payload: bool | list[str] = True,
) -> Iterator[dict[str, Any]]:
    """Yield each point's payload, paging through ``collection`` up to the cap.

    Bounded by :data:`SCROLL_MAX_POINTS`. ``scope_filter`` (when given) restricts
    the scan server-side (e.g. to a caller's own material). Any error -- a missing
    collection, an unreachable server -- ends the iteration quietly, so callers
    degrade to "nothing indexed" instead of raising, matching the previous
    per-module behavior. ``with_payload`` is forwarded to Qdrant so a caller that
    needs only one field can fetch just that.
    """
    offset = None
    scanned = 0
    try:
        while scanned < SCROLL_MAX_POINTS:
            points, offset = client.scroll(
                collection_name=collection,
                scroll_filter=scope_filter,
                limit=SCROLL_PAGE,
                with_payload=with_payload,
                with_vectors=False,
                offset=offset,
            )
            for point in points:
                yield point.payload or {}
            scanned += len(points)
            if offset is None or not points:
                break
    except Exception:
        return
