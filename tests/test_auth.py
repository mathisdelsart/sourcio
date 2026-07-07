"""Tests for the user authentication system (register / login / me).

Auth is fully local: passwords are hashed with bcrypt and tokens are signed
JWTs. No LLM, vector store, or network call is involved. The API is bound to an
in-memory SQLite database so the routes run in isolation. The module is skipped
when the optional ``api`` extra (FastAPI) is not installed, so CI without extras
collects cleanly.
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("jwt")
pytest.importorskip("bcrypt")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import api.main as api_main  # noqa: E402
from api import auth as auth_mod  # noqa: E402
from api.main import app  # noqa: E402


@pytest.fixture
def client():
    """Bind the API to a fresh in-memory SQLite DB and yield a test client."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    api_main.configure_engine(engine)
    with TestClient(app) as test_client:
        yield test_client
    api_main._engine = None


def _register(client, username="tester", password="hunter2pass"):
    return client.post("/auth/register", json={"username": username, "password": password})


# --- password hashing --------------------------------------------------------


def test_password_is_hashed_not_plaintext():
    password = "hunter2pass"
    hashed = auth_mod.hash_password(password)
    assert hashed != password
    assert hashed.startswith("$2")  # bcrypt hash prefix
    assert auth_mod.verify_password(password, hashed) is True
    assert auth_mod.verify_password("wrong", hashed) is False


def test_hashing_is_salted():
    a = auth_mod.hash_password("samepassword")
    b = auth_mod.hash_password("samepassword")
    assert a != b


def test_verify_rejects_malformed_hash():
    assert auth_mod.verify_password("x", "not-a-bcrypt-hash") is False


# --- registration ------------------------------------------------------------


def test_register_creates_user_and_hashes_password(client):
    response = _register(client, "alice", "supersecret")
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"
    assert isinstance(body["id"], int)
    # The hash, not the plaintext, is stored.
    assert "password" not in body

    from db.models import User
    from db.session import get_session

    with get_session(api_main._engine) as session:
        user = session.scalar(select(User).where(User.username == "alice"))
        assert user is not None
        assert user.hashed_password != "supersecret"
        assert "supersecret" not in user.hashed_password
        assert auth_mod.verify_password("supersecret", user.hashed_password)


def test_register_preserves_username_case_and_trims(client):
    # The stored username keeps its original case but is trimmed of surrounding
    # whitespace; it is echoed verbatim by /auth/me.
    response = _register(client, "  Math.D-1  ", "supersecret")
    assert response.status_code == 201
    assert response.json()["username"] == "Math.D-1"

    token = client.post(
        "/auth/login", json={"username": "Math.D-1", "password": "supersecret"}
    ).json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["username"] == "Math.D-1"


def test_register_duplicate_username_is_409(client):
    assert _register(client, "dup", "supersecret").status_code == 201
    # Same username, different case/whitespace, must still collide (case-insensitive).
    second = _register(client, "DUP ", "anothersecret")
    assert second.status_code == 409
    assert second.json()["detail"] == "This username is already taken."


@pytest.mark.parametrize(
    "body",
    [
        {"password": "supersecret"},  # missing username
        {"username": "alice"},  # missing password
        {"username": "ab", "password": "supersecret"},  # too short
        {"username": "x" * 33, "password": "supersecret"},  # too long
        {"username": "has space", "password": "supersecret"},  # space not allowed
        {"username": "bad@name", "password": "supersecret"},  # disallowed char
        {"username": "gooduser", "password": "short"},  # password too short
    ],
)
def test_register_bad_input_is_4xx(client, body):
    response = client.post("/auth/register", json=body)
    assert response.status_code in (400, 422)


# --- login -------------------------------------------------------------------


def test_login_success_returns_bearer_token(client):
    _register(client, "carol", "supersecret")
    response = client.post("/auth/login", json={"username": "carol", "password": "supersecret"})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]


