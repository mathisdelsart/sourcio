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

import os
import re
import time
from collections.abc import Iterator
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

# Where uploaded originals are kept so a user can re-open the intact file later.
# Overridable for tests/deploys; gitignored.
UPLOADS_DIR = os.environ.get("DOCUMENTS_DIR", "uploads")

# User-facing message when an upload is neither a PDF nor a supported text file.
# Surfaced as a clean ``error`` event / raised error instead of a raw fitz crash.
UNSUPPORTED_FILE_MESSAGE = "Unsupported file type — upload a PDF, .md or .txt"


def _is_pdf_file(path: str) -> bool:
    """Return whether ``path`` has a ``.pdf`` extension (case-insensitive)."""
    return os.path.splitext(path)[1].lower() == ".pdf"


def _slug(value: str) -> str:
    """Filesystem-safe slug for a course directory name."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return cleaned or "course"


def _safe_filename(name: str) -> str:
    """Keep only the basename and strip anything path-like, to prevent traversal."""
    base = os.path.basename(name).strip()
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base)
    return base or "document"


def _course_dir(course: str) -> str:
    return os.path.join(UPLOADS_DIR, _slug(course))


def _document_id(path: str) -> str:
    """Stable per-document identifier derived from the uploaded file name.

    The basename uniquely names a document within a course (uploads are stored as
    ``uploads/<course>/<filename>``). It is stamped on every page so two distinct
    files in the same course get distinct chunk ids and can be filtered/listed
    apart, and it scopes the incremental-skip check to a single document.
    """
    return _safe_filename(os.path.basename(path))


def save_upload(data: bytes, course: str, filename: str) -> str:
    """Persist an uploaded file under ``uploads/<course>/<filename>`` and return its path."""
    directory = _course_dir(course)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, _safe_filename(filename))
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def stored_file_path(course: str, name: str) -> str | None:
    """Resolve a previously stored original by course + filename, or None.

    Guards against path traversal: the resolved path must stay inside the
    course's upload directory.
    """
    directory = os.path.abspath(_course_dir(course))
    path = os.path.abspath(os.path.join(directory, _safe_filename(name)))
    if os.path.commonpath([directory, path]) != directory:
        return None
    return path if os.path.isfile(path) else None


def list_course_files(course: str) -> list[str]:
    """Names of the original files stored for a course (newest first)."""
    directory = _course_dir(course)
    if not os.path.isdir(directory):
        return []
    names = [n for n in os.listdir(directory) if os.path.isfile(os.path.join(directory, n))]
    names.sort(key=lambda n: os.path.getmtime(os.path.join(directory, n)), reverse=True)
    return names


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


def list_documents(owner: str | None = None) -> list[dict[str, Any]]:
    """Return the indexed material organized by course and chapter.

    Scrolls the configured collection (payload only) and groups the distinct
    ``page`` numbers per ``course`` and ``chapter``. The shape is
    ``[{course, total_pages, chapters: [{chapter, pages}]}]`` where ``chapter``
    is ``None`` for material indexed without one (a UI groups it as
    "Uncategorized"). When ``owner`` is given the scroll is scoped to the caller's
    own or owner-less (shared/legacy) material, so an account only sees its own
    documents plus the shared corpus. Returns ``[]`` for an empty or missing
    collection and never raises on a connection or collection error.
    """
    from core.retrieval import owner_scope_filter

    settings = get_settings()
    client = _client()
    collection = settings.qdrant_collection
    scroll_filter = owner_scope_filter(owner) if owner is not None else None

    # course -> chapter (str | None) -> set of distinct page numbers.
    index: dict[str, dict[Any, set[int]]] = {}
    offset = None
    scanned = 0
    try:
        while scanned < _SCROLL_MAX_POINTS:
            points, offset = client.scroll(
                collection_name=collection,
                scroll_filter=scroll_filter,
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
        pass
    result = _format_inventory(index)
    # Attach the stored original files (if any) so the UI can offer "view".
    for course in result:
        course["files"] = list_course_files(str(course["course"]))
    return result


def _indexed_pages(course: str, document: str | None = None, owner: str | None = None) -> set[int]:
    """Page numbers already indexed for a specific document, so a retry can skip.

    This is what makes a retry free: a page already in Qdrant is never sent to
    the (paid) vision model again. The filter is scoped to ``course`` **and**
    ``document`` so a fresh document (whose page numbers 1..N would otherwise
    collide with pages already indexed for the course) is never wrongly skipped;
    only re-uploading the *same* document skips. It is further scoped to ``owner``
    so a different account re-uploading the same filename is not wrongly skipped
    (their pages have a distinct owner). Any error degrades to an empty set
    (nothing skipped) rather than failing the ingest.
    """
    settings = get_settings()
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    conditions: list[Any] = [FieldCondition(key="course", match=MatchValue(value=course))]
    if document is not None:
        conditions.append(FieldCondition(key="document", match=MatchValue(value=document)))
    if owner is not None:
        conditions.append(FieldCondition(key="owner", match=MatchValue(value=owner)))
    pages: set[int] = set()
    offset = None
    scanned = 0
    try:
        client = _client()
        course_filter = Filter(must=conditions)
        while scanned < _SCROLL_MAX_POINTS:
            points, offset = client.scroll(
                collection_name=settings.qdrant_collection,
                scroll_filter=course_filter,
                limit=_SCROLL_PAGE,
                with_payload=["page"],
                with_vectors=False,
                offset=offset,
            )
            for point in points:
                page = (point.payload or {}).get("page")
                if page is not None:
                    pages.add(int(page))
            scanned += len(points)
            if offset is None or not points:
                break
    except Exception:
        return set()
    return pages


def _load_pages(path: str, course: str) -> list[Page]:
    """Extract pages from an uploaded file, routing by extension.

    ``.md``/``.txt`` go through the prose loader (no model, no network); ``.pdf``
    is routed through the math-aware pipeline in **hybrid** mode, so plain-text
    pages (e.g. a prose PDF) are extracted for free and deterministically with
    PyMuPDF while only genuinely math/figure-heavy pages reach the vision model.
    A clearly-unsupported extension raises a clean :class:`ValueError` rather than
    letting a raw fitz error escape. ``extract_pdf`` is imported lazily so the
    heavy PDF dependency (PyMuPDF) stays optional and a stubbed test never triggers
    it.
    """
    if is_text_file(path):
        return load_text_file(path, course)
    if not _is_pdf_file(path):
        raise ValueError(UNSUPPORTED_FILE_MESSAGE)
    from ingestion.extract import extract_pdf

    try:
        return extract_pdf(path, course, hybrid=True)
    except ValueError:
        raise
    except Exception as exc:
        # A corrupt/unreadable PDF (fitz.open failure) surfaces as a clean error
        # rather than an opaque low-level exception.
        raise ValueError(f"Could not read the PDF: {exc}") from exc


def _stamp_pages(
    pages: list[Page], chapter: str | None, document: str, owner: str | None = None
) -> None:
    """Stamp the document identity (and chosen chapter, if any) onto every page.

    The document id distinguishes this upload from every other file in the course
    (see :func:`_document_id`); a non-empty ``chapter`` overrides the
    source-derived one so the material is filed under the user's chosen chapter.
    ``owner`` (the uploader's effective ``student_id``) is stamped on every page so
    the indexed chunks are scoped to that account; ``None`` leaves the material
    owner-less (shared/legacy), preserving the CLI ingestion behaviour.
    """
    for page in pages:
        page.document = document
        page.owner = owner
        if chapter is not None:
            page.chapter = chapter


def _done_reason(indexed: int, skipped: int) -> str:
    """Classify a finished ingest so a true 0 is reported honestly.

    - ``"indexed"``: new chunks were added this run.
    - ``"already_indexed"``: nothing new, but the document was already indexed.
    - ``"empty"``: nothing new and nothing was there — no text could be
      extracted. The file is blank/whitespace prose, or an image-only PDF the
      current extractor cannot read (a weak/local vision model returned nothing
      and PyMuPDF found no text). The UI maps this reason to a message that
      suggests configuring an OpenAI extract model (``LLM_EXTRACT``) for such
      image-only files.
    """
    if indexed > 0:
        return "indexed"
    if skipped > 0:
        return "already_indexed"
    return "empty"


def ingest_document(
    path: str,
    course: str,
    chapter: str | None = None,
    *,
    owner: str | None = None,
    sparse: bool = False,
) -> int:
    """Ingest one uploaded file under ``course``/``chapter`` and return the count.

    Reuses the exact extract -> chunk -> index path of the ingestion CLI. When a
    ``chapter`` is given it overrides the source-derived chapter on every page so
    the uploaded material is filed under the user's chosen chapter; otherwise the
    pipeline's own chapter (the file stem for prose, ``None`` for slides) is kept.
    Every page is stamped with the document identity so distinct files in the same
    course never collide or overwrite one another, and with ``owner`` (the
    uploader's effective ``student_id``) so the material is scoped to that account.
    Returns the number of indexed chunks (``0`` when the file has no content).
    """
    pages = _load_pages(path, course)
    _stamp_pages(pages, chapter, _document_id(path), owner)
    if not pages:
        return 0
    chunks = chunk_pages(pages)
    if not chunks:
        return 0
    index_chunks(chunks, sparse=sparse)
    return len(chunks)


def stream_ingest(
    path: str,
    course: str,
    chapter: str | None = None,
    *,
    owner: str | None = None,
    batch_size: int = 3,
    sparse: bool = False,
) -> Iterator[dict[str, Any]]:
    """Ingest a file incrementally, yielding progress events.

    Yields, in order:
    - ``{"type": "start", "total": N, "skipped": K}`` once,
    - ``{"type": "progress", "done", "total", "indexed", "elapsed"}`` per batch,
    - ``{"type": "done", "indexed", "skipped", "total", "reason", "elapsed"}`` on
      success, where ``reason`` (``"indexed"`` / ``"already_indexed"`` /
      ``"empty"``) lets the UI report a true 0 honestly rather than as a plain
      success, or
    - ``{"type": "error", "message", ...}`` if a batch fails (earlier batches stay
      indexed — work is never lost).

    Each document is scoped by its own identity (the stored file name), so two
    different files in the same course never collide or overwrite one another, and
    only re-uploading the *same* document skips already-indexed pages (never
    re-paying the vision model). Each PDF batch is indexed as soon as it is
    extracted, so a mid-way failure keeps the pages done so far. Prose
    (``.md``/``.txt``) is loaded and indexed in one step (no model cost).
    """
    started = time.time()
    document = _document_id(path)

    if is_text_file(path):
        try:
            pages = load_text_file(path, course)
        except Exception as exc:
            # A decode error (e.g. non-UTF-8 bytes) must surface as a clean error
            # event rather than break the SSE stream mid-flight.
            yield {
                "type": "error",
                "message": str(exc),
                "done": 0,
                "total": 0,
                "indexed": 0,
                "elapsed": round(time.time() - started, 1),
            }
            return
        _stamp_pages(pages, chapter, document, owner)
        total = len(pages)
        yield {"type": "start", "total": total, "skipped": 0}
        chunks = chunk_pages(pages) if pages else []
        if chunks:
            index_chunks(chunks, sparse=sparse)
        indexed = len(chunks)
        yield {
            "type": "done",
            "indexed": indexed,
            "skipped": 0,
            "total": total,
            "reason": _done_reason(indexed, 0),
            "elapsed": round(time.time() - started, 1),
        }
        return

    # A clearly-unsupported extension (not a PDF, and not caught above as text)
    # is reported cleanly up front rather than failing later with a raw fitz error.
    if not _is_pdf_file(path):
        yield {
            "type": "error",
            "message": UNSUPPORTED_FILE_MESSAGE,
            "done": 0,
            "total": 0,
            "indexed": 0,
            "elapsed": round(time.time() - started, 1),
        }
        return

    from ingestion.extract import extract_pdf
    from ingestion.run import _pdf_page_count

    total = 0
    done = 0
    indexed = 0
    skipped = 0
    try:
        # Inside the try so a non-PDF / corrupt file (fitz.open failure) surfaces
        # as a clean error event instead of an unhandled exception breaking the
        # SSE stream mid-flight.
        total = _pdf_page_count(path)
        already = _indexed_pages(course, document, owner)
        todo = [p for p in range(1, total + 1) if p not in already]
        skipped = total - len(todo)  # pages already indexed for THIS document
        done = skipped  # count already-indexed pages as done for the bar
        yield {"type": "start", "total": total, "skipped": skipped}

        for start in range(0, len(todo), batch_size):
            batch = todo[start : start + batch_size]
            # hybrid=True: plain-text pages are extracted for free with PyMuPDF
            # (deterministic, no model), so a text PDF indexes even when the
            # configured vision model is weak/absent; only math/figure-heavy pages
            # reach the vision model.
            pages = extract_pdf(path, course, pages=batch, hybrid=True)
            _stamp_pages(pages, chapter, document, owner)
            chunks = chunk_pages(pages)
            if chunks:
                index_chunks(chunks, sparse=sparse)
                indexed += len(chunks)
            done += len(batch)
            yield {
                "type": "progress",
                "done": done,
                "total": total,
                "indexed": indexed,
                "elapsed": round(time.time() - started, 1),
            }
    except Exception as exc:
        yield {
            "type": "error",
            "message": str(exc),
            "done": done,
            "total": total,
            "indexed": indexed,
            "elapsed": round(time.time() - started, 1),
        }
        return

    yield {
        "type": "done",
        "indexed": indexed,
        "skipped": skipped,
        "total": total,
        "reason": _done_reason(indexed, skipped),
        "elapsed": round(time.time() - started, 1),
    }


def delete_documents(course: str, chapter: str | None = None, owner: str | None = None) -> int:
    """Delete a course's points (optionally one chapter) and return how many.

    Builds a payload filter on ``course`` (plus ``chapter`` when given), counts
    the matching points, then deletes them with that filter. When ``owner`` is
    given the deletion is scoped to ``owner``'s OWN points only (an exact
    ``owner`` match, never the shared/legacy branch), so an account can never
    delete the shared corpus or another account's material. Returns the number of
    points removed; a missing collection or any error yields ``0`` rather than
    raising, so the endpoint degrades gracefully.
    """
    from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

    settings = get_settings()
    client = _client()
    collection = settings.qdrant_collection

    conditions: list[Any] = [FieldCondition(key="course", match=MatchValue(value=course))]
    if chapter is not None:
        conditions.append(FieldCondition(key="chapter", match=MatchValue(value=chapter)))
    if owner is not None:
        # Mine-only: an exact owner match (not the shared/legacy OR branch), so a
        # user can never delete owner-less (shared) points or another account's.
        conditions.append(FieldCondition(key="owner", match=MatchValue(value=owner)))
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
