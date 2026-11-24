"""Synchronise Docker containers into the database and detect container security conditions."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import ensure_aware, utcnow
from app.docker_integration.adapter import DockerUnavailable, get_docker_adapter
from app.models import Container
from app.realtime.bus import manager
from app.security_engine import engine
from app.services.alerts import detect, get_rule

log = logging.getLogger("cloudguard.docker")

RUNNING = {"running"}
STOPPED = {"exited", "dead"}


def sync_containers(db: Session, with_stats: bool = True) -> dict:
    adapter = get_docker_adapter()
    try:
        items = adapter.list_containers()
    except DockerUnavailable as e:
        return {"available": False, "message": str(e), "synced": 0}

    seen = set()
    now = utcnow()
    res_rule = get_rule(db, "container_resource")
    for it in items:
        seen.add(it["id"])
        row = db.scalar(select(Container).where(Container.container_id == it["id"]))
        prev_status = prev_restarts = prev_health = None
        if row is None:
            row = Container(container_id=it["id"], name=it["name"])
            db.add(row)
        else:
            prev_status, prev_restarts, prev_health = row.status, row.restart_count, row.health
        row.name = it["name"]
        row.image = it["image"]
        row.status = it["status"]
        row.health = it["health"]
        row.restart_count = it["restart_count"]
        row.exit_code = it.get("exit_code")
        row.networks = it.get("networks", [])
        row.last_seen_at = now
        if with_stats and it["status"] == "running":
            try:
                st = adapter.stats(it["id"])
                row.cpu_percent = st["cpu_percent"]
                row.memory_percent = st["memory_percent"]
                row.memory_usage = st["memory_usage"]
                row.net_rx_bytes = st["net_rx_bytes"]
                row.net_tx_bytes = st["net_tx_bytes"]
            except Exception:
                log.debug("stats failed for %s", it["name"], exc_info=True)
        elif it["status"] != "running":
            row.cpu_percent = row.memory_percent = 0.0
            row.memory_usage = 0
        db.commit()

        name = row.name
        # --- detection on state transitions
        if prev_status in RUNNING and row.status in STOPPED:
            expected = ensure_aware(row.expected_stop_at)
            if expected and now - expected < timedelta(minutes=5):
                row.expected_stop_at = None
                db.commit()
            else:
                detect(db, "container_unexpected_exit", title=f"Container '{name}' stopped unexpectedly",
                       description=f"Container '{name}' ({row.image}) changed from running to {row.status} "
                                   f"(exit code {row.exit_code}) without a CloudGuard stop action.",
                       resource_type="container", resource_name=name, details={"exit_code": row.exit_code})
                engine.register_failure(db, "container", name, f"exited with code {row.exit_code}")
        if row.health == "unhealthy" and prev_health != "unhealthy":
            detect(db, "container_unhealthy", title=f"Container '{name}' is unhealthy",
                   description=f"Docker health check reports '{name}' as unhealthy.",
                   resource_type="container", resource_name=name)
        if prev_restarts is not None and row.restart_count > prev_restarts:
            detect(db, "container_restart", title=f"Container '{name}' restarted",
                   description=f"Restart count of '{name}' increased from {prev_restarts} to {row.restart_count}.",
                   resource_type="container", resource_name=name,
                   details={"restart_count": row.restart_count})
            engine.register_failure(db, "container", name, "restarted by Docker")
        if res_rule and res_rule.enabled and row.status == "running":
            cpu_l = float(res_rule.params.get("cpu", 90))
            mem_l = float(res_rule.params.get("memory", 90))
            if row.cpu_percent >= cpu_l or row.memory_percent >= mem_l:
                detect(db, "container_resource", title=f"High resource usage in container '{name}'",
                       description=f"Container '{name}' CPU {row.cpu_percent:.1f}% / memory {row.memory_percent:.1f}% "
                                   f"(limits {cpu_l:.0f}% / {mem_l:.0f}%).",
                       resource_type="container", resource_name=name,
                       details={"cpu": row.cpu_percent, "memory": row.memory_percent})

    # Containers removed from Docker
    for row in db.scalars(select(Container)).all():
        if row.container_id not in seen and row.status != "removed":
            row.status = "removed"
            db.commit()

    manager.publish("monitoring", {"type": "containers.synced", "count": len(items)})
    return {"available": True, "synced": len(items)}
