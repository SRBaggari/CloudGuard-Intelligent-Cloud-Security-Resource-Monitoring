from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.api.pagination import PageParams, paginate
from app.core.audit import audit
from app.core.database import ensure_aware, get_db
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


def _activity_query(action: str | None, user_id: int | None, start: datetime | None, end: datetime | None,
                    q: str | None):
    stmt = select(ActivityLog).order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
    if action:
        stmt = stmt.where(ActivityLog.action.like(f"{action}%"))
    if user_id:
        stmt = stmt.where(ActivityLog.user_id == user_id)
    if start:
        stmt = stmt.where(ActivityLog.created_at >= start)
    if end:
        stmt = stmt.where(ActivityLog.created_at <= end)
    if q:
        stmt = stmt.where(or_(ActivityLog.resource_id.ilike(f"%{q}%"), ActivityLog.ip_address.ilike(f"%{q}%"),
                              ActivityLog.resource_type.ilike(f"%{q}%")))
    return stmt


@router.get("/api/activity", response_model=Page[ActivityOut])
def activity_logs(params: PageParams = Depends(), action: str | None = Query(None, max_length=64),
                  user_id: int | None = None, start: datetime | None = None, end: datetime | None = None,
                  q: str | None = Query(None, max_length=128),
                  _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Security audit log of user activity and administrative actions."""
    return paginate(db, _activity_query(action, user_id, start, end, q), params, ActivityOut)


@router.get("/api/activity/export")
def export_activity(request: Request, action: str | None = Query(None, max_length=64), user_id: int | None = None,
                    start: datetime | None = None, end: datetime | None = None, q: str | None = Query(None, max_length=128),
                    admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Download the (filtered) audit log as CSV (max 50,000 rows)."""
    rows = db.scalars(_activity_query(action, user_id, start, end, q).limit(50_000)).unique().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "timestamp_utc", "user_id", "username", "action", "resource_type", "resource_id", "ip_address", "details"])
    for r in rows:
        w.writerow([r.id, ensure_aware(r.created_at).isoformat(), r.user_id or "", r.username or "system", r.action,
                    r.resource_type, r.resource_id, r.ip_address, json.dumps(r.details, default=str)])
    audit(db, "audit.exported", admin.id, "activity_log", "", {"rows": len(rows)}, client_ip(request))
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="cloudguard-audit-log.csv"'})


@router.get("/api/security/login-attempts", response_model=Page[LoginAttemptOut])
def login_attempts(params: PageParams = Depends(), success: bool | None = None, _: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    stmt = select(LoginAttempt).order_by(LoginAttempt.created_at.desc())
    if success is not None:
        stmt = stmt.where(LoginAttempt.success.is_(success))
    return paginate(db, stmt, params, LoginAttemptOut)
