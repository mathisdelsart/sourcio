"""Discovery of the courses (and their chapters) currently indexed in Qdrant.

Lists the distinct ``course`` payload values stored in the configured
collection, so a UI can populate a course picker dynamically instead of
hardcoding the list, plus the distinct ``chapter`` values of a given course so a
dependent chapter picker can be populated. This is read-only and grounded in
what is actually indexed: a course only appears once at least one of its chunks
lives in Qdrant.

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


def list_courses(owner: str | None = None) -> list[str]:
    """Return the sorted, distinct course names indexed in Qdrant.

    Builds a Qdrant client from settings (same construction as retrieval) and
    enumerates the distinct ``course`` payload values in the configured
    collection. Prefers the facet aggregation API and falls back to a paged
    scroll when it is unavailable. When ``owner`` is given, the aggregation is
    strictly scoped to the caller's *own* material, so an account only discovers
    its own courses (no shared/legacy visibility). When ``owner`` is ``None`` the
    read is **fail-closed**: it returns ``[]`` without querying, since a course
    listing is a per-account read and running it unscoped would enumerate every
    account's courses. Returns ``[]`` for an empty or missing collection, and
    never raises on a connection or collection error.
    """
    # Fail closed: with no owner there is no caller to scope to, so return nothing
    # rather than enumerating every account's courses. The API always supplies the
    # caller's effective id; only a request with no identity reaches here as None.
    if owner is None:
        return []

    # Imported lazily so importing this module stays cheap and the heavy client
    # is only loaded when courses are actually requested, matching the codebase
    # style for optional/heavy dependencies.
    from qdrant_client import QdrantClient

    from core.retrieval import owner_scope_filter

    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    collection = settings.qdrant_collection
    owner_filter = owner_scope_filter(owner)

    courses = _facet_courses(client, collection, owner_filter)
    if courses is None:
        courses = _scroll_courses(client, collection, owner_filter)
    return sorted(courses)


def list_chapters(course: str, owner: str | None = None) -> list[str]:
    """Return the sorted, distinct chapter names of ``course``, scoped to ``owner``.

    Enumerates the distinct, non-empty ``chapter`` payload values across the
    points whose ``course`` matches, so a UI can populate a chapter picker that
    depends on the chosen course. Prefers the facet aggregation API (filtered by
    course *and* owner) and falls back to a paged scroll when it is unavailable.
    The read is strictly scoped to the caller's *own* material via
    :func:`owner_scope_filter`, so an account only discovers chapters of its own
    courses. When ``owner`` is ``None`` the read is **fail-closed**: it returns
    ``[]`` without querying, since a chapter listing is a per-account read and
    running it unscoped would enumerate every account's material. Returns ``[]``
    for a course with no chapters, an empty or missing collection, and never
    raises on a connection or collection error.
    """
    # Fail closed: with no owner there is no caller to scope to, so return nothing
    # rather than enumerating every account's chapters (mirrors ``list_courses``).
    if owner is None:
        return []

    from qdrant_client import QdrantClient
    from qdrant_client.models import Condition, FieldCondition, Filter, MatchValue

    from core.retrieval import owner_scope_filter

    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    collection = settings.qdrant_collection
    # Scope strictly to the caller's own material AND the chosen course. The owner
    # condition is nested via the shared ``owner_scope_filter`` (same pattern as
    # retrieval's ``_build_filter``) so the isolation stays consistent with reads.
    conditions: list[Condition] = [
        FieldCondition(key="course", match=MatchValue(value=course)),
        owner_scope_filter(owner),
    ]
    scope_filter = Filter(must=conditions)

    chapters = _facet_distinct(client, collection, "chapter", scope_filter)
    if chapters is None:
        chapters = _scroll_distinct(client, collection, "chapter", scope_filter)
    # Only non-empty chapters: material indexed without one must not surface as a
    # blank option (the facet path may return "" for such points).
    return sorted(value for value in chapters if value)


def _facet_courses(client, collection: str, owner_filter=None) -> set[str] | None:
    """Collect distinct course values via the facet API, or None if unavailable."""
    return _facet_distinct(client, collection, "course", owner_filter)


def _scroll_courses(client, collection: str, owner_filter=None) -> set[str]:
    """Collect distinct course values by paging through points with payload."""
    return _scroll_distinct(client, collection, "course", owner_filter)


def _facet_distinct(client, collection: str, key: str, scope_filter=None) -> set[str] | None:
    """Collect distinct values of a payload ``key`` via the facet API, or None.

    Returns the distinct values as a set, an empty set for an empty or missing
    collection, or ``None`` when the facet API cannot be used (e.g. the client
    lacks it), signalling the caller to fall back to scrolling. ``scope_filter``,
    when given, strictly scopes the aggregation (e.g. to the caller's own material
    and, for chapters, to a single course).
    """
    facet = getattr(client, "facet", None)
    if facet is None:
        return None
    try:
        response = facet(
            collection_name=collection,
            key=key,
            facet_filter=scope_filter,
            limit=_FACET_LIMIT,
        )
    except Exception:
        # The collection may not exist yet, or the server may not support facet:
        # fall back to the scroll path rather than failing the request.
        return None
    return {str(hit.value) for hit in response.hits}


def _scroll_distinct(client, collection: str, key: str, scope_filter=None) -> set[str]:
    """Collect distinct values of a payload ``key`` by paging through points.

    Bounded by ``_SCROLL_MAX_POINTS`` so the scan can never run unbounded.
    Returns an empty set for an empty or missing collection (any error is
    treated as "nothing indexed"). ``scope_filter``, when given, strictly scopes
    the scan (e.g. to the caller's own material and, for chapters, to a course).
    """
    values: set[str] = set()
    offset = None
    scanned = 0
    try:
        while scanned < _SCROLL_MAX_POINTS:
            points, offset = client.scroll(
                collection_name=collection,
                scroll_filter=scope_filter,
                limit=_SCROLL_PAGE,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )
            for point in points:
                payload = point.payload or {}
                value = payload.get(key)
                if value is not None:
                    values.add(str(value))
            scanned += len(points)
            if offset is None or not points:
                break
    except Exception:
        return values
    return values
