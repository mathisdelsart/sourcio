"""Course and chapter discovery routes (owner-scoped)."""

from fastapi import APIRouter, Depends

import api.main as api_main
from api.auth import UserOut
from api.deps import DataUser, _scoped_read_owner, require_api_key
from api.schemas import ChaptersResponse, CoursesResponse

router = APIRouter()


@router.get(
    "/courses",
    response_model=CoursesResponse,
    dependencies=[Depends(require_api_key)],
)
def courses(student_id: str | None = None, user: UserOut | None = DataUser) -> dict[str, list[str]]:
    """List the distinct courses currently indexed in Qdrant.

    Lets a client discover the available courses dynamically (e.g. to populate a
    picker) instead of hardcoding them. When ``student_id`` is given the list is
    strictly scoped to that account's own courses; without it the read is
    fail-closed (empty) rather than listing every account's courses. Returns an
    empty list when nothing is indexed yet; it never reaches the LLM and runs no
    retrieval.
    """
    owner = _scoped_read_owner(student_id, user)
    return {"courses": api_main.list_courses(owner=owner)}


@router.get(
    "/chapters",
    response_model=ChaptersResponse,
    dependencies=[Depends(require_api_key)],
)
def chapters(
    course: str, student_id: str | None = None, user: UserOut | None = DataUser
) -> dict[str, list[str]]:
    """List the distinct chapters of ``course`` currently indexed, sorted.

    Lets a client populate a chapter picker that depends on the chosen course
    instead of hardcoding chapters. When ``student_id`` is given the list is
    strictly scoped to that account's own material; without it the read is
    fail-closed (empty) rather than listing every account's chapters. Returns an
    empty list when the course has no chapters or nothing is indexed yet; it
    never reaches the LLM and runs no retrieval.
    """
    owner = _scoped_read_owner(student_id, user)
    return {"chapters": api_main.list_chapters(course, owner=owner)}
