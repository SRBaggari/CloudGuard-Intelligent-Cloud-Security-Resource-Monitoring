"""Runtime settings stored in the database (editable by administrators)."""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import SystemSetting


def defaults() -> dict[str, dict[str, Any]]:
    s = get_settings()
    return {
        "monitoring": {
            "interval_seconds": s.metrics_interval_seconds,
            "container_poll_interval_seconds": s.container_poll_interval_seconds,
            "retention_days": s.metrics_retention_days,
            # Process names that should raise an alert if seen running (empty by default)
            "process_watchlist": [],
        },
        "ml": {
            "enabled": True,
            "contamination": 0.02,
            "min_training_samples": 200,
            "z_threshold": 4.0,
            "auto_alert": True,
        },
    }


def get_section(db: Session, key: str) -> dict[str, Any]:
    base = copy.deepcopy(defaults()[key])
    row = db.get(SystemSetting, key)
    if row:
        base.update(row.value or {})
    return base


def get_all(db: Session) -> dict[str, dict[str, Any]]:
    return {k: get_section(db, k) for k in defaults()}


def set_section(db: Session, key: str, value: dict[str, Any]) -> dict[str, Any]:
    if key not in defaults():
        raise KeyError(key)
    row = db.get(SystemSetting, key)
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))
    db.commit()
    return get_section(db, key)
