"""Discovery of the courses currently indexed in Qdrant.

Lists the distinct ``course`` payload values stored in the configured
collection, so a UI can populate a course picker dynamically instead of
hardcoding the list. This is read-only and grounded in what is actually
indexed: a course only appears once at least one of its chunks lives in Qdrant.

The fast path uses Qdrant's facet API, which aggregates distinct values of a
payload key server-side. When the API is unavailable in the installed client,
it falls back to scrolling points (paged) and collecting distinct values. An
empty or missing collection yields an empty list rather than raising, so the
endpoint degrades gracefully before any course has been ingested.
"""

from core.config import get_settings

# Cap on how many points to scan in the scroll fallback, so an unexpectedly
# large collection can never make this enumeration unbounded.
_SCROLL_PAGE = 256
_SCROLL_MAX_POINTS = 100_000

# Upper bound on distinct course values requested from the facet API.
_FACET_LIMIT = 1_000


def list_courses() -> list[str]:
    """Return the sorted, distinct course names indexed in Qdrant.

    Builds a Qdrant client from settings (same construction as retrieval) and
    enumerates the distinct ``course`` payload values in the configured
    collection. Prefers the facet aggregation API and falls back to a paged
    scroll when it is unavailable. Returns ``[]`` for an empty or missing
    collection, and never raises on a connection or collection error.
    """
    # Imported lazily so importing this module stays cheap and the heavy client
    # is only loaded when courses are actually requested, matching the codebase
    # style for optional/heavy dependencies.
    from qdrant_client import QdrantClient

    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    collection = settings.qdrant_collection

    courses = _facet_courses(client, collection)
    if courses is None:
        courses = _scroll_courses(client, collection)
    return sorted(courses)


def _facet_courses(client, collection: str) -> set[str] | None:
    """Collect distinct course values via the facet API, or None if unavailable.

    Returns the distinct values as a set, an empty set for an empty or missing
    collection, or ``None`` when the facet API cannot be used (e.g. the client
    lacks it), signalling the caller to fall back to scrolling.
    """
    facet = getattr(client, "facet", None)
    if facet is None:
        return None
    try:
        response = facet(collection_name=collection, key="course", limit=_FACET_LIMIT)
    except Exception:
        # The collection may not exist yet, or the server may not support facet:
        # fall back to the scroll path rather than failing the request.
        return None
    return {str(hit.value) for hit in response.hits}


def _scroll_courses(client, collection: str) -> set[str]:
    """Collect distinct course values by paging through points with payload.

    Bounded by ``_SCROLL_MAX_POINTS`` so the scan can never run unbounded.
    Returns an empty set for an empty or missing collection (any error is
    treated as "nothing indexed").
    """
    courses: set[str] = set()
    offset = None
    scanned = 0
    try:
        while scanned < _SCROLL_MAX_POINTS:
            points, offset = client.scroll(
                collection_name=collection,
                limit=_SCROLL_PAGE,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )
            for point in points:
                payload = point.payload or {}
                course = payload.get("course")
                if course is not None:
                    courses.add(str(course))
            scanned += len(points)
            if offset is None or not points:
                break
    except Exception:
        return courses
    return courses
