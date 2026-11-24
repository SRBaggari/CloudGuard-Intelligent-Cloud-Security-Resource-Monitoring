"""Idempotent seeding of reference data: roles, detection rules and the local device."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DetectionRule, Role
from app.monitoring.service import get_local_device
from app.security_engine.rules import DEFAULT_RULES


def seed(db: Session) -> None:
    for name, desc in (("admin", "Full access: configuration, actions, user management"),
                       ("user", "Read access to monitoring; may manage resources assigned to them")):
        if not db.scalar(select(Role).where(Role.name == name)):
            db.add(Role(name=name, description=desc))
    db.commit()

    existing = {r.key for r in db.scalars(select(DetectionRule)).all()}
    for r in DEFAULT_RULES:
        if r["key"] not in existing:
            db.add(DetectionRule(**r))
    db.commit()
    from app.compliance.service import seed_checks
    seed_checks(db)
    get_local_device(db)
