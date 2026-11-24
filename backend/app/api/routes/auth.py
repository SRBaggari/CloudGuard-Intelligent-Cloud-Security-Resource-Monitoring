from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.pagination import PageParams, paginate
from app.core.audit import audit
from app.core.config import get_settings
from app.core.database import ensure_aware, get_db, utcnow
from app.core.deps import client_ip, get_current_user
from app.core.security import (
    DUMMY_HASH, TokenError, create_access_token, create_refresh_token, decode_token, hash_password, verify_password,
)
from app.models import LoginAttempt, RefreshToken, Role, User
from app.schemas import (
    LoginAttemptOut, LoginRequest, Message, Page, PasswordChange, ProfileUpdate, RefreshRequest, RegisterRequest,
    TokenPair, UserOut,
)
from app.security_engine import engine
from app.services.alerts import record_event

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def _issue_tokens(db: Session, user: User) -> TokenPair:
    access = create_access_token(user.id, user.role_name)
    refresh, jti, exp = create_refresh_token(user.id)
    db.add(RefreshToken(jti=jti, user_id=user.id, expires_at=exp))
    db.commit()
    return TokenPair(access_token=access, refresh_token=refresh,
                     expires_in=get_settings().access_token_expire_minutes * 60,
                     user=UserOut.model_validate(user))


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Register a user. The very first account becomes the administrator; later accounts are regular users."""
    first = (db.scalar(select(func.count(User.id))) or 0) == 0
    role = db.scalar(select(Role).where(Role.name == ("admin" if first else "user")))
    if role is None:
        raise HTTPException(500, "Roles not initialised")
    email = body.email.lower()
    if db.scalar(select(User).where(or_(User.email == email, User.username == body.username))):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email or username already registered")
    user = User(email=email, username=body.username, full_name=body.full_name,
                hashed_password=hash_password(body.password), role_id=role.id)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email or username already registered")
    db.refresh(user)
    audit(db, "user.registered", user.id, "user", user.id, {"role": role.name}, client_ip(request))
    return user


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ident = body.username.strip().lower()
    ip = client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:255]
    user = db.scalar(select(User).where(or_(func.lower(User.username) == ident, User.email == ident)))

    def fail(reason: str, code=status.HTTP_401_UNAUTHORIZED, msg="Invalid username or password"):
        att = LoginAttempt(user_id=user.id if user else None, identifier=ident, ip_address=ip, user_agent=ua,
                           success=False, reason=reason)
        db.add(att)
        if user:
            user.failed_login_count += 1
        record_event(db, "login_failed", "authentication", f"Failed login for '{ident}' from {ip} ({reason})",
                     severity="low", resource=ident, details={"ip": ip, "reason": reason})
        db.commit()
        engine.evaluate_login(db, att, user)
        raise HTTPException(code, msg)

    if user is None:
        verify_password(body.password, DUMMY_HASH)  # equalise timing
        fail("unknown_user")
    if engine.is_locked(user):
        fail("locked", status.HTTP_423_LOCKED,
             "Account temporarily locked after repeated failed logins. Try again later.")
    if not verify_password(body.password, user.hashed_password):
        fail("bad_password")
    if not user.is_active:
        fail("inactive", status.HTTP_403_FORBIDDEN, "Account disabled")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    att = LoginAttempt(user_id=user.id, identifier=ident, ip_address=ip, user_agent=ua, success=True, reason="ok")
    db.add(att)
    db.commit()
    audit(db, "auth.login", user.id, "user", user.id, {"user_agent": ua}, ip)
    engine.evaluate_login(db, att, user)
    return _issue_tokens(db, user)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, "refresh")
    except TokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e))
    row = db.scalar(select(RefreshToken).where(RefreshToken.jti == payload["jti"]))
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown refresh token")
    if row.revoked:
        # token reuse => likely theft: revoke every session of this user
        db.execute(update(RefreshToken).where(RefreshToken.user_id == row.user_id).values(revoked=True))
        record_event(db, "refresh_token_reuse", "authentication",
                     f"Revoked refresh token reused for user id {row.user_id} from {client_ip(request)}",
                     severity="high", resource=str(row.user_id))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token revoked")
    if ensure_aware(row.expires_at) < utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token expired")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    row.revoked = True
    db.commit()
    return _issue_tokens(db, user)


@router.post("/logout", response_model=Message)
def logout(request: Request, body: RefreshRequest | None = None, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    """Revoke the given refresh token (or all of the user's refresh tokens if none supplied)."""
    q = update(RefreshToken).where(RefreshToken.user_id == user.id)
    if body and body.refresh_token:
        try:
            q = q.where(RefreshToken.jti == decode_token(body.refresh_token, "refresh")["jti"])
        except TokenError:
            pass
    db.execute(q.values(revoked=True))
    db.commit()
    audit(db, "auth.logout", user.id, "user", user.id, ip=client_ip(request))
    return Message(detail="Logged out")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: ProfileUpdate, request: Request, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    if body.email and body.email.lower() != user.email:
        if db.scalar(select(User).where(User.email == body.email.lower())):
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use")
        user.email = body.email.lower()
    if body.full_name is not None:
        user.full_name = body.full_name
    db.commit()
    audit(db, "user.profile_updated", user.id, "user", user.id, ip=client_ip(request))
    return user


@router.post("/change-password", response_model=Message)
def change_password(body: PasswordChange, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.hashed_password = hash_password(body.new_password)
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id).values(revoked=True))
    db.commit()
    audit(db, "user.password_changed", user.id, "user", user.id, ip=client_ip(request))
    return Message(detail="Password changed. Other sessions were signed out.")


@router.get("/login-history", response_model=Page[LoginAttemptOut])
def login_history(params: PageParams = Depends(), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(LoginAttempt).where(LoginAttempt.user_id == user.id).order_by(LoginAttempt.created_at.desc())
    return paginate(db, stmt, params, LoginAttemptOut)

