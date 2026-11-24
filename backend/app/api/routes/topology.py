from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import User
from app.services.topology import build_topology

router = APIRouter(prefix="/api/topology", tags=["Topology"])


@router.get("")
def topology(include_demo: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Graph of monitored infrastructure (nodes, edges, health, active alert counts).

    Regular users only see containers/VMs assigned to them. `include_demo=true` returns the
    separate, labelled demonstration environment instead of real infrastructure.
    """
    return build_topology(db, user, include_demo=include_demo)
