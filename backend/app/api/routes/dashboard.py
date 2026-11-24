from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db, utcnow
from app.core.deps import get_current_user
from app.docker_integration.adapter import get_docker_adapter
from app.ml_engine.detector import detector
from app.models import ActivityLog, Alert, AnomalyRecord, Container, Device, SecurityEvent, SystemMetric, User, VirtualMachine
from app.monitoring.service import get_local_device, health_status
from app.schemas import AlertOut, MetricOut
from app.virtualization.vbox import get_vbox_adapter

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/summary")
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dev = get_local_device(db)
    latest = db.scalar(select(SystemMetric).where(SystemMetric.device_id == dev.id)
                       .order_by(SystemMetric.timestamp.desc()).limit(1))
    docker = get_docker_adapter().status()
    vbox = get_vbox_adapter().status()

    cstmt = select(Container).where(Container.status != "removed")
    vstmt = select(VirtualMachine)
    if not user.is_admin:
        cstmt = cstmt.where(Container.owner_id == user.id)
        vstmt = vstmt.where(VirtualMachine.owner_id == user.id)
    containers = db.scalars(cstmt).all() if docker.get("available") else []
    vms = db.scalars(vstmt).all() if vbox.get("available") else []

    since = utcnow() - timedelta(hours=24)
    active = select(Alert).where(Alert.status != "resolved")
    sev_counts = dict(db.execute(select(Alert.severity, func.count(Alert.id)).where(Alert.status != "resolved")
                                 .group_by(Alert.severity)).all())
    cat_counts = dict(db.execute(select(Alert.category, func.count(Alert.id)).where(Alert.created_at >= since)
                                 .group_by(Alert.category)).all())
    recent_alerts = db.scalars(active.order_by(Alert.last_seen_at.desc()).limit(6)).all()
    events_24h = db.scalar(select(func.count(SecurityEvent.id)).where(SecurityEvent.created_at >= since)) or 0
    anomalies_24h = db.scalar(select(func.count(AnomalyRecord.id)).where(
        AnomalyRecord.timestamp >= since, AnomalyRecord.is_anomaly.is_(True))) or 0
    failed_logins_24h = db.scalar(select(func.count(SecurityEvent.id)).where(
        SecurityEvent.created_at >= since, SecurityEvent.event_type == "login_failed")) or 0

    activity = []
    if user.is_admin:
        activity = [{"id": a.id, "action": a.action, "resource_type": a.resource_type, "resource_id": a.resource_id,
                     "user_id": a.user_id, "created_at": a.created_at}
                    for a in db.scalars(select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(8))]

    m = MetricOut.model_validate(latest) if latest else None
    health = health_status(m.cpu_percent, m.memory_percent, m.disk_percent) if m else {"status": "unknown", "score": None, "issues": ["No metrics collected yet"]}
    if sev_counts.get("critical"):
        health["status"] = "critical"
        health["issues"].append(f"{sev_counts['critical']} critical alert(s) open")
    elif sev_counts.get("high") and health["status"] == "healthy":
        health["status"] = "degraded"
        health["issues"].append(f"{sev_counts['high']} high-severity alert(s) open")

    return {
        "devices": {"total": (db.scalar(select(func.count(Device.id))) or 0) + len(vms) + len(containers),
                    "hosts": db.scalar(select(func.count(Device.id))) or 0},
        "vms": {"available": vbox.get("available", False), "mode": vbox.get("mode"), "message": vbox.get("message"),
                "total": len(vms), "running": sum(v.state == "running" for v in vms)},
        "containers": {"available": docker.get("available", False), "mode": docker.get("mode"),
                       "message": docker.get("message"), "total": len(containers),
                       "running": sum(c.status == "running" for c in containers),
                       "unhealthy": sum(c.health == "unhealthy" for c in containers)},
        "metric": m,
        "health": health,
        "alerts": {"active": sum(sev_counts.values()), "by_severity": {s: sev_counts.get(s, 0) for s in
                                                                       ("critical", "high", "medium", "low")},
                   "recent": [AlertOut.model_validate(a) for a in recent_alerts]},
        "threats": {"events_24h": events_24h, "failed_logins_24h": failed_logins_24h, "anomalies_24h": anomalies_24h,
                    "alerts_by_category_24h": cat_counts, "ml_model_ready": detector.info() is not None},
        "activity": activity,
    }


@router.get("/health")
def health(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dev = get_local_device(db)
    latest = db.scalar(select(SystemMetric).where(SystemMetric.device_id == dev.id)
                       .order_by(SystemMetric.timestamp.desc()).limit(1))
    components = {
        "database": {"status": "up"},
        "metrics_collector": {"status": "up" if latest else "waiting",
                              "last_sample": latest.timestamp if latest else None},
        "docker": get_docker_adapter().status(),
        "virtualbox": get_vbox_adapter().status(),
        "ml_engine": {"status": "trained" if detector.info() else "not_trained"},
    }
    overall = health_status(latest.cpu_percent, latest.memory_percent, latest.disk_percent) if latest else {"status": "unknown"}
    return {"status": overall["status"], "host": overall, "components": components}
