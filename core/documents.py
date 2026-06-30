"""Inventory and management of the course material indexed in Qdrant.

A thin management layer on top of the existing ingestion pipeline and Qdrant
client. It exposes three operations a "Documents" UI needs:

- :func:`list_documents` builds an organized inventory by scrolling the stored
  payloads (``course``/``chapter``/``page``) and grouping pages per course and
  chapter. It is read-only and grounded in what is actually indexed; an empty or
  missing collection yields an empty list rather than raising.
- :func:`ingest_document` ingests one uploaded file (``.pdf`` via the math-aware
  vision pipeline, ``.md``/``.txt`` via the prose loader) under a given
  course/chapter, reusing exactly the same extract -> chunk -> index path as the
  ingestion CLI. The heavy extract/embed/index calls live behind module-level
  names so a test can stub them without loading any model.
- :func:`delete_documents` removes the points of a course (optionally narrowed to
  one chapter) with a payload filter, returning how many points were removed.

The Qdrant client is built from settings, matching ``core.courses`` and
``core.sources``.
"""

from typing import Any

from core.config import get_settings
from ingestion.chunk import chunk_pages
from ingestion.index import index_chunks
from ingestion.load import is_text_file, load_text_file
from ingestion.schema import Page

# Cap on how many points to scan when building the inventory, so an unexpectedly
# large collection can never make the enumeration unbounded.
_SCROLL_PAGE = 256
_SCROLL_MAX_POINTS = 100_000


def _client():
    """Build a Qdrant client from settings (same construction as retrieval)."""
    from qdrant_client import QdrantClient

    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)


def _format_inventory(index: dict[str, dict[Any, set[int]]]) -> list[dict[str, Any]]:
    """Render the collected ``course -> chapter -> pages`` map as the API shape.

    Courses are sorted by name; within a course, chapters are sorted with the
    chapterless group (``None``) last. ``pages`` counts the distinct page numbers
    seen for that chapter, and ``total_pages`` is their sum across the course.
    """
    result: list[dict[str, Any]] = []
    for course in sorted(index):
        chapters_map = index[course]
        chapters: list[dict[str, Any]] = []
        total = 0
        for chapter in sorted(chapters_map, key=lambda c: (c is None, c or "")):
            count = len(chapters_map[chapter])
            total += count
            chapters.append({"chapter": chapter, "pages": count})
        result.append({"course": course, "total_pages": total, "chapters": chapters})
    return result


def list_documents() -> list[dict[str, Any]]:
    """Return the indexed material organized by course and chapter.

    Scrolls the configured collection (payload only) and groups the distinct
    ``page`` numbers per ``course`` and ``chapter``. The shape is
    ``[{course, total_pages, chapters: [{chapter, pages}]}]`` where ``chapter``
    is ``None`` for material indexed without one (a UI groups it as
    "Uncategorized"). Returns ``[]`` for an empty or missing collection and never
    raises on a connection or collection error.
    """
    settings = get_settings()
    client = _client()
    collection = settings.qdrant_collection

    # course -> chapter (str | None) -> set of distinct page numbers.
    index: dict[str, dict[Any, set[int]]] = {}
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
                if course is None:
                    continue
                chapter = payload.get("chapter")
                pages = index.setdefault(str(course), {}).setdefault(chapter, set())
                page = payload.get("page")
                if page is not None:
                    pages.add(int(page))
            scanned += len(points)
            if offset is None or not points:
                break
    except Exception:
        # Treat any scroll/collection error as "nothing indexed" rather than
        # failing the request, matching core.courses' graceful degradation.
        return _format_inventory(index)
    return _format_inventory(index)


def _load_pages(path: str, course: str) -> list[Page]:
    """Extract pages from an uploaded file, routing by extension.

    ``.md``/``.txt`` go through the prose loader (no model, no network); anything
    else is treated as a PDF and routed through the math-aware vision pipeline.
    ``extract_pdf`` is imported lazily so the heavy PDF dependency (PyMuPDF) stays
    optional and a stubbed test never triggers it.
    """
    if is_text_file(path):
        return load_text_file(path, course)
    from ingestion.extract import extract_pdf

    return extract_pdf(path, course)


def ingest_document(
    path: str, course: str, chapter: str | None = None, *, sparse: bool = False
) -> int:
    """Ingest one uploaded file under ``course``/``chapter`` and return the count.

    Reuses the exact extract -> chunk -> index path of the ingestion CLI. When a
    ``chapter`` is given it overrides the source-derived chapter on every page so
    the uploaded material is filed under the user's chosen chapter; otherwise the
    pipeline's own chapter (the file stem for prose, ``None`` for slides) is kept.
    Returns the number of indexed chunks (``0`` when the file has no content).
    """
    pages = _load_pages(path, course)
    if chapter is not None:
        for page in pages:
            page.chapter = chapter
    if not pages:
        return 0
    chunks = chunk_pages(pages)
    if not chunks:
        return 0
    index_chunks(chunks, sparse=sparse)
    return len(chunks)


def delete_documents(course: str, chapter: str | None = None) -> int:
    """Delete a course's points (optionally one chapter) and return how many.

    Builds a payload filter on ``course`` (plus ``chapter`` when given), counts
    the matching points, then deletes them with that filter. Returns the number
    of points removed; a missing collection or any error yields ``0`` rather than
    raising, so the endpoint degrades gracefully.
    """
    from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

    settings = get_settings()
    client = _client()
    collection = settings.qdrant_collection

    conditions: list[Any] = [FieldCondition(key="course", match=MatchValue(value=course))]
    if chapter is not None:
        conditions.append(FieldCondition(key="chapter", match=MatchValue(value=chapter)))
    payload_filter = Filter(must=conditions)

    try:
        matched = client.count(
            collection_name=collection, count_filter=payload_filter, exact=True
        ).count
        client.delete(
            collection_name=collection,
            points_selector=FilterSelector(filter=payload_filter),
        )
    except Exception:
        return 0
    return matched
