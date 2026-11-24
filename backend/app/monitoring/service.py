"""Monitoring service: persist metrics, evaluate rules, push realtime updates, expose Prometheus gauges."""
from __future__ import annotations

import logging
import platform
import socket
from datetime import timedelta

from prometheus_client import Gauge
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.models import Device, SystemMetric
from app.monitoring.collector import collector, primary_ip
from app.realtime.bus import manager
from app.schemas import MetricOut
from app.security_engine import engine
from app.services import settings_service

log = logging.getLogger("cloudguard.monitoring")

G_CPU = Gauge("cloudguard_host_cpu_percent", "Host CPU utilisation percent")
G_MEM = Gauge("cloudguard_host_memory_percent", "Host memory utilisation percent")
G_DISK = Gauge("cloudguard_host_disk_percent", "Host disk utilisation percent")
G_TX = Gauge("cloudguard_host_net_send_bytes_per_second", "Host network upload rate")
G_RX = Gauge("cloudguard_host_net_recv_bytes_per_second", "Host network download rate")
G_PROC = Gauge("cloudguard_host_process_count", "Running processes")


def get_local_device(db: Session) -> Device:
    host = socket.gethostname()
    dev = db.scalar(select(Device).where(Device.hostname == host))
    if dev is None:
        dev = Device(
            name=f"{host} (local host)", hostname=host, device_type="host",
            os_info=platform.platform(), ip_address=primary_ip(), status="online", last_seen_at=utcnow(),
        )
        db.add(dev)
        db.commit()
        db.refresh(dev)
    return dev


def collect_and_store(db: Session) -> SystemMetric:
    device = get_local_device(db)
    previous = db.scalar(
        select(SystemMetric).where(SystemMetric.device_id == device.id).order_by(SystemMetric.timestamp.desc()).limit(1)
    )
    data = collector.collect()
    metric = SystemMetric(device_id=device.id, **data)
    db.add(metric)
    device.last_seen_at = data["timestamp"]
    device.status = "online"
    db.commit()
    db.refresh(metric)

    for g, v in ((G_CPU, metric.cpu_percent), (G_MEM, metric.memory_percent), (G_DISK, metric.disk_percent),
                 (G_TX, metric.net_send_rate), (G_RX, metric.net_recv_rate), (G_PROC, metric.process_count)):
        g.set(v)

    manager.publish("monitoring", {"type": "metric", "device_id": device.id,
                                   "metric": MetricOut.model_validate(metric).model_dump(mode="json")})
    try:
        engine.evaluate_metric(db, metric, device.hostname, previous)
        watch = settings_service.get_section(db, "monitoring").get("process_watchlist") or []
        if watch:
            engine.evaluate_processes(db, collector.process_names(), watch, device.hostname)
    except Exception:  # detection must never break collection
        log.exception("rule evaluation failed")
        db.rollback()
    return metric


def prune_old_metrics(db: Session) -> int:
    days = int(settings_service.get_section(db, "monitoring")["retention_days"])
    cutoff = utcnow() - timedelta(days=days)
    res = db.execute(delete(SystemMetric).where(SystemMetric.timestamp < cutoff))
    db.commit()
    return res.rowcount or 0


def health_status(cpu: float, mem: float, disk: float) -> dict:
    """Overall health from current utilisation: healthy / degraded / critical."""
    issues = []
    level = "healthy"
    for name, v, warn, crit in (("CPU", cpu, 80, 95), ("Memory", mem, 85, 95), ("Disk", disk, 90, 97)):
        if v >= crit:
            level = "critical"
            issues.append(f"{name} critical ({v:.0f}%)")
        elif v >= warn:
            if level != "critical":
                level = "degraded"
            issues.append(f"{name} high ({v:.0f}%)")
    score = max(0, round(100 - max(0, cpu - 50) * 0.4 - max(0, mem - 50) * 0.4 - max(0, disk - 60) * 0.5))
    return {"status": level, "score": score, "issues": issues}
