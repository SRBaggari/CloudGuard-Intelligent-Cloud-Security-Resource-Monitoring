"""FastAPI dependencies: authentication and role-based authorization."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import TokenError, decode_token
from app.models import User

bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def user_from_token(db: Session, token: str) -> User:
    try:
        payload = decode_token(token, "access")
    except TokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e), headers={"WWW-Authenticate": "Bearer"}) from e
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
    return user


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return user_from_token(db, creds.credentials)


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required")
    return user


def can_manage(user: User, owner_id: int | None) -> bool:
    """Admins manage everything; regular users only resources assigned to them."""
    return user.is_admin or (owner_id is not None and owner_id == user.id)
