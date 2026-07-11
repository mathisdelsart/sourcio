"""Document inventory, upload/ingest, retrieval, deletion and rename routes."""

import mimetypes
import os
import threading
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

import api.main as api_main
from api.auth import UserOut
from api.deps import (
    DataUser,
    OpenAIKey,
    _resolve_student,
    _scoped_read_owner,
    require_api_key,
)
from api.schemas import (
    DocumentCourse,
    DocumentDeleteResponse,
    DocumentRenameRequest,
    DocumentRenameResponse,
)
from core.errors import describe_capacity_error
from core.jobs import create_job, get_job, list_jobs, update_job
from db.session import get_session

router = APIRouter()


@router.get(
    "/documents",
    response_model=list[DocumentCourse],
    dependencies=[Depends(require_api_key)],
)
def documents(
    student_id: str | None = None, user: UserOut | None = DataUser
) -> list[dict[str, Any]]:
    """Return the indexed material organized by course and chapter.

    Lets a client show what is indexed (and how much) so a user can manage it.
    The shape is ``[{course, total_pages, chapters: [{chapter, pages}]}]`` with a
    ``null`` chapter for material indexed without one. When ``student_id`` is
    given the inventory is strictly scoped to that account's own material; without
    it the read is fail-closed (empty) rather than listing every account's
    material. Returns an empty list when nothing is indexed yet; it never reaches
    the LLM and runs no retrieval.
    """
    owner = _scoped_read_owner(student_id, user)
    return api_main.list_documents(owner=owner)


@router.post(
    "/documents/upload",
    dependencies=[Depends(require_api_key)],
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    file: Annotated[UploadFile, File()],
    course: Annotated[str, Form()],
    student_id: Annotated[str, Form()],
    chapter: Annotated[str | None, Form()] = None,
    openai_key: Annotated[str | None, Form()] = None,
    user: UserOut | None = DataUser,
    header_openai_key: str | None = OpenAIKey,
) -> dict[str, str]:
    """Start ingesting an uploaded file as a background job and return its id.

    The original file is stored under ``uploads/<course>/`` so it can be re-opened
    later, then ingested incrementally on a daemon thread: ``.md``/``.txt`` via the
    prose loader, anything else via the math-aware PDF vision path. The request
    returns ``{"job_id": ...}`` immediately (HTTP 202) instead of streaming, so
    ingestion is not tied to the request lifetime — a browser refresh or
    navigation no longer aborts the ingest. The client polls
    ``GET /documents/jobs/{job_id}`` to follow (or, after a refresh, re-attach to)
    progress; the job record carries the same ``start``/``progress``/``done``/
    ``error`` shape as ``stream_ingest`` plus a ``status`` lifecycle field.

    Each document is scoped by its own identity, so a second file in the same
    course indexes independently; only re-uploading the same document skips
    already-indexed pages (never re-paying the vision model), and each batch is
    indexed as it is extracted, so a failure keeps the pages done so far.

    A plain daemon thread is used deliberately: FastAPI ``BackgroundTasks`` run
    within the request scope (defeating the purpose), and ``stream_ingest`` is a
    blocking, synchronous generator so it cannot run on the event loop. The job
    registry is in-process — see the multi-worker caveat in ``core.jobs``.

    ``openai_key`` is an OPTIONAL, visitor-supplied OpenAI key used ONLY to
    transcribe a scanned/image PDF on the visitor's own account (so the app owner
    is never billed). SECURITY: it is used transiently for this one ingestion and
    is NEVER stored in the job record, NEVER logged (the request middleware does
    not log form bodies), and NEVER returned in any response. Text PDFs and
    ``.md``/``.txt`` files ingest for free and ignore it.
    """
    normalized_chapter = chapter.strip() if chapter and chapter.strip() else None
    # Normalise the visitor's key: an empty/whitespace value is treated as absent
    # so it is never forwarded. Kept only as a local; never persisted or logged.
    # The ``X-OpenAI-Key`` header (already trimmed/normalized by the dependency)
    # WINS over the legacy ``openai_key`` form field, so the global key set in the
    # UI flows through automatically; the form field stays a fallback so an older
    # upload flow still works.
    form_key = openai_key.strip() if openai_key and openai_key.strip() else None
    extract_api_key = header_openai_key or form_key
    # ``student_id`` is required so an upload is always stamped with an owner and
    # scoped to that account — never left owner-less (which strict isolation would
    # make invisible to everyone). Resolve (and, when authenticated, enforce
    # ownership of) the uploader before stamping.
    with get_session(api_main._engine) as session:
        _resolve_student(session, student_id, user)
    owner: str = student_id
    # Read the whole upload into memory (ingestion needs the bytes anyway) and
    # enforce the size cap on the actual byte count, not a client-supplied
    # Content-Length header, so a spoofed header cannot slip an oversized file
    # past the guard. This is a public-abuse safeguard.
    contents = await file.read()
    max_bytes = api_main.get_settings().max_upload_mb * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File too large: max {api_main.get_settings().max_upload_mb} MB.",
        )
    # Persist the original so the user can re-open the intact file later; ingest
    # from that stored path (its extension drives prose/PDF routing).
    stored_path = api_main.save_upload(contents, course, file.filename or "document")
    job_id = create_job(course, normalized_chapter, os.path.basename(stored_path))

    def run() -> None:
        """Drive the (blocking) ingest, mirroring each event into the job store."""
        try:
            for event in api_main.stream_ingest(
                stored_path,
                course,
                normalized_chapter,
                owner=owner,
                extract_api_key=extract_api_key,
            ):
                update_job(job_id, event)
                if event.get("type") == "error":
                    # stream_ingest reports a failed batch as an error event then
                    # returns; reflect it as a terminal status.
                    update_job(job_id, {"status": "error"})
                    return
            update_job(job_id, {"status": "done"})
        except Exception as exc:  # pragma: no cover - defensive; ingest guards itself
            message = describe_capacity_error(exc, used_own_key=bool(extract_api_key)) or str(exc)
            update_job(job_id, {"status": "error", "type": "error", "message": message})

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@router.get("/documents/jobs", dependencies=[Depends(require_api_key)])
def document_jobs() -> list[dict[str, Any]]:
    """List the current (running and recently finished) ingestion jobs."""
    return list_jobs()


