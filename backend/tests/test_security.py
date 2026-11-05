import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)

SETTINGS = get_settings()
SECRET = SETTINGS.jwt_secret.get_secret_value()


def _token(**overrides: object) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": "x",
        "type": "access",
        **overrides,
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")


def test_verifyPassword_correctPassword_returnsTrue() -> None:
    assert verify_password("correct horse battery", hash_password("correct horse battery"))


def test_verifyPassword_wrongPassword_returnsFalse() -> None:
    assert not verify_password("nope-nope-nope", hash_password("correct horse battery"))


def test_verifyPassword_unknownUser_returnsFalse() -> None:
    assert not verify_password("anything-at-all", None)


def test_decodeAccessToken_validToken_returnsUserId() -> None:
    user_id = uuid.uuid4()
    assert decode_access_token(create_access_token(user_id, SETTINGS), SETTINGS) == user_id


def test_decodeAccessToken_expiredToken_raisesUnauthorized() -> None:
    expired = _token(exp=datetime.now(UTC) - timedelta(minutes=1))
    with pytest.raises(UnauthorizedError):
        decode_access_token(expired, SETTINGS)


def test_decodeAccessToken_wrongType_raisesUnauthorized() -> None:
    with pytest.raises(UnauthorizedError):
        decode_access_token(_token(type="refresh"), SETTINGS)


def test_decodeAccessToken_otherAlgorithm_raisesUnauthorized() -> None:
    other = jwt.encode({"sub": str(uuid.uuid4()), "exp": 9999999999}, SECRET, algorithm="HS512")
    with pytest.raises(UnauthorizedError):
        decode_access_token(other, SETTINGS)


def test_decodeAccessToken_unsignedToken_raisesUnauthorized() -> None:
    unsigned = jwt.encode({"sub": str(uuid.uuid4())}, key=None, algorithm="none")
    with pytest.raises(UnauthorizedError):
        decode_access_token(unsigned, SETTINGS)


def test_decodeAccessToken_missingClaims_raisesUnauthorized() -> None:
    bare = jwt.encode({"sub": str(uuid.uuid4())}, SECRET, algorithm="HS256")
    with pytest.raises(UnauthorizedError):
        decode_access_token(bare, SETTINGS)


def test_hashRefreshToken_sameInput_isStableAndNotRaw() -> None:
    raw = new_refresh_token()
    assert hash_refresh_token(raw) == hash_refresh_token(raw) != raw
