from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import User
from app.services.capacity import build_capacity_report

router = APIRouter(prefix="/api/capacity", tags=["Capacity Planning"])


@router.get("")
def capacity(lookback_days: int = Query(7, ge=1, le=90), horizon_days: int = Query(30, ge=1, le=180),
             demo: bool = Query(False, description="Analyse the labelled demonstration node instead of this host"),
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Measured utilisation, linear trend and threshold estimates for CPU, memory, disk and network.

    Every projected value is tagged `kind: "estimate"`; observed values are `kind: "measured"`.
    Returns `status: "insufficient_data"` with an explanation when history is too short.
    """
    return build_capacity_report(db, user, lookback_days, horizon_days, demo)
