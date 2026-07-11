"""Cited source resolution route: turn a chunk id into its excerpt (owner-scoped)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

import api.main as api_main
from api.auth import UserOut
from api.deps import DataUser, _scoped_read_owner, require_api_key
from api.schemas import SourceResponse

router = APIRouter()


@router.get(
    "/source/{chunk_id}",
    response_model=SourceResponse,
    dependencies=[Depends(require_api_key)],
)
def source(
    chunk_id: str, student_id: str | None = None, user: UserOut | None = DataUser
) -> dict[str, Any]:
    """Return a cited source chunk's full text and citation metadata.

    Lets a client resolve a citation (the chunk id surfaced with an answer) into
    the underlying course excerpt, so a UI can show what an answer was grounded
    in. When ``student_id`` is given the lookup is strictly owner-scoped to that
    account's own material, so one account cannot read another's chunk by guessing
    its deterministic id; an authenticated caller passing a foreign student id is
    rejected with 403. A chunk owned by a different account (or an owner-less
    legacy chunk) is reported as 404 (its existence never leaks). Without a
    ``student_id`` the lookup is fail-closed (404) rather than unscoped. Yields
    404 when the id is unknown or the collection is missing; it never reaches the
    LLM and runs no retrieval.
    """
    owner = _scoped_read_owner(student_id, user)
    chunk = api_main.get_source(chunk_id, owner=owner)
    if chunk is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source chunk not found.",
        )
    return chunk
