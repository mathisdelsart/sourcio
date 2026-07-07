"""User authentication: bcrypt password hashing and JWT access tokens.

This module is self-contained and additive. It provides:

* password hashing/verification with ``bcrypt`` (plaintext is never stored or
  logged);
* signed JWT access tokens (HS256) with an expiry, using the secret from
  ``Settings.jwt_secret``;
* the request/response models and the ``get_current_user`` dependency wired by
  the API into the ``/auth/*`` routes.

It does not change any existing endpoint or the ``X-API-Key`` guard: Bearer auth
and the optional API key are independent and coexist.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from core.config import get_settings
from db.models import User
from db.session import get_session

# JWT signing algorithm. Symmetric (HS256): the same secret signs and verifies.
_JWT_ALGORITHM = "HS256"

# bcrypt truncates the password at 72 bytes; reject longer inputs explicitly
# rather than silently ignoring the tail.
_MAX_PASSWORD_BYTES = 72

# A pragmatic minimum so empty/blank passwords are rejected at registration.
_MIN_PASSWORD_LENGTH = 8

# Username rules: a public pseudonym used both as the login id and the display
# name. Letters, digits and a few separators (``.``, ``_``, ``-``) so pseudos
# like "Math.D." work; no spaces, 3-32 characters.
_MIN_USERNAME_LENGTH = 3
_MAX_USERNAME_LENGTH = 32
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password`` as a UTF-8 string.

    The salt is generated per call, so identical passwords produce different
    hashes. The plaintext is never persisted or logged.
    """
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Return True when ``password`` matches the stored bcrypt ``hashed`` value.

    Any malformed stored hash is treated as a non-match rather than raising, so
    a corrupt row can never authenticate a request or crash the endpoint.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str) -> str:
    """Sign a JWT access token for ``subject`` (the user's id, as a string).

    The token carries a ``sub`` claim and an ``exp`` expiry derived from
    ``Settings.jwt_expire_minutes``. It is signed with ``Settings.jwt_secret``
    using HS256.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Validate ``token`` and return its ``sub`` claim (the user id).

    Raises 401 when the token is malformed, has a bad signature, is expired, or
    lacks a usable subject. The error detail stays generic on purpose.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return subject


def validate_registration(username: str, password: str) -> tuple[str, str]:
    """Validate and normalize a registration payload.

    Returns the trimmed username (original case preserved) and the original
    password on success. Raises 422 with a clear message when the username is the
    wrong length or contains disallowed characters, or when the password is too
    short or too long for bcrypt. Uniqueness is checked separately, at insert
    time, and is case-insensitive.
    """
    normalized = username.strip()
    if not _MIN_USERNAME_LENGTH <= len(normalized) <= _MAX_USERNAME_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Username must be between {_MIN_USERNAME_LENGTH} and "
                f"{_MAX_USERNAME_LENGTH} characters."
            ),
        )
    if not _USERNAME_RE.match(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username may only contain letters, digits, '.', '_' and '-'.",
        )
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Password must be at least {_MIN_PASSWORD_LENGTH} characters.",
        )
    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Password must not exceed {_MAX_PASSWORD_BYTES} bytes.",
        )
    return normalized, password


class RegisterRequest(BaseModel):
    """Credentials to create a new account.

    The username format is validated in ``validate_registration`` rather than via
    a pydantic validator so the rules live in one place.
    """

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginRequest(BaseModel):
    """Credentials to obtain an access token."""

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserOut(BaseModel):
    """Public view of a user. The password hash is never exposed."""

    id: int
    # The pseudonym: both the login identifier and the display name.
    username: str


class TokenResponse(BaseModel):
    """A bearer access token returned on successful login."""

    access_token: str
    token_type: str = "bearer"


def _bearer_token(authorization: str | None) -> str:
    """Extract the token from an ``Authorization: Bearer <jwt>`` header.

    Raises 401 when the header is missing or not a well-formed bearer scheme.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def _resolve_user_from_token(token: str) -> UserOut:
    """Decode a bearer ``token`` and load the matching user as a ``UserOut``.

    Raises 401 when the token is malformed/expired, carries a non-numeric
    subject, or points to a user that no longer exists. Shared by both the
    strict (``get_current_user``) and optional (``get_optional_user``)
    dependencies so they stay consistent.
    """
    subject = decode_access_token(token)
    try:
        user_id = int(subject)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return UserOut(id=user.id, username=user.username)


def get_current_user(authorization: str | None = Header(default=None)) -> UserOut:
    """FastAPI dependency that resolves the caller from a bearer JWT.

    Parses and validates the ``Authorization`` header, decodes the token, and
    loads the matching user. Returns a ``UserOut``. Raises 401 on any failure
    (missing/invalid/expired token, or a token whose user no longer exists).
    """
    token = _bearer_token(authorization)
    return _resolve_user_from_token(token)


def get_optional_user(authorization: str | None = Header(default=None)) -> UserOut | None:
    """FastAPI dependency that resolves the caller from a bearer JWT, if present.

    Unlike ``get_current_user``, authentication is optional: when no
    ``Authorization`` header is supplied the dependency returns ``None`` instead
    of raising, so a route can stay open to anonymous callers while still
    recognizing a logged-in user. A header that *is* present but malformed,
    invalid, or expired still raises 401, so a broken token never silently
    degrades to anonymous access.
    """
    if not authorization:
        return None
    token = _bearer_token(authorization)
    return _resolve_user_from_token(token)


def register_user(payload: RegisterRequest) -> UserOut:
    """Create a new account from a validated registration payload.

    Hashes the password with bcrypt and persists the user. Raises 409 when the
    username is already taken (compared case-insensitively so "Math" and "math"
    collide), enforcing first-come-first-served. The plaintext password is never
    stored.
    """
    username, password = validate_registration(payload.username, payload.password)
    with get_session() as session:
        existing = session.scalar(select(User).where(func.lower(User.username) == username.lower()))
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This username is already taken.",
            )
        user = User(username=username, hashed_password=hash_password(password))
        session.add(user)
        session.flush()
        return UserOut(id=user.id, username=user.username)


def login_user(payload: LoginRequest) -> TokenResponse:
    """Verify credentials and return a signed access token.

    Looks the account up by username (case-insensitively). Raises 401 on an
    unknown username or a wrong password, with the same generic message in both
    cases so the response does not reveal which usernames exist.
    """
    username = payload.username.strip()
    with get_session() as session:
        user = session.scalar(select(User).where(func.lower(User.username) == username.lower()))
        if user is None or not verify_password(payload.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return TokenResponse(access_token=create_access_token(str(user.id)))


# Re-exported so the API can declare the dependency without importing internals.
CurrentUser = Depends(get_current_user)
OptionalUser = Depends(get_optional_user)
