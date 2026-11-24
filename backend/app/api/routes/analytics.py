from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import ensure_aware, get_db, utcnow
from app.core.deps import client_ip, get_current_user, require_admin
from app.ml_engine.detector import InsufficientData, detector
from app.models import Alert, AnomalyRecord, SecurityEvent, SystemMetric, User
from app.monitoring.service import get_local_device
from app.schemas import AnomalyOut
from app.services import settings_service

router = APIRouter(prefix="/api/analytics", tags=["Analytics & ML"])


@router.get("/overview")
def overview(days: int = Query(7, ge=1, le=90), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=days)
    dev = get_local_device(db)
    metrics = db.scalars(select(SystemMetric).where(SystemMetric.device_id == dev.id, SystemMetric.timestamp >= since)
                         .order_by(SystemMetric.timestamp)).all()
    bucket_minutes = 60 if days > 1 else 10
    buckets: dict = defaultdict(list)
    for m in metrics:
        ts = ensure_aware(m.timestamp)
        key = ts.replace(minute=(ts.minute // bucket_minutes) * bucket_minutes if bucket_minutes < 60 else 0,
                         second=0, microsecond=0)
        buckets[key].append(m)
    timeline = [{
        "time": k.isoformat(),
        "cpu_avg": round(sum(x.cpu_percent for x in v) / len(v), 2),
        "cpu_max": round(max(x.cpu_percent for x in v), 2),
        "memory_avg": round(sum(x.memory_percent for x in v) / len(v), 2),
        "disk_avg": round(sum(x.disk_percent for x in v) / len(v), 2),
        "net_send_avg": round(sum(x.net_send_rate for x in v) / len(v), 1),
        "net_recv_avg": round(sum(x.net_recv_rate for x in v) / len(v), 1),
    } for k, v in sorted(buckets.items())]

    alerts = db.scalars(select(Alert).where(Alert.created_at >= since, Alert.is_demo.is_(False))).all()
    per_day: dict = defaultdict(lambda: {"critical": 0, "high": 0, "medium": 0, "low": 0})
    by_cat: dict = defaultdict(int)
    by_res: dict = defaultdict(int)
    for a in alerts:
        per_day[ensure_aware(a.created_at).date().isoformat()][a.severity] += 1
        by_cat[a.category] += 1
        by_res[a.resource_name] += a.occurrences
    resolved = [a for a in alerts if a.resolved_at]
    mttr = (sum((ensure_aware(a.resolved_at) - ensure_aware(a.created_at)).total_seconds() for a in resolved)
            / len(resolved) / 60) if resolved else None
    events = dict(db.execute(select(SecurityEvent.category, func.count(SecurityEvent.id))
                             .where(SecurityEvent.created_at >= since, SecurityEvent.is_demo.is_(False)).group_by(SecurityEvent.category)).all())
    return {
        "days": days, "samples": len(metrics), "bucket_minutes": bucket_minutes, "timeline": timeline,
        "alerts_per_day": [{"date": d, **v} for d, v in sorted(per_day.items())],
        "alerts_by_category": dict(by_cat),
        "top_resources": [{"resource": r, "count": c} for r, c in sorted(by_res.items(), key=lambda kv: -kv[1])[:8]],
        "events_by_category": events,
        "mean_time_to_resolve_minutes": round(mttr, 1) if mttr is not None else None,
        "total_alerts": len(alerts),
    }


@router.get("/anomalies")
def anomalies(points: int = Query(300, ge=20, le=3000), _: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Model status, scored recent metrics (normal vs abnormal) and stored anomaly records."""
    ml = settings_service.get_section(db, "ml")
    dev = get_local_device(db)
    available = db.scalar(select(func.count(SystemMetric.id)).where(SystemMetric.device_id == dev.id)) or 0
    model = detector.info()
    base = {"settings": ml, "samples_available": available, "samples_required": ml["min_training_samples"],
            "model": model}
    if model is None:
        need = max(0, ml["min_training_samples"] - available)
        return {**base, "status": "insufficient_data" if need else "not_trained",
                "message": (f"More monitoring data is needed: {available} of {ml['min_training_samples']} samples "
                            f"collected. Keep CloudGuard running to gather a baseline of normal behaviour."
                            if need else "Enough data collected. Train the model to start anomaly detection."),
                "series": [], "records": []}
    recent = db.scalars(select(SystemMetric).where(SystemMetric.device_id == dev.id)
                        .order_by(SystemMetric.timestamp.desc()).limit(points)).all()[::-1]
    scored = detector.score(recent)
    series = [{"timestamp": s["timestamp"], "score": round(s["score"], 4), "is_anomaly": s["is_anomaly"],
               "cpu_percent": s["features"]["cpu_percent"], "memory_percent": s["features"]["memory_percent"],
               "net_recv_rate": s["features"]["net_recv_rate"], "explanation": s.get("explanation"),
               "detected_by": s.get("detected_by", "")} for s in scored]
    records = db.scalars(select(AnomalyRecord).where(AnomalyRecord.is_anomaly.is_(True))
                         .order_by(AnomalyRecord.timestamp.desc()).limit(50)).all()
    return {**base, "status": "ready", "message": "Model trained and scoring live metrics.",
            "series": series, "anomaly_rate": (sum(s["is_anomaly"] for s in scored) / len(scored)) if scored else 0,
            "records": [AnomalyOut.model_validate(r) for r in records]}


@router.post("/anomalies/train")
def train(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    ml = settings_service.get_section(db, "ml")
    dev = get_local_device(db)
    try:
        info = detector.train(db, dev.id, float(ml["contamination"]), int(ml["min_training_samples"]),
                              float(ml.get("z_threshold", 4.0)))
    except InsufficientData as e:
        raise HTTPException(status.HTTP_409_CONFLICT, {"message": str(e), "have": e.have, "need": e.need})
    audit(db, "ml.model_trained", admin.id, "model", info["version"], {"samples": info["n_samples"]},
          client_ip(request))
    return info


@router.delete("/anomalies/model", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    detector.reset()
    audit(db, "ml.model_deleted", admin.id, "model", "", ip=client_ip(request))