@router.get("/documents/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def document_job(job_id: str) -> dict[str, Any]:
    """Return one ingestion job's record, or 404 if unknown or already pruned."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job


@router.get("/documents/file", dependencies=[Depends(require_api_key)])
def document_file(course: str, name: str) -> Response:
    """Serve a stored original file so the user can re-open it intact.

    ``course`` and ``name`` identify a file previously saved by an upload.
    ``read_stored_file`` resolves the bytes from whichever backend actually
    holds them -- Cloudflare R2 first when configured (the durable store in
    production), local disk otherwise or as a fallback -- with the same
    traversal guard as before on the local-disk side. The bytes are returned
    directly (rather than via ``FileResponse``) since an R2-backed file has no
    local path to stream from. An unknown file yields 404.
    """
    data = api_main.read_stored_file(course, name)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    media_type, _ = mimetypes.guess_type(name)
    filename = os.path.basename(name)
    return Response(
        content=data,
        media_type=media_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/documents",
    response_model=DocumentDeleteResponse,
    dependencies=[Depends(require_api_key)],
)
def remove_documents(
    course: str,
    chapter: str | None = None,
    student_id: str | None = None,
    user: UserOut | None = DataUser,
) -> dict[str, int]:
    """Delete a course's indexed points, optionally narrowed to one chapter.

    ``course`` is required; ``chapter`` (a query parameter) restricts the deletion
    to a single chapter when given. When ``student_id`` is given the deletion is
    strictly scoped to that account's OWN points only (never another account's
    material and never the owner-less legacy corpus); the student is resolved and
    ownership enforced exactly as elsewhere. Without a ``student_id`` the delete is
    fail-closed (removes nothing) rather than wiping every account's points.
    Returns how many points were removed. A missing collection or an unknown
    course yields ``{"deleted": 0}`` rather than an error; it never reaches the LLM
    and runs no retrieval.
    """
    owner: str | None = None
    if student_id is not None:
        with get_session(api_main._engine) as session:
            _resolve_student(session, student_id, user)
        owner = student_id
    return {"deleted": api_main.delete_documents(course, chapter, owner)}


@router.post(
    "/documents/rename",
    response_model=DocumentRenameResponse,
    dependencies=[Depends(require_api_key)],
)
def rename_documents(
    request: DocumentRenameRequest,
    user: UserOut | None = DataUser,
) -> dict[str, int]:
    """Rename a course and/or a chapter of the caller's indexed material.

    Set ``new_course`` to rename ``course``; set both ``chapter`` and
    ``new_chapter`` to rename that chapter within the course. Renaming rewrites the
    ``course``/``chapter`` payload on the caller's matching chunks, so the new name
    is reflected everywhere it is read (inventory, course/chapter pickers,
    retrieval filters, citations). ``student_id`` is required so the rename is
    stamped to and strictly scoped to that account's OWN points only (never another
    account's material and never the owner-less legacy corpus); the student is
    resolved and ownership enforced exactly as on upload/delete. Renaming onto an
    existing course/chapter name merges into it, which is acceptable. When a chapter
    rename is requested it is applied first (under the original course name) so a
    combined course+chapter rename in one call stays consistent. Returns how many
    points each field's rename updated; an unknown course/chapter or a no-op yields
    zeros rather than an error. It never reaches the LLM and runs no retrieval.
    """
    with get_session(api_main._engine) as session:
        _resolve_student(session, request.student_id, user)
    owner: str = request.student_id

    if request.new_course is None and not (request.chapter and request.new_chapter):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide new_course, or both chapter and new_chapter.",
        )

    # Rename the chapter first (under the ORIGINAL course name) so a combined
    # course+chapter rename in one call still matches; then rename the course.
    chapter_updated = 0
    if request.chapter and request.new_chapter:
        chapter_updated = api_main.rename_chapter(
            owner, request.course, request.chapter, request.new_chapter
        )
    course_updated = 0
    if request.new_course is not None:
        course_updated = api_main.rename_course(owner, request.course, request.new_course)
    return {"course_updated": course_updated, "chapter_updated": chapter_updated}
