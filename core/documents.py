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
- :func:`rename_course` / :func:`rename_chapter` rewrite the ``course`` /
  ``chapter`` payload field on all of the caller's matching points with a
  filtered ``set_payload``, so a rename is reflected everywhere (inventory,
  pickers, retrieval filters, citations). Both are owner-scoped and fail-closed.

The Qdrant client is built from settings, matching ``core.courses`` and
``core.sources``.
"""

import os
import re
import time
from collections.abc import Iterator
from typing import Any

from core import storage
from core.config import get_settings
from core.errors import describe_capacity_error
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

# User-facing message when a scanned/image PDF needs the vision model but no
# OpenAI key is available (neither the visitor's nor a server env key). Text PDFs
# and .md/.txt import for free with local embeddings, so this only ever applies
# to image-based pages. It guides the UI to prompt the visitor for their own key.
MISSING_OPENAI_KEY_MESSAGE = (
    "This looks like a scanned or image-based PDF, which needs a vision model to "
    "read. Add your OpenAI API key to import it — text PDFs and .md/.txt files "
    "import for free without a key."
)

# Same failure but the visitor DID supply a key that the provider rejected (wrong
# value, no credit, or no vision-model access). A common cause is pasting a whole
# `OPENAI_API_KEY=...` line instead of just the key, so the message says so.
REJECTED_OPENAI_KEY_MESSAGE = (
    "The API key was rejected. Check that it is valid — that it has credit and "
    "access to a vision model, and that you pasted only the key itself (e.g. "
    "sk-…), not a whole 'OPENAI_API_KEY=…' line."
)


def _openai_key_error(extract_api_key: str | None) -> str:
    """Pick the missing-key vs rejected-key message by whether a key was supplied."""
    return REJECTED_OPENAI_KEY_MESSAGE if extract_api_key else MISSING_OPENAI_KEY_MESSAGE


def _is_missing_openai_credentials(exc: BaseException) -> bool:
    """Return whether ``exc`` is an OpenAI missing/invalid-credentials error.

    Detection is by exception class name and message so the OpenAI SDK never has
    to be imported here. Covers both LangChain's "Did not find openai_api_key"
    startup ValueError and the SDK's ``AuthenticationError`` (HTTP 401), which is
    what a scanned PDF hits when no key (visitor's or env) is available for the
    vision fallback. Unrelated errors return False and keep their own message.
    """
    haystack = f"{type(exc).__name__} {exc}".lower()
    return (
        "openai_api_key" in haystack
        or "authenticationerror" in haystack
        or "api_key client option must be set" in haystack
        or ("api key" in haystack and "openai" in haystack)
    )


def _is_pdf_file(path: str) -> bool:
    """Return whether ``path`` has a ``.pdf`` extension (case-insensitive)."""
    return os.path.splitext(path)[1].lower() == ".pdf"


def _slug(value: str) -> str:
    """Filesystem-safe slug for a course directory name.

    Dots survive the character filter, so a course named ``.`` or ``..`` would
    otherwise become a path-traversal component that escapes ``UPLOADS_DIR`` once
    joined. Those are rejected to the default, exactly like an empty slug.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if cleaned in {"", ".", ".."}:
        return "course"
    return cleaned


def _safe_filename(name: str) -> str:
    """Keep only the basename and strip anything path-like, to prevent traversal."""
    base = os.path.basename(name).strip()
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base)
    if base in {"", ".", ".."}:
        return "document"
    return base


def _safe_join(directory: str, name: str) -> str | None:
    """Join a sanitized ``name`` onto ``directory``, only if it stays inside.

    Defense in depth on top of :func:`_safe_filename`: both sides are resolved to
    absolute paths and the result must remain under ``directory``, so no crafted
    name can ever read or write outside the course's upload folder. Returns
    ``None`` when the resolved path would escape.
    """
    directory = os.path.abspath(directory)
    path = os.path.abspath(os.path.join(directory, _safe_filename(name)))
    if os.path.commonpath([directory, path]) != directory:
        return None
    return path


def _course_dir(course: str) -> str:
    return os.path.join(UPLOADS_DIR, _slug(course))


def _r2_key(course: str, filename: str) -> str:
    """R2 object key for a course file, mirroring the local ``<course>/<file>`` layout."""
    return f"{_slug(course)}/{_safe_filename(filename)}"


