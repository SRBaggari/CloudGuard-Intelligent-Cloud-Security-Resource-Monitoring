from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.pagination import PageParams, paginate
from app.core.audit import audit
from app.core.database import get_db, utcnow
from app.core.deps import client_ip, get_current_user
from app.models import Notification, User
from app.schemas import Message, NotificationOut, NotificationPage, NotificationPreferences
from app.services.notifications import mark_read

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


def _unread(db: Session, user: User) -> int:
    return db.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user.id, Notification.is_read.is_(False))) or 0


@router.get("", response_model=NotificationPage)
def list_notifications(
    params: PageParams = Depends(),
    unread_only: bool = False,
    severity: str | None = Query(None, pattern="^(critical|high|medium|low|info)$"),
    category: str | None = Query(None, pattern="^(alert|incident|system)$"),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Notification history for the signed-in user (newest first)."""
    stmt = select(Notification).where(Notification.user_id == user.id).order_by(
        Notification.updated_at.desc(), Notification.id.desc())
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    if severity:
        stmt = stmt.where(Notification.severity == severity)
    if category:
        stmt = stmt.where(Notification.category == category)
    return {**paginate(db, stmt, params, NotificationOut), "unread": _unread(db, user)}


@router.get("/unread-count")
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"unread": _unread(db, user)}


@router.post("/{notification_id}/read", response_model=NotificationOut)
def read_one(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:  # users can only touch their own notifications
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    return mark_read(db, n)


@router.post("/read-all", response_model=Message)
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    res = db.execute(update(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))
                     .values(is_read=True, read_at=utcnow()))
    db.commit()
    return Message(detail=f"{res.rowcount or 0} notification(s) marked as read")


@router.get("/preferences", response_model=NotificationPreferences)
def get_preferences(user: User = Depends(get_current_user)):
    return NotificationPreferences(min_severity=user.notification_min_severity)


@router.put("/preferences", response_model=NotificationPreferences)
def set_preferences(body: NotificationPreferences, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    user.notification_min_severity = body.min_severity
    db.commit()
    audit(db, "notifications.preferences_updated", user.id, "user", user.id, body.model_dump(), client_ip(request))
    return body
