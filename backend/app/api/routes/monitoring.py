from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import ensure_aware, get_db, utcnow
from app.core.deps import get_current_user, require_admin
from app.models import SystemMetric, User
from app.monitoring.collector import collector
from app.monitoring.service import collect_and_store, get_local_device, health_status
from app.schemas import DeviceOut, MetricOut

router = APIRouter(prefix="/api/monitoring", tags=["Monitoring"])


@router.get("/system")
def system(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Current real-time metrics (psutil) plus OS information and health."""
    dev = get_local_device(db)
    latest = db.scalar(select(SystemMetric).where(SystemMetric.device_id == dev.id)
                       .order_by(SystemMetric.timestamp.desc()).limit(1))
    if latest is None or (utcnow() - ensure_aware(latest.timestamp)).total_seconds() > 60:
        latest = collect_and_store(db)
    m = MetricOut.model_validate(latest)
    return {
        "device": DeviceOut.model_validate(dev),
        "metric": m,
        "info": collector.system_info(),
        "health": health_status(m.cpu_percent, m.memory_percent, m.disk_percent),
    }


@router.get("/history", response_model=list[MetricOut])
def history(
    minutes: int = Query(60, ge=1, le=60 * 24 * 30),
    start: datetime | None = None, end: datetime | None = None,
    max_points: int = Query(500, ge=10, le=5000),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Historical metrics, downsampled to at most `max_points` samples."""
    dev = get_local_device(db)
    end = end or utcnow()
    start = start or (end - timedelta(minutes=minutes))
    rows = db.scalars(select(SystemMetric).where(
        SystemMetric.device_id == dev.id, SystemMetric.timestamp >= start, SystemMetric.timestamp <= end,
    ).order_by(SystemMetric.timestamp)).all()
    step = max(1, len(rows) // max_points)
    return rows[::step]


@router.get("/network")
def network(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dev = get_local_device(db)
    latest = db.scalar(select(SystemMetric).where(SystemMetric.device_id == dev.id)
                       .order_by(SystemMetric.timestamp.desc()).limit(1))
    return {
        "send_rate": latest.net_send_rate if latest else 0.0,
        "recv_rate": latest.net_recv_rate if latest else 0.0,
        "bytes_sent": latest.net_bytes_sent if latest else 0,
        "bytes_recv": latest.net_bytes_recv if latest else 0,
        "interfaces": collector.network_interfaces(),
        # remote endpoint details are sensitive -> admins only
        "connections": collector.connection_summary() if user.is_admin else None,
    }


@router.get("/processes")
def processes(sort: str = Query("cpu", pattern="^(cpu|memory)$"), limit: int = Query(25, ge=1, le=200),
              _: User = Depends(require_admin)):
    """Top running processes (admin only: process lists can reveal sensitive information)."""
    return collector.processes(limit=limit, sort=sort)


@router.get("/devices", response_model=list[DeviceOut])
def devices(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import Device
    get_local_device(db)
    return db.scalars(select(Device).order_by(Device.id)).all()
