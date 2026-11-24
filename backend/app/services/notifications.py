"""In-app notifications.

Duplicate prevention: every notification has a `dedupe_key` that is unique per user (e.g.
``alert:42``). A repeated detection of the same alert does NOT create a new notification; only a
severity escalation re-surfaces the existing one (marked unread again).
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.models import Alert, Notification, User
from app.realtime.bus import manager
from app.schemas import NotificationOut

log = logging.getLogger("cloudguard.notifications")

RANK = {"info": -1, "low": 0, "medium": 1, "high": 2, "critical": 3}


def _push(n: Notification, event: str = "notification.created") -> None:
    manager.publish_user(n.user_id, {"type": event, "notification": NotificationOut.model_validate(n).model_dump(mode="json")})


def notify_user(
    db: Session, user_id: int, *, category: str, severity: str, title: str, message: str = "", link: str = "",
    dedupe_key: str, alert_id: int | None = None, resurface: bool = False,
) -> Notification | None:
    """Create a notification unless one with the same dedupe key exists for this user.

    With `resurface=True` an existing notification is updated and marked unread instead.
    """
    existing = db.scalar(select(Notification).where(Notification.user_id == user_id, Notification.dedupe_key == dedupe_key))
    if existing is not None:
        if not resurface:
            return None
        existing.severity, existing.title, existing.message = severity, title[:255], message
        existing.is_read, existing.read_at = False, None
        db.commit()
        _push(existing, "notification.updated")
        return existing
    n = Notification(user_id=user_id, category=category, severity=severity, title=title[:255], message=message,
                     link=link, dedupe_key=dedupe_key, alert_id=alert_id)
    db.add(n)
    try:
        db.commit()
    except IntegrityError:  # concurrent insert of the same key - keep the first one
        db.rollback()
        return None
    db.refresh(n)
    _push(n)
    return n


def notify_alert(db: Session, alert: Alert, *, is_new: bool, escalated: bool) -> int:
    """Notify every active user whose preference covers the alert severity. Returns notifications created/updated."""
    if not (is_new or escalated):
        return 0
    users = db.scalars(select(User).where(User.is_active.is_(True))).all()
    count = 0
    for u in users:
        if RANK[alert.severity] < RANK.get(u.notification_min_severity, 0):
            continue
        prefix = ("[DEMO] " if alert.is_demo else "") + ("Escalated: " if escalated and not is_new else "")
        n = notify_user(
            db, u.id, category="alert", severity=alert.severity, title=f"{prefix}{alert.title}",
            message=alert.description[:500], link=f"/alerts?id={alert.id}", dedupe_key=f"alert:{alert.id}",
            alert_id=alert.id, resurface=escalated,
        )
        count += n is not None
    return count


def mark_read(db: Session, n: Notification) -> Notification:
    if not n.is_read:
        n.is_read, n.read_at = True, utcnow()
        db.commit()
    return n
