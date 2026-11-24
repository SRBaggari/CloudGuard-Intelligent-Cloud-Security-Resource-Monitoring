"""Resource capacity planning from historical host metrics.

Method (deliberately simple and explainable):
1. Measured history is aggregated into buckets (10 min for spans < 12 h, otherwise 1 h).
2. An ordinary least-squares line is fitted to the bucket averages over time.
3. The line is extrapolated over the planning horizon; the band is ±1.96 × residual standard
   deviation (an approximate 95% interval assuming the trend continues).
4. Days until the configured warning / critical thresholds are derived from the fitted line.

All projected values are labelled ``estimate``; observed values are labelled ``measured``. With too
little history the API returns ``insufficient_data`` instead of a forecast.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import ensure_aware, utcnow
from app.models import Container, SystemMetric, User
from app.monitoring.service import get_local_device
from app.services.alerts import get_rule

MB = 1024 * 1024
MIN_BUCKETS = 12
MIN_SPAN_HOURS = 3

METRICS = [
    ("cpu_percent", "CPU", "percent", "cpu_threshold"),
    ("memory_percent", "Memory", "percent", "memory_threshold"),
    ("disk_percent", "Disk", "percent", "disk_threshold"),
    ("net_recv_rate", "Download throughput", "bytes_per_second", "network_traffic"),
    ("net_send_rate", "Upload throughput", "bytes_per_second", "network_traffic"),
]


def _thresholds(db: Session, rule_key: str, unit: str) -> tuple[float | None, float | None]:
    rule = get_rule(db, rule_key)
    if rule is None:
        return None, None
    p = rule.params or {}
    if unit == "percent":
        return float(p.get("warning", 85)), float(p.get("critical", 95))
    limit = float(p.get("mbps", 50)) * MB
    return limit, None


def _bucket(rows: list[SystemMetric], field: str, minutes: int) -> list[tuple[datetime, float, float]]:
    buckets: dict[datetime, list[float]] = {}
    for r in rows:
        ts = ensure_aware(r.timestamp)
        key = ts.replace(second=0, microsecond=0, minute=(ts.minute // minutes) * minutes if minutes < 60 else 0)
        buckets.setdefault(key, []).append(float(getattr(r, field) or 0.0))
    return [(k, float(np.mean(v)), float(np.max(v))) for k, v in sorted(buckets.items())]


def _days_until(target: float, value_now: float, slope: float) -> float | None:
    if value_now >= target:
        return 0.0
    if slope <= 1e-9:
        return None
    return (target - value_now) / slope


def analyse_metric(db: Session, rows: list[SystemMetric], field: str, label: str, unit: str, rule_key: str,
                   bucket_minutes: int, horizon_days: int) -> dict[str, Any]:
    pts = _bucket(rows, field, bucket_minutes)
    raw = np.array([float(getattr(r, field) or 0.0) for r in rows])
    now = utcnow()
    t0 = pts[0][0]
    x = np.array([(p[0] - t0).total_seconds() / 86400 for p in pts])  # days
    y = np.array([p[1] for p in pts])
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    resid_std = float(np.std(y - fitted, ddof=2)) if len(y) > 2 else 0.0
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - float(np.sum((y - fitted) ** 2)) / ss_tot if ss_tot > 1e-12 else 0.0
    x_now = (now - t0).total_seconds() / 86400
    trend_now = float(slope * x_now + intercept)

    is_pct = unit == "percent"
    clamp = (lambda v: float(min(100.0, max(0.0, v)))) if is_pct else (lambda v: float(max(0.0, v)))
    step_days = 1.0 if horizon_days > 2 else 1 / 24
    n_steps = int(round(horizon_days / step_days))
    forecast = []
    for i in range(1, n_steps + 1):
        xd = x_now + i * step_days
        est = slope * xd + intercept
        forecast.append({"timestamp": (now + timedelta(days=i * step_days)).isoformat(), "kind": "estimate",
                         "value": clamp(est), "lower": clamp(est - 1.96 * resid_std), "upper": clamp(est + 1.96 * resid_std)})

    warning, critical = _thresholds(db, rule_key, unit)
    current = float(raw[-1])
    avg = float(raw.mean())
    eta_warning = _days_until(warning, trend_now, slope) if warning is not None else None
    eta_critical = _days_until(critical, trend_now, slope) if critical is not None else None
    if warning is not None and avg >= warning:
        status = "exceeding"
    elif eta_warning is not None and eta_warning <= horizon_days:
        status = "approaching"
    else:
        status = "stable"
    span_days = float(x[-1]) if len(x) else 0.0
    confidence = "low" if r2 < 0.3 or span_days < 1 else "medium" if r2 < 0.7 or span_days < 3 else "high"

    out: dict[str, Any] = {
        "metric": field, "label": label, "unit": unit,
        "measured": {"current": current, "average": avg, "p95": float(np.percentile(raw, 95)), "max": float(raw.max()),
                     "samples": int(len(raw))},
        "trend": {"slope_per_day": float(slope), "r2": round(r2, 3), "residual_std": resid_std,
                  "fitted_now": clamp(trend_now), "confidence": confidence},
        "thresholds": {"warning": warning, "critical": critical},
        "estimate": {
            "value_at_horizon": forecast[-1]["value"] if forecast else clamp(trend_now),
            "days_to_warning": round(eta_warning, 1) if eta_warning is not None else None,
            "days_to_critical": round(eta_critical, 1) if eta_critical is not None else None,
        },
        "status": status,
        "history": [{"timestamp": p[0].isoformat(), "kind": "measured", "value": p[1], "max": p[2]} for p in pts],
        "forecast": forecast,
    }
    out["summary"] = _summary(out, horizon_days)
    return out


def _fmt(v: float, unit: str) -> str:
    return f"{v:.1f}%" if unit == "percent" else f"{v / MB:.2f} MB/s"


def _summary(m: dict[str, Any], horizon: int) -> str:
    u, est, th = m["unit"], m["estimate"], m["thresholds"]
    if m["status"] == "exceeding":
        return f"{m['label']} already averages {_fmt(m['measured']['average'], u)}, above the warning threshold of {_fmt(th['warning'], u)}."
    if est["days_to_warning"] is not None and est["days_to_warning"] <= horizon:
        return (f"Estimated to reach the warning threshold ({_fmt(th['warning'], u)}) in about {est['days_to_warning']:.0f} days "
                f"if the current trend of {m['trend']['slope_per_day']:+.2f}{'%' if u == 'percent' else ' B/s'} per day continues.")
    return f"No threshold crossing estimated within {horizon} days (trend {m['trend']['slope_per_day']:+.2f}{'%' if u == 'percent' else ' B/s'}/day)."


def build_capacity_report(db: Session, user: User, lookback_days: int = 7, horizon_days: int = 30) -> dict[str, Any]:
    dev = get_local_device(db)
    since = utcnow() - timedelta(days=lookback_days)
    rows = db.scalars(select(SystemMetric).where(SystemMetric.device_id == dev.id, SystemMetric.timestamp >= since)
                      .order_by(SystemMetric.timestamp)).all()
    span_hours = ((ensure_aware(rows[-1].timestamp) - ensure_aware(rows[0].timestamp)).total_seconds() / 3600) if len(rows) > 1 else 0.0
    bucket_minutes = 10 if span_hours < 12 else 60
    n_buckets = len({(ensure_aware(r.timestamp).replace(second=0, microsecond=0, minute=(ensure_aware(r.timestamp).minute // bucket_minutes) * bucket_minutes if bucket_minutes < 60 else 0)) for r in rows})
    base = {"lookback_days": lookback_days, "horizon_days": horizon_days, "samples": len(rows),
            "span_hours": round(span_hours, 2), "bucket_minutes": bucket_minutes, "generated_at": utcnow().isoformat(),
            "method": "Ordinary least-squares linear trend on bucketed averages; band = ±1.96 × residual std. "
                      "Estimates assume the observed trend continues and are not measurements."}
    if n_buckets < MIN_BUCKETS or span_hours < MIN_SPAN_HOURS:
        return {**base, "status": "insufficient_data", "metrics": [], "containers": [],
                "message": (f"More monitoring history is needed for capacity estimates: {span_hours:.1f} h across {n_buckets} "
                            f"time buckets collected; at least {MIN_SPAN_HOURS} h and {MIN_BUCKETS} buckets are required.")}

    metrics = [analyse_metric(db, rows, f, label, unit, rule, bucket_minutes, horizon_days) for f, label, unit, rule in METRICS]
    latest = rows[-1]
    for m in metrics:  # absolute resource requirement estimates for memory and disk
        total = latest.memory_total if m["metric"] == "memory_percent" else latest.disk_total if m["metric"] == "disk_percent" else 0
        if total and m["thresholds"]["warning"]:
            projected_used = total * m["estimate"]["value_at_horizon"] / 100
            m["estimate"]["capacity"] = {
                "total_bytes": int(total), "measured_used_bytes": int(total * m["measured"]["current"] / 100),
                "projected_used_bytes": int(projected_used),
                "required_total_bytes_to_stay_below_warning": int(projected_used / (m["thresholds"]["warning"] / 100)),
            }

    rule = get_rule(db, "container_resource")
    cpu_l = float((rule.params or {}).get("cpu", 90)) if rule else 90.0
    mem_l = float((rule.params or {}).get("memory", 90)) if rule else 90.0
    c_stmt = select(Container).where(Container.status == "running")
    if hasattr(Container, "is_demo"):
        c_stmt = c_stmt.where(Container.is_demo.is_(False))
    if not user.is_admin:
        c_stmt = c_stmt.where(Container.owner_id == user.id)
    containers = []
    for c in db.scalars(c_stmt).all():
        ratio = max(c.cpu_percent / cpu_l, c.memory_percent / mem_l)
        if ratio >= 0.8:
            containers.append({"name": c.name, "cpu_percent": c.cpu_percent, "memory_percent": c.memory_percent,
                               "cpu_threshold": cpu_l, "memory_threshold": mem_l, "kind": "measured",
                               "status": "exceeding" if ratio >= 1 else "approaching"})
    return {**base, "status": "ready", "message": "", "metrics": metrics, "containers": containers}
