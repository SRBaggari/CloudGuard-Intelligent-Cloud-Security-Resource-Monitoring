"""Password hashing (Argon2id) and JWT token handling."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# Used to equalise timing when the user does not exist
DUMMY_HASH = _hasher.hash("cloudguard-timing-equaliser")


class TokenError(Exception):
    pass


def _encode(payload: dict[str, Any]) -> str:
    s = get_settings()
    return jwt.encode(payload, s.jwt_secret_key, algorithm=s.jwt_algorithm)


def create_access_token(user_id: int, role: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    return _encode({
        "sub": str(user_id), "role": role, "type": "access",
        "iat": now, "exp": now + timedelta(minutes=s.access_token_expire_minutes),
        "jti": uuid.uuid4().hex,
    })


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    s = get_settings()
    now = datetime.now(timezone.utc)
    jti = uuid.uuid4().hex
    exp = now + timedelta(days=s.refresh_token_expire_days)
    token = _encode({"sub": str(user_id), "type": "refresh", "iat": now, "exp": exp, "jti": jti})
    return token, jti, exp


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret_key, algorithms=[s.jwt_algorithm])
    except jwt.ExpiredSignatureError as e:
        raise TokenError("Token expired") from e
    except jwt.PyJWTError as e:
        raise TokenError("Invalid token") from e
    if payload.get("type") != expected_type:
        raise TokenError("Wrong token type")
    return payload
