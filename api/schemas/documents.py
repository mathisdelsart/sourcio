"""Course/chapter discovery, document inventory, rename and source models."""

from pydantic import BaseModel


class CoursesResponse(BaseModel):
    """The distinct courses currently indexed in Qdrant, sorted."""

    courses: list[str]


class ChaptersResponse(BaseModel):
    """The distinct chapters of one course currently indexed in Qdrant, sorted."""

    chapters: list[str]


class DocumentChapter(BaseModel):
    """One chapter of a course and how many distinct pages it carries.

    ``chapter`` is ``None`` for material indexed without one (a UI groups it as
    "Uncategorized").
    """

    chapter: str | None = None
    pages: int


class DocumentCourse(BaseModel):
    """A course's indexed inventory: its chapters, page count and stored files."""

    course: str
    total_pages: int
    chapters: list[DocumentChapter]
    # Names of original uploaded files kept for this course (viewable via
    # GET /documents/file). Empty for material indexed outside the upload UI.
    files: list[str] = []


class DocumentDeleteResponse(BaseModel):
    """How many indexed points were removed by a delete request."""

    deleted: int


class DocumentRenameRequest(BaseModel):
    """Rename a course and/or a chapter of the caller's indexed material.

    ``student_id`` scopes the rename to the caller's own points (required — a
    rename is a per-account write). ``course`` names the course to act on. Set
    ``new_course`` to rename that course; set both ``chapter`` and ``new_chapter``
    to rename a chapter within the course. At least one of the two renames must be
    requested.
    """

    student_id: str
    course: str
    new_course: str | None = None
    chapter: str | None = None
    new_chapter: str | None = None


class DocumentRenameResponse(BaseModel):
    """How many indexed points a rename updated, split by field."""

    course_updated: int = 0
    chapter_updated: int = 0


class SourceResponse(BaseModel):
    """A cited source chunk: its full text and citation metadata.

    Lets a UI turn a citation into a readable excerpt. ``chapter`` may be absent
    for material indexed without a chapter, so it is optional.
    """

    id: str
    course: str
    chapter: str | None = None
    page: int
    text: str
