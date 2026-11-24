from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import ActivityLog


def audit(
    db: Session,
    action: str,
    user_id: int | None = None,
    resource_type: str = "",
    resource_id: str | int = "",
    details: dict[str, Any] | None = None,
    ip: str = "",
    commit: bool = True,
) -> ActivityLog:
    entry = ActivityLog(
        user_id=user_id, action=action, resource_type=resource_type,
        resource_id=str(resource_id), details=details or {}, ip_address=ip,
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry
