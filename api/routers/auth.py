"""Account and identity routes: register, login, current user, owned students."""

from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import select

import api.main as api_main
from api.auth import (
    CurrentUser,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
    login_user,
    register_user,
)
from api.deps import _iso_utc
from api.schemas import StudentOut
from db.models import Student
from db.session import get_session

router = APIRouter()


@router.post(
    "/auth/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
def auth_register(request: RegisterRequest) -> UserOut:
    """Create a new account from a username and password.

    The password is hashed with bcrypt before storage. Returns 201 with the
    minimal user info on success, 409 when the username is already taken, and
    422 on invalid input. This route is additive and does not affect the
    existing endpoints or the ``X-API-Key`` guard.
    """
    return register_user(request)


@router.post("/auth/login", response_model=TokenResponse)
def auth_login(request: LoginRequest) -> TokenResponse:
    """Verify credentials and return a signed bearer access token.

    Returns ``{access_token, token_type}`` on success or 401 on bad credentials
    (same message for unknown username and wrong password).
    """
    return login_user(request)


@router.get("/auth/me", response_model=UserOut)
def auth_me(current_user: UserOut = CurrentUser) -> UserOut:
    """Return the currently authenticated user.

    Protected by ``get_current_user``: the request must carry a valid
    ``Authorization: Bearer <jwt>`` header, otherwise 401 is returned.
    """
    return current_user


@router.get("/me/students", response_model=list[StudentOut])
def my_students(current_user: UserOut = CurrentUser) -> list[dict[str, Any]]:
    """List the student identities owned by the authenticated caller.

    Protected by ``get_current_user``: the request must carry a valid bearer
    token, otherwise 401 is returned. Only students linked to this user are
    returned, so a caller never sees another account's data or the anonymous,
    unlinked students. The list is newest-first.
    """
    with get_session(api_main._engine) as session:
        rows = session.scalars(
            select(Student)
            .where(Student.user_id == current_user.id)
            .order_by(Student.created_at.desc(), Student.id.desc())
        )
        return [
            {
                "id": row.id,
                "external_id": row.external_id,
                "created_at": _iso_utc(row.created_at),
            }
            for row in rows
        ]