def test_login_is_case_insensitive_on_username(client):
    _register(client, "Dave", "supersecret")
    response = client.post("/auth/login", json={"username": "DAVE", "password": "supersecret"})
    assert response.status_code == 200


def test_login_wrong_password_is_401(client):
    _register(client, "erin", "supersecret")
    response = client.post("/auth/login", json={"username": "erin", "password": "wrongpass1"})
    assert response.status_code == 401


def test_login_unknown_username_is_401(client):
    response = client.post("/auth/login", json={"username": "nobody", "password": "supersecret"})
    assert response.status_code == 401


# --- /auth/me ----------------------------------------------------------------


def _token(client, username="frank", password="supersecret"):
    _register(client, username, password)
    return client.post("/auth/login", json={"username": username, "password": password}).json()[
        "access_token"
    ]


def test_me_with_valid_token_returns_user(client):
    token = _token(client, "frank")
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["username"] == "frank"


def test_me_missing_token_is_401(client):
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_me_invalid_token_is_401(client):
    response = client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401


def test_me_wrong_scheme_is_401(client):
    token = _token(client, "grace")
    response = client.get("/auth/me", headers={"Authorization": token})  # no "Bearer "
    assert response.status_code == 401


def test_me_expired_token_is_401(client, monkeypatch):
    from datetime import UTC, datetime, timedelta

    import jwt

    from core.config import get_settings

    # Forge a token that expired one hour ago, signed with the real secret.
    _register(client, "heidi", "supersecret")
    secret = get_settings().jwt_secret
    expired = jwt.encode(
        {
            "sub": "1",
            "exp": datetime.now(UTC) - timedelta(hours=1),
        },
        secret,
        algorithm="HS256",
    )
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_me_token_for_deleted_user_is_401(client):
    token = _token(client, "ivan")
    # Remove the user, then the previously valid token must no longer resolve.
    from db.models import User
    from db.session import get_session

    with get_session(api_main._engine) as session:
        user = session.scalar(select(User).where(User.username == "ivan"))
        session.delete(user)

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


# --- additive / non-breaking -------------------------------------------------


def test_existing_endpoints_do_not_require_bearer(client, monkeypatch):
    # The tutor endpoints stay open to the bearer guard: no Authorization header
    # is needed (only the optional X-API-Key guard applies, here disabled).
    monkeypatch.setattr(
        api_main,
        "answer",
        lambda question, *, k=5, course=None, chapter=None, owner=None, language=None: {
            "answer": "ok",
            "refused": False,
            "sources": [],
            "raw": "ok",
        },
    )
    response = client.post("/ask", json={"student_id": "s1", "question": "q"})
    assert response.status_code == 200


def test_jwt_round_trip_subject():
    token = auth_mod.create_access_token("42")
    assert auth_mod.decode_access_token(token) == "42"


# --- startup JWT secret guard (H1) -------------------------------------------
# When auth is required, the app must refuse to boot with the forgeable default
# secret (or any too-short secret). With auth off, the local default is fine.

from core.config import Settings  # noqa: E402


def test_validate_jwt_secret_rejects_default_when_auth_required():
    settings = Settings(require_auth=True, jwt_secret="dev-insecure-change-me")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        api_main._validate_jwt_secret(settings)


def test_validate_jwt_secret_rejects_short_secret_when_auth_required():
    settings = Settings(require_auth=True, jwt_secret="tooshort")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        api_main._validate_jwt_secret(settings)


def test_validate_jwt_secret_accepts_strong_secret_when_auth_required():
    settings = Settings(require_auth=True, jwt_secret="a-strong-random-secret-value")
    # Must not raise.
    api_main._validate_jwt_secret(settings)


def test_validate_jwt_secret_allows_default_when_auth_off():
    # Local dev (require_auth off) keeps the placeholder secret without blocking.
    settings = Settings(require_auth=False, jwt_secret="dev-insecure-change-me")
    api_main._validate_jwt_secret(settings)
