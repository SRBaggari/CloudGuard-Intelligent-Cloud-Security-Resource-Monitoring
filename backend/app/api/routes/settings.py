from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import client_ip, get_current_user, require_admin
from app.docker_integration.adapter import get_docker_adapter
from app.models import User
from app.schemas import SettingsOut, SettingsUpdate
from app.services import settings_service
from app.virtualization.vbox import get_vbox_adapter

router = APIRouter(prefix="/api/settings", tags=["Settings"])


@router.get("", response_model=SettingsOut)
def get_all(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return settings_service.get_all(db)


@router.put("", response_model=SettingsOut)
def update(body: SettingsUpdate, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.monitoring:
        v = body.monitoring.model_dump()
        v["process_watchlist"] = sorted({p.strip() for p in v["process_watchlist"] if p.strip()})[:200]
        settings_service.set_section(db, "monitoring", v)
    if body.ml:
        settings_service.set_section(db, "ml", body.ml.model_dump())
    audit(db, "settings.updated", admin.id, "settings", "", body.model_dump(exclude_none=True), client_ip(request))
    return settings_service.get_all(db)


@router.get("/integrations")
def integrations(_: User = Depends(get_current_user)):
    s = get_settings()
    return {
        "mode": s.integration_mode,
        "docker": get_docker_adapter().status() if s.docker_enabled else {"available": False, "message": "Disabled"},
        "virtualbox": get_vbox_adapter().status() if s.virtualbox_enabled else {"available": False, "message": "Disabled"},
        "database": "sqlite" if s.is_sqlite else "postgresql",
        "prometheus": s.prometheus_enabled,
    }


@router.get("/diagnostics")
def diagnostics(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    """System health diagnostics: database, migrations, background loops, collector, storage, integrations."""
    from app.services.diagnostics import run_diagnostics
    return run_diagnostics(db)
