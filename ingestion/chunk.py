"""Adaptive chunking.

Slides carry little text but strong per-slide structure, so one slide maps to
one chunk (token-based splitting would glue several slides together). Prose
documents (Markdown / text course files) are split upstream by
:mod:`ingestion.load` into overlapping word windows, each already a ready
``Page``; here each prose window likewise maps to one chunk.

Each chunk carries {course, chapter, page} metadata used to build citations.
"""

import logging
import uuid

from ingestion.schema import Chunk, Page

logger = logging.getLogger(__name__)


def _chunk_id(
    course: str,
    page: int,
    chapter: str | None,
    document: str | None = None,
    owner: str | None = None,
) -> str:
    """Stable UUID so re-ingesting a course overwrites rather than duplicates.

    Qdrant point ids must be unsigned ints or UUIDs, hence uuid5 over a stable
    key. When a ``document`` identifier is known (uploads), it is folded into the
    key so two decks in the same course never share a page number and thus never
    overwrite one another (slide page numbers are per-document 1..N). Prose
    ``page`` is only a per-document window index, so the document's ``chapter`` is
    also folded in to keep windows from different files distinct.

    When an ``owner`` is known (per-account uploads) it is also folded into the
    key so two accounts uploading the same course + filename never collide on the
    same point id (one would otherwise overwrite the other's chunk). When
    ``owner`` is ``None`` (CLI / shared corpus) the key is unchanged.

    When ``document`` is ``None`` (CLI ingestion) the legacy key is kept, so
    existing slide ids stay byte-identical: ``course``+``page`` for slides
    (``chapter`` is None) and ``course``+``chapter``+``page`` for prose.
    """
    if document is not None:
        base = f"{course}-{document}"
    else:
        base = course
    if owner is not None:
        base = f"{owner}-{base}"
    key = f"{base}-p{page}" if chapter is None else f"{base}-{chapter}-p{page}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def chunk_pages(pages: list[Page], *, log_sample: int = 3) -> list[Chunk]:
    """Turn extracted pages into retrievable chunks.

    Both slide pages (one per slide) and prose windows (one per word window from
    :mod:`ingestion.load`) map one-to-one to a chunk; only the chunk-id key
    differs (see :func:`_chunk_id`). Empty pages (e.g. title or section dividers
    with no content) are dropped. A few chunks are logged for visual inspection
    before the pipeline is trusted.
    """
    chunks: list[Chunk] = []
    for page in pages:
        if page.doc_type not in ("slides", "prose"):
            raise NotImplementedError(f"chunking for doc_type={page.doc_type!r}")
        if not page.text.strip():
            continue
        chunks.append(
            Chunk(
                id=_chunk_id(page.course, page.page, page.chapter, page.document, page.owner),
                course=page.course,
                page=page.page,
                text=page.text,
                chapter=page.chapter,
                document=page.document,
                owner=page.owner,
            )
        )

    for chunk in chunks[:log_sample]:
        logger.info("chunk %s (p.%d):\n%s\n", chunk.id, chunk.page, chunk.text[:400])

    return chunks