def _document_id(path: str) -> str:
    """Stable per-document identifier derived from the uploaded file name.

    The basename uniquely names a document within a course (uploads are stored as
    ``uploads/<course>/<filename>``). It is stamped on every page so two distinct
    files in the same course get distinct chunk ids and can be filtered/listed
    apart, and it scopes the incremental-skip check to a single document.
    """
    return _safe_filename(os.path.basename(path))


def save_upload(data: bytes, course: str, filename: str) -> str:
    """Persist an uploaded file under ``uploads/<course>/<filename>`` and return its path.

    Always writes a local copy: ingestion reads the file straight off disk right
    after this call (PyMuPDF's ``fitz.open`` and the prose loader both need a
    real filesystem path), well before any container restart could matter, so
    the local write happens unconditionally regardless of the durable backend.

    When Cloudflare R2 is configured (see :func:`core.storage.configured`) the
    same bytes are ALSO uploaded to R2 under the equivalent key. That R2 copy --
    not the local one -- is what makes the stored original survive a
    redeploy/sleep-wake cycle in production (see :func:`read_stored_file`). The
    R2 upload is best-effort: a failure there is silently swallowed rather than
    failing the upload/ingest request, which has already succeeded locally.
    """
    directory = _course_dir(course)
    path = _safe_join(directory, filename)
    if path is None:  # pragma: no cover - defensive; _safe_filename already contains it
        raise ValueError("Invalid upload filename")
    os.makedirs(directory, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    if storage.configured():
        try:
            storage.put_object(_r2_key(course, filename), data)
        except Exception:
            pass
    return path


def stored_file_path(course: str, name: str) -> str | None:
    """Resolve a previously stored original by course + filename, or None.

    Local-disk lookup only (the R2-aware read path is :func:`read_stored_file`).
    Guards against path traversal: the resolved path must stay inside the
    course's upload directory.
    """
    path = _safe_join(_course_dir(course), name)
    if path is None:
        return None
    return path if os.path.isfile(path) else None


def read_stored_file(course: str, name: str) -> bytes | None:
    """Return the bytes of a previously stored original, or ``None`` if not found.

    When R2 is configured it is tried first: it is the durable copy in
    production (the local copy written by :func:`save_upload` is a working copy
    for ingestion and does not survive a container restart there). Any local
    copy is used as a fallback when the R2 lookup misses -- e.g. a file uploaded
    before R2 was configured, or a transient R2 error -- so nothing that used to
    be viewable stops being viewable. When R2 is not configured this reduces to
    exactly the previous local-disk-only behavior.
    """
    if storage.configured():
        data = storage.get_object(_r2_key(course, name))
        if data is not None:
            return data
    path = stored_file_path(course, name)
    if path is None:
        return None
    with open(path, "rb") as handle:
        return handle.read()


def list_course_files(course: str) -> list[str]:
    """Names of the original files stored for a course (newest first).

    When R2 is configured its objects for this course are listed first (they
    are the durable, authoritative set in production); any name present only on
    local disk (e.g. uploaded before R2 was configured) is still appended, so
    nothing already visible becomes hidden. When R2 is not configured this
    reduces to exactly the previous local-disk-only behavior.
    """
    names: list[str] = []
    seen: set[str] = set()
    if storage.configured():
        prefix = _slug(course) + "/"
        for key in storage.list_keys(prefix):
            name = key[len(prefix) :]
            if name and name not in seen:
                names.append(name)
                seen.add(name)
    directory = _course_dir(course)
    if os.path.isdir(directory):
        local_names = [
            n for n in os.listdir(directory) if os.path.isfile(os.path.join(directory, n))
        ]
        local_names.sort(key=lambda n: os.path.getmtime(os.path.join(directory, n)), reverse=True)
        for name in local_names:
            if name not in seen:
                names.append(name)
                seen.add(name)
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
    "Uncategorized"). When ``owner`` is given the scroll is strictly scoped to the
    caller's *own* material, so an account only sees its own documents (no
    shared/legacy visibility). When ``owner`` is ``None`` the read is
    **fail-closed**: it returns ``[]`` without querying, since a document
    inventory is a per-account read and running it unscoped would list every
    account's material. Returns ``[]`` for an empty or missing collection and
    never raises on a connection or collection error.
    """
    # Fail closed: with no owner there is no caller to scope to, so return nothing
    # rather than listing every account's documents. The API always supplies the
    # caller's effective id; only a request with no identity reaches here as None.
    if owner is None:
        return []

    from core.retrieval import owner_scope_filter

    settings = get_settings()
    client = _client()
    collection = settings.qdrant_collection
    scroll_filter = owner_scope_filter(owner)

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


def _load_pages(path: str, course: str, *, extract_api_key: str | None = None) -> list[Page]:
    """Extract pages from an uploaded file, routing by extension.

    ``.md``/``.txt`` go through the prose loader (no model, no network, no key);
    ``.pdf`` is routed through the math-aware pipeline in **hybrid** mode, so
    plain-text pages (e.g. a prose PDF) are extracted for free and
    deterministically with PyMuPDF while only genuinely math/figure-heavy pages
    reach the vision model. ``extract_api_key`` (a visitor's own OpenAI key) is
    forwarded to the vision path only; the free text branch never sees it. A
    clearly-unsupported extension raises a clean :class:`ValueError` rather than
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
        return extract_pdf(
            path,
            course,
            hybrid=True,
            api_key=extract_api_key,
            concurrency=get_settings().ingest_concurrency,
        )
    except ValueError:
        raise
    except Exception as exc:
        # A missing/invalid OpenAI key on a scanned PDF surfaces as a clear,
        # actionable message instead of a raw SDK error.
        if _is_missing_openai_credentials(exc):
            raise ValueError(_openai_key_error(extract_api_key)) from exc
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
    the indexed chunks are scoped to that account. ``None`` leaves the material
    owner-less, which the CLI ingestion path may do; note that under strict
    isolation owner-less chunks are invisible to every account's reads (the API
    upload therefore requires a ``student_id`` and never leaves it null).
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
    extract_api_key: str | None = None,
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
    pages = _load_pages(path, course, extract_api_key=extract_api_key)
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
    batch_size: int | None = None,
    sparse: bool = False,
    extract_api_key: str | None = None,
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
    (``.md``/``.txt``) is loaded and indexed in one step (no model cost, no key).

    ``extract_api_key`` (a visitor's own OpenAI key) is forwarded only to the PDF
    vision path so a scanned/image PDF can be transcribed on the caller's own
    account; it is used transiently and never stored or logged. The free
    ``.md``/``.txt`` and plain-text-PDF paths neither receive nor need it.
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

    settings = get_settings()
    # Larger batches + concurrent vision (see Settings.ingest_*) import a big PDF
    # far faster; callers may still pass an explicit batch_size (e.g. tests).
    if batch_size is None:
        batch_size = settings.ingest_batch_size
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
            pages = extract_pdf(
                path,
                course,
                pages=batch,
                hybrid=True,
                api_key=extract_api_key,
                concurrency=settings.ingest_concurrency,
            )
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
        # A scanned/image PDF with no OpenAI key (visitor's or env) surfaces as a
        # clear, actionable message so the UI can guide the user to add their key;
        # a provider capacity error (free-tier TPM limit / rate limit) does too.
        message = (
            _openai_key_error(extract_api_key)
            if _is_missing_openai_credentials(exc)
            else describe_capacity_error(exc, used_own_key=bool(extract_api_key)) or str(exc)
        )
        yield {
            "type": "error",
            "message": message,
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
    given the deletion is strictly scoped to that account's *own* points via
    :func:`owner_scope_filter` — never another account's material and never the
    owner-less legacy corpus (which is invisible to reads too). When ``owner`` is
    ``None`` the delete is **fail-closed**: it returns ``0`` without deleting,
    since a delete is a per-account operation and running it unscoped would remove
    every account's points for that course. Returns the number of points removed;
    a missing collection or any error yields ``0`` rather than raising, so the
    endpoint degrades gracefully.
    """
    # Fail closed: with no owner there is no caller to scope to, so delete nothing
    # rather than wiping every account's points for the course. The API always
    # supplies the caller's effective id; only a request with no identity is None.
    if owner is None:
        return 0

    from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

    from core.retrieval import owner_scope_filter

    settings = get_settings()
    client = _client()
    collection = settings.qdrant_collection

    conditions: list[Any] = [FieldCondition(key="course", match=MatchValue(value=course))]
    if chapter is not None:
        conditions.append(FieldCondition(key="chapter", match=MatchValue(value=chapter)))
    # Strictly scope to the caller's own points: another account's OWNED points and
    # the owner-less legacy corpus never match, so neither can be deleted here.
    conditions.append(owner_scope_filter(owner))
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


def _set_payload_scoped(
    owner: str,
    course: str,
    chapter: str | None,
    payload: dict[str, Any],
) -> int:
    """Overwrite ``payload`` on the caller's points matching course(+chapter).

    Builds a payload filter on ``course`` (plus ``chapter`` when given) nested
    under the strict :func:`owner_scope_filter`, counts the matching points, then
    rewrites the given fields on exactly those points with ``set_payload``. The
    owner scope guarantees another account's OWNED points and the owner-less
    legacy corpus never match, so a rename can only ever touch the caller's own
    material — never a collection-wide update. Returns how many points were
    updated; any error yields ``0`` rather than raising, so the endpoint degrades
    gracefully. Callers guarantee ``owner`` is truthy (fail-closed happens above).
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from core.retrieval import owner_scope_filter

    settings = get_settings()
    client = _client()
    collection = settings.qdrant_collection

    conditions: list[Any] = [FieldCondition(key="course", match=MatchValue(value=course))]
    if chapter is not None:
        conditions.append(FieldCondition(key="chapter", match=MatchValue(value=chapter)))
    # Strictly scope to the caller's own points: another account's OWNED points and
    # the owner-less legacy corpus never match, so neither can be rewritten here.
    conditions.append(owner_scope_filter(owner))
    payload_filter = Filter(must=conditions)

    try:
        matched = client.count(
            collection_name=collection, count_filter=payload_filter, exact=True
        ).count
        # ``points`` accepts a Filter directly: only points matching it are updated,
        # never the whole collection.
        client.set_payload(
            collection_name=collection,
            payload=payload,
            points=payload_filter,
        )
    except Exception:
        return 0
    return matched


def _move_course_dir(old_course: str, new_course: str) -> None:
    """Best-effort rename of the stored originals so they follow a renamed course.

    Renaming the Qdrant payloads is what the app relies on; this keeps the
    stored originals viewable under the new course name too, on whichever
    backend(s) hold them. Both moves are independently best-effort and never
    raise — a failure here must not fail the payload rename that already
    succeeded:

    - local disk: only renames when the source dir exists and the destination
      does not (a merge into an existing course leaves the files where they
      are);
    - R2 (when configured): copies every object under the old course's key
      prefix to the new prefix, then deletes the old ones (S3/R2 has no atomic
      rename); a destination key that already exists is overwritten, matching
      the "merge into an existing course" behavior of the local-disk move.
    """
    try:
        source = _course_dir(old_course)
        dest = _course_dir(new_course)
        if os.path.isdir(source) and not os.path.exists(dest):
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            os.rename(source, dest)
    except Exception:
        pass
    if storage.configured():
        try:
            storage.copy_prefix(_slug(old_course) + "/", _slug(new_course) + "/")
        except Exception:
            pass


def rename_course(owner: str | None, old_course: str, new_course: str) -> int:
    """Rename a course on all of the caller's matching points; return the count.

    Rewrites the ``course`` payload field from ``old_course`` to a trimmed
    ``new_course`` on every one of the caller's own points for that course, so the
    new name shows up everywhere it is read (inventory, course/chapter pickers,
    retrieval filters, citations). Renaming onto an existing course name merges the
    two — that is acceptable and intentional. Also best-effort renames the stored
    upload folder so the originals stay viewable. When ``owner`` is falsy the
    rename is **fail-closed**: it returns ``0`` without touching Qdrant, so a
    request with no identity can never issue a collection-wide update. Returns
    ``0`` too when either name is empty/whitespace or unchanged.
    """
    new = (new_course or "").strip()
    # Fail closed: no owner -> touch nothing. Also skip empty/no-op renames.
    if not owner or not old_course or not new or new == old_course:
        return 0
    updated = _set_payload_scoped(owner, old_course, None, {"course": new})
    if updated:
        _move_course_dir(old_course, new)
    return updated


def rename_chapter(owner: str | None, course: str, old_chapter: str, new_chapter: str) -> int:
    """Rename a chapter within a course on the caller's matching points; return count.

    Rewrites the ``chapter`` payload field from ``old_chapter`` to a trimmed
    ``new_chapter`` on every one of the caller's own points for that
    ``course``/``chapter``, so the new name shows up everywhere it is read. Merging
    into an existing chapter of the same course is acceptable. When ``owner`` is
    falsy the rename is **fail-closed**: it returns ``0`` without touching Qdrant.
    Returns ``0`` too when the course, the old chapter or the new name is
    empty/whitespace, or when the name is unchanged. The chapterless
    ("Uncategorized") group has no chapter value to match and so cannot be renamed
    here.
    """
    new = (new_chapter or "").strip()
    # Fail closed: no owner -> touch nothing. Also skip empty/no-op renames.
    if not owner or not course or not old_chapter or not new or new == old_chapter:
        return 0
    return _set_payload_scoped(owner, course, old_chapter, {"chapter": new})
