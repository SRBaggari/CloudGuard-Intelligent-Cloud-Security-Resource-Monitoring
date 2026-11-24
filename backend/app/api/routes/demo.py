from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import client_ip, get_current_user, require_admin
from app.models import User
from app.services import demo

router = APIRouter(prefix="/api/demo", tags=["Demonstration Mode"])


@router.get("")
def demo_status(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """State of the labelled demonstration environment and the available scenarios."""
    return {
        **demo.status(db),
        "scenarios": [{"key": k, "title": v["title"], "description": v["description"], "uses_real_rule_engine": v["engine"]}
                      for k, v in demo.SCENARIOS.items()],
    }


@router.post("/seed")
def seed(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Create the separate demonstration environment (idempotent)."""
    result = demo.seed_demo(db)
    audit(db, "demo.seeded", admin.id, "demo", "", {}, client_ip(request))
    return result


@router.post("/reset")
def reset(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Delete all demonstration data. Real infrastructure data is not affected."""
    result = demo.reset_demo(db)
    audit(db, "demo.reset", admin.id, "demo", "", {}, client_ip(request))
    return result


@router.post("/scenarios/{name}")
def run_scenario(name: str, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if name not in demo.SCENARIOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown scenario")
    try:
        result = demo.run_scenario(db, name, admin)
    except demo.DemoNotReady as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    audit(db, "demo.scenario", admin.id, "demo", name, {k: v for k, v in result.items() if k != "alerts"}, client_ip(request))
    return result
