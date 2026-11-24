"""Background collection loops (metrics, containers, VMs, integrity scans, ML scoring)."""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal, utcnow
from app.docker_integration.service import sync_containers
from app.integrity.fim import scan_directory
from app.ml_engine.detector import detector
from app.models import MonitoredDirectory
from app.monitoring.service import collect_and_store, prune_old_metrics
from app.services import settings_service
from app.services.alerts import detect, get_rule
from app.virtualization.service import sync_vms

log = logging.getLogger("cloudguard.scheduler")

FIM_INTERVAL_SECONDS = 300

# Live status of each background loop, exposed by the diagnostics endpoint.
LOOP_STATUS: dict[str, dict] = {}


def _metrics_tick() -> int:
    with SessionLocal() as db:
        metric = collect_and_store(db)
        ml = settings_service.get_section(db, "ml")
        if ml.get("enabled"):
            rec = detector.score_and_store(db, metric)
            if rec and ml.get("auto_alert"):
                rule = get_rule(db, "ml_anomaly")
                n = int((rule.params or {}).get("consecutive", 2)) if rule else 2
                recent = detector.score(_last_metrics(db, metric.device_id, n))
                if len(recent) >= n and all(r["is_anomaly"] for r in recent):
                    detect(db, "ml_anomaly", title="Anomalous resource behaviour detected",
                           description=f"Isolation Forest flagged {n} consecutive samples. {rec.explanation}",
                           resource_type="host", resource_name=metric.device.hostname,
                           details={"score": round(rec.score, 4), "explanation": rec.explanation})
        return int(settings_service.get_section(db, "monitoring")["interval_seconds"])


def _last_metrics(db, device_id: int, n: int):
    from app.models import SystemMetric
    return db.scalars(select(SystemMetric).where(SystemMetric.device_id == device_id)
                      .order_by(SystemMetric.timestamp.desc()).limit(n)).all()[::-1]


def _infra_tick() -> int:
    s = get_settings()
    with SessionLocal() as db:
        if s.docker_enabled:
            sync_containers(db)
        if s.virtualbox_enabled:
            sync_vms(db)
        return int(settings_service.get_section(db, "monitoring")["container_poll_interval_seconds"])


def _fim_tick() -> None:
    with SessionLocal() as db:
        for d in db.scalars(select(MonitoredDirectory).where(MonitoredDirectory.enabled.is_(True))).all():
            try:
                scan_directory(db, d)
            except Exception as e:
                log.warning("integrity scan failed for %s: %s", d.path, e)


def _prune_tick() -> None:
    with SessionLocal() as db:
        n = prune_old_metrics(db)
        if n:
            log.info("pruned %d old metric rows", n)


async def _loop(name: str, fn, default_interval: float) -> None:
    st = LOOP_STATUS.setdefault(name, {"runs": 0, "errors": 0, "last_run": None, "last_duration_ms": None,
                                       "last_error": None, "interval_seconds": default_interval})
    while True:
        started = time.monotonic()
        interval = default_interval
        try:
            res = await asyncio.to_thread(fn)
            if isinstance(res, int) and res > 0:
                interval = res
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("%s loop iteration failed", name)
            st["errors"] += 1
            st["last_error"] = f"{e.__class__.__name__}: {e}"[:300]
        st["runs"] += 1
        st["last_run"] = utcnow().isoformat()
        st["last_duration_ms"] = round((time.monotonic() - started) * 1000, 1)
        st["interval_seconds"] = interval
        await asyncio.sleep(max(0.5, interval - (time.monotonic() - started)))


def start_background_tasks() -> list[asyncio.Task]:
    s = get_settings()
    return [
        asyncio.create_task(_loop("metrics", _metrics_tick, s.metrics_interval_seconds)),
        asyncio.create_task(_loop("infrastructure", _infra_tick, s.container_poll_interval_seconds)),
        asyncio.create_task(_loop("integrity", _fim_tick, FIM_INTERVAL_SECONDS)),
        asyncio.create_task(_loop("retention", _prune_tick, 3600)),
    ]
