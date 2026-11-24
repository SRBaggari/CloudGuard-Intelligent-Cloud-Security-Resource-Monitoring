from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.api.pagination import PageParams, paginate
from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import client_ip, require_admin
from app.models import ActivityLog, LoginAttempt, RefreshToken, Role, User
from app.schemas import ActivityOut, AdminUserUpdate, LoginAttemptOut, Page, UserOut

router = APIRouter(tags=["Users & Audit"])


@router.get("/api/users", response_model=Page[UserOut])
def list_users(params: PageParams = Depends(), q: str | None = Query(None, max_length=64),
               _: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(User).order_by(User.id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.username).like(like), User.email.like(like)))
    return paginate(db, stmt, params, UserOut)


@router.patch("/api/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: AdminUserUpdate, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id and (body.role == "user" or body.is_active is False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot demote or disable your own account")
    if body.role:
        user.role_id = db.scalar(select(Role.id).where(Role.name == body.role))
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id).values(revoked=True))
    db.commit()
    db.refresh(user)
    audit(db, "admin.user_updated", admin.id, "user", user.id, body.model_dump(exclude_none=True), client_ip(request))
    return user


@router.post("/api/users/{user_id}/unlock", response_model=UserOut)
def unlock_user(user_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user.locked_until = None
    user.failed_login_count = 0
    db.commit()
    audit(db, "admin.user_unlocked", admin.id, "user", user.id, ip=client_ip(request))
    return user


@router.get("/api/activity", response_model=Page[ActivityOut])
def activity_logs(params: PageParams = Depends(), action: str | None = Query(None, max_length=64),
                  user_id: int | None = None, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(ActivityLog).order_by(ActivityLog.created_at.desc())
    if action:
        stmt = stmt.where(ActivityLog.action.like(f"{action}%"))
    if user_id:
        stmt = stmt.where(ActivityLog.user_id == user_id)
    return paginate(db, stmt, params, ActivityOut)


@router.get("/api/security/login-attempts", response_model=Page[LoginAttemptOut])
def login_attempts(params: PageParams = Depends(), success: bool | None = None, _: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    stmt = select(LoginAttempt).order_by(LoginAttempt.created_at.desc())
    if success is not None:
        stmt = stmt.where(LoginAttempt.success.is_(success))
    return paginate(db, stmt, params, LoginAttemptOut)
