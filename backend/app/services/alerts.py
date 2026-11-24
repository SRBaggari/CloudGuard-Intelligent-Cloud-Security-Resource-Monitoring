"""Security event recording and alert creation with de-duplication + realtime push."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.models import Alert, DetectionRule, SecurityEvent
from app.realtime.bus import manager
from app.schemas import AlertOut

log = logging.getLogger("cloudguard.alerts")

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def get_rule(db: Session, key: str) -> DetectionRule | None:
    return db.scalar(select(DetectionRule).where(DetectionRule.key == key))


def record_event(
    db: Session, event_type: str, category: str, message: str, *, severity: str = "low",
    resource: str = "", details: dict[str, Any] | None = None, rule: DetectionRule | None = None,
    source: str = "cloudguard",
) -> SecurityEvent:
    ev = SecurityEvent(
        event_type=event_type, category=category, severity=severity, message=message,
        resource=resource, details=details or {}, rule_id=rule.id if rule else None, source=source,
    )
    db.add(ev)
    db.flush()
    return ev


def raise_alert(
    db: Session, rule: DetectionRule, *, title: str, description: str, resource_type: str,
    resource_name: str, details: dict[str, Any] | None = None, severity: str | None = None,
    dedupe_key: str | None = None, event: SecurityEvent | None = None,
) -> Alert:
    """Create an alert, or bump an existing open/acknowledged alert with the same fingerprint."""
    severity = severity or rule.severity
    fingerprint = f"{rule.key}:{resource_type}:{dedupe_key or resource_name}"[:255]
    existing = db.scalar(
        select(Alert).where(Alert.fingerprint == fingerprint, Alert.status != "resolved").order_by(Alert.id.desc())
    )
    now = utcnow()
    escalated = False
    if existing:
        existing.occurrences += 1
        existing.last_seen_at = now
        existing.title = title  # reflect the latest detection
        existing.description = description
        if SEVERITY_ORDER[severity] > SEVERITY_ORDER[existing.severity]:
            existing.severity = severity
            escalated = True
        if details:
            existing.details = {**(existing.details or {}), **details}
        alert, is_new = existing, False
    else:
        alert = Alert(
            title=title, description=description, severity=severity, category=rule.category,
            resource_type=resource_type, resource_name=resource_name, fingerprint=fingerprint,
            recommended_action=rule.recommended_response, details=details or {}, rule_id=rule.id,
            event_id=event.id if event else None, last_seen_at=now,
        )
        db.add(alert)
        is_new = True
    db.commit()
    db.refresh(alert)
    manager.publish("alerts", {
        "type": "alert.created" if is_new else "alert.updated",
        "alert": AlertOut.model_validate(alert).model_dump(mode="json"),
    })
    if is_new:
        log.info("ALERT [%s] %s (%s)", severity.upper(), title, resource_name)
    try:
        from app.services.notifications import notify_alert
        notify_alert(db, alert, is_new=is_new, escalated=escalated)
    except Exception:  # notification failures must never block detection
        log.exception("failed to create notifications for alert %s", alert.id)
        db.rollback()
    return alert


def detect(
    db: Session, rule_key: str, *, title: str, description: str, resource_type: str, resource_name: str,
    event_type: str | None = None, details: dict[str, Any] | None = None, severity: str | None = None,
    dedupe_key: str | None = None,
) -> Alert | None:
    """Convenience: record a security event and raise an alert if the rule is enabled."""
    rule = get_rule(db, rule_key)
    if rule is None or not rule.enabled:
        return None
    ev = record_event(
        db, event_type or rule_key, rule.category, description, severity=severity or rule.severity,
        resource=resource_name, details=details, rule=rule,
    )
    return raise_alert(
        db, rule, title=title, description=description, resource_type=resource_type,
        resource_name=resource_name, details=details, severity=severity, dedupe_key=dedupe_key, event=ev,
    )


def count_recent_events(db: Session, event_type: str, resource: str, minutes: int) -> int:
    since = utcnow() - timedelta(minutes=minutes)
    return len(db.scalars(
        select(SecurityEvent.id).where(
            SecurityEvent.event_type == event_type, SecurityEvent.resource == resource,
            SecurityEvent.created_at >= since,
        )
    ).all())
