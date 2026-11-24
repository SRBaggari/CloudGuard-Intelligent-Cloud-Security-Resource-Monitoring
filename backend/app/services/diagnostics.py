"""System health diagnostics for administrators (all values measured at request time)."""
from __future__ import annotations

import os
import platform
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import EPHEMERAL_JWT_SECRET, get_settings
from app.core.database import ensure_aware, utcnow
from app.docker_integration.adapter import get_docker_adapter
from app.ml_engine.detector import detector
from app.models import Alert, Incident, SystemMetric, User
from app.monitoring.collector import collector
from app.realtime.bus import manager
from app.services import settings_service
from app.virtualization.vbox import get_vbox_adapter

STARTED_AT = time.time()


def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def run_diagnostics(db: Session) -> dict[str, Any]:
    s = get_settings()
    checks: list[dict[str, str]] = []

    def check(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    # ---- database
    t = time.perf_counter()
    db.execute(text("SELECT 1"))
    latency_ms = round((time.perf_counter() - t) * 1000, 2)
    dialect = db.get_bind().dialect.name
    revision = None
    if "alembic_version" in inspect(db.get_bind()).get_table_names():
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    check("Database connection", "ok" if latency_ms < 200 else "warning", f"{dialect}, round-trip {latency_ms} ms")
    check("Schema migrations", "ok" if revision else "warning",
          f"Alembic revision {revision}" if revision else "No Alembic revision recorded (schema created directly, e.g. tests)")

    # ---- background loops
    from app.services.scheduler import LOOP_STATUS
    loops = {}
    if not s.enable_background_tasks:
        check("Background tasks", "warning", "Disabled (ENABLE_BACKGROUND_TASKS=false)")
    for name, st in LOOP_STATUS.items():
        last = st.get("last_run")
        age = (utcnow() - datetime.fromisoformat(last)).total_seconds() if last else None
        overdue = age is not None and age > max(60, 3 * float(st.get("interval_seconds") or 60))
        status = "error" if overdue else "warning" if st.get("errors") and st.get("last_error") else "ok"
        loops[name] = {**st, "seconds_since_last_run": round(age, 1) if age is not None else None, "status": status}
        check(f"Loop: {name}", status, f"{st['runs']} runs, {st['errors']} errors, last {round(age or 0)} s ago")

    # ---- collector freshness
    interval = int(settings_service.get_section(db, "monitoring")["interval_seconds"])
    last_metric = db.scalar(select(func.max(SystemMetric.timestamp)))
    age = (utcnow() - ensure_aware(last_metric)).total_seconds() if last_metric else None
    check("Metric collection", "ok" if age is not None and age <= max(60, 3 * interval) else "error",
          f"Last sample {round(age)} s ago (interval {interval} s)" if age is not None else "No samples yet")
    pool = "worker process" if collector._pool is not None else ("in-process (fallback)" if collector._pool_failed else "not started yet")
    check("Process scanner", "ok" if collector._pool is not None or not collector._pool_failed else "warning", pool)

    # ---- storage
    usage = shutil.disk_usage(s.data_dir)
    free_pct = usage.free / usage.total * 100
    check("Data directory storage", "ok" if free_pct > 10 else "warning", f"{free_pct:.1f}% free on the data volume")
    reports_bytes = _dir_size(s.data_dir / "reports")

    # ---- security configuration
    check("JWT secret", "error" if EPHEMERAL_JWT_SECRET else "ok",
          "Ephemeral secret (set JWT_SECRET_KEY)" if EPHEMERAL_JWT_SECRET else "Configured")

    docker = get_docker_adapter().status() if s.docker_enabled else {"available": False, "message": "Disabled"}
    vbox = get_vbox_adapter().status() if s.virtualbox_enabled else {"available": False, "message": "Disabled"}
    check("Docker Engine", "ok" if docker.get("available") else "info", docker.get("message") or f"version {docker.get('version')}")
    check("VirtualBox", "ok" if vbox.get("available") else "info", vbox.get("message") or f"version {vbox.get('version')}")
    ml = detector.info()
    check("Anomaly model", "ok" if ml else "info", f"Model {ml['version']} ({ml['n_samples']} samples)" if ml else "Not trained")

    proc = psutil.Process(os.getpid())
    overall = "error" if any(c["status"] == "error" for c in checks) else "warning" if any(c["status"] == "warning" for c in checks) else "ok"
    return {
        "status": overall,
        "checked_at": utcnow().isoformat(),
        "checks": checks,
        "application": {
            "version": "1.1.0", "environment": s.app_env, "integration_mode": s.integration_mode,
            "python": sys.version.split()[0], "platform": platform.platform(), "pid": os.getpid(),
            "started_at": datetime.fromtimestamp(STARTED_AT, timezone.utc).isoformat(),
            "uptime_seconds": int(time.time() - STARTED_AT), "memory_rss_bytes": proc.memory_info().rss,
            "threads": proc.num_threads(),
        },
        "database": {"dialect": dialect, "latency_ms": latency_ms, "revision": revision,
                     "rows": {"users": db.scalar(select(func.count(User.id))), "metrics": db.scalar(select(func.count(SystemMetric.id))),
                              "alerts": db.scalar(select(func.count(Alert.id))), "incidents": db.scalar(select(func.count(Incident.id)))}},
        "background_loops": loops,
        "storage": {"data_dir": str(s.data_dir), "free_bytes": usage.free, "total_bytes": usage.total, "reports_bytes": reports_bytes},
        "realtime": manager.stats(),
    }
