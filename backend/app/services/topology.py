"""Infrastructure topology graph built from monitored resources (no invented nodes).

Nodes: host devices, the Docker Engine and VirtualBox hypervisor (only when connected or when
resources from them are known), containers, Docker networks and virtual machines.
Edges: host→engine/hypervisor, engine→container, container→network, hypervisor→VM.
Each node gets a health classification and the number of active alerts that reference it.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import ensure_aware, utcnow
from app.docker_integration.adapter import get_docker_adapter
from app.models import Alert, Container, Device, SystemMetric, User, VirtualMachine
from app.monitoring.service import health_status
from app.services import settings_service
from app.virtualization.vbox import get_vbox_adapter

HEALTH_ORDER = ["critical", "warning", "unavailable", "stopped", "healthy"]


def _container_health(c: Container) -> str:
    if c.health == "unhealthy":
        return "critical"
    if c.status in ("exited", "dead"):
        return "critical" if (c.exit_code or 0) not in (0, 143) else "stopped"
    if c.status in ("restarting", "paused"):
        return "warning"
    return "healthy" if c.status == "running" else "warning"


def _vm_health(v: VirtualMachine) -> str:
    if v.state == "running":
        return "healthy"
    if v.state in ("aborted", "gurumeditation"):
        return "critical"
    if v.state in ("poweroff", "saved"):
        return "stopped"
    return "warning"


def build_topology(db: Session, user: User, include_demo: bool = False) -> dict[str, Any]:
    demo = include_demo
    active_alerts = dict(db.execute(
        select(Alert.resource_name, func.count(Alert.id)).where(Alert.status != "resolved", Alert.is_demo.is_(demo))
        .group_by(Alert.resource_name)).all())
    interval = int(settings_service.get_section(db, "monitoring")["interval_seconds"])
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []

    def add(node_id: str, kind: str, label: str, health: str, details: dict[str, Any], alert_key: str | None = None,
            link: str = "") -> None:
        n_alerts = active_alerts.get(alert_key or label, 0)
        if n_alerts and health == "healthy":
            health = "warning"
        nodes.append({"id": node_id, "type": kind, "label": label, "health": health, "alerts": n_alerts,
                      "details": details, "link": link})

    dev_stmt = select(Device).where(Device.is_demo.is_(demo)).order_by(Device.id)
    devices = db.scalars(dev_stmt).all()
    host_id = None
    for d in devices:
        latest = db.scalar(select(SystemMetric).where(SystemMetric.device_id == d.id).order_by(SystemMetric.timestamp.desc()).limit(1))
        stale = latest is None or utcnow() - ensure_aware(latest.timestamp) > timedelta(seconds=max(60, interval * 3))
        if stale and not demo:
            health = "unavailable"
        else:
            h = health_status(latest.cpu_percent, latest.memory_percent, latest.disk_percent)["status"] if latest else "healthy"
            health = {"healthy": "healthy", "degraded": "warning", "critical": "critical"}[h]
        nid = f"device:{d.id}"
        host_id = host_id or nid
        add(nid, "host", d.name, health, {
            "hostname": d.hostname, "ip": d.ip_address, "os": d.os_info,
            "cpu_percent": latest.cpu_percent if latest else None, "memory_percent": latest.memory_percent if latest else None,
            "disk_percent": latest.disk_percent if latest else None,
            "last_seen": ensure_aware(latest.timestamp).isoformat() if latest else None,
        }, alert_key=d.hostname, link="/monitoring")

    # ---- containers
    c_stmt = select(Container).where(Container.status != "removed", Container.is_demo.is_(demo)).order_by(Container.name)
    if not user.is_admin:
        c_stmt = c_stmt.where(Container.owner_id == user.id)
    containers = db.scalars(c_stmt).all()
    docker = {"available": True, "mode": "demo"} if demo else get_docker_adapter().status()
    if containers or docker.get("available"):
        engine_id = "docker-engine"
        add(engine_id, "docker", "Docker Engine", "healthy" if docker.get("available") else "unavailable",
            {"version": docker.get("version"), "mode": docker.get("mode"), "message": docker.get("message")}, link="/containers")
        if host_id:
            edges.append({"source": host_id, "target": engine_id, "kind": "runs"})
        networks: set[str] = set()
        for c in containers:
            cid = f"container:{c.id}"
            add(cid, "container", c.name, _container_health(c) if docker.get("available") else "unavailable", {
                "image": c.image, "status": c.status, "health": c.health, "restarts": c.restart_count,
                "cpu_percent": c.cpu_percent, "memory_percent": c.memory_percent, "networks": c.networks or [],
                "exit_code": c.exit_code,
            }, link="/containers")
            edges.append({"source": engine_id, "target": cid, "kind": "hosts"})
            for net in c.networks or []:
                networks.add(net)
                edges.append({"source": cid, "target": f"network:{net}", "kind": "attached"})
        for net in sorted(networks):
            add(f"network:{net}", "network", net, "healthy",
                {"containers": sum(net in (c.networks or []) for c in containers)}, alert_key=f"network:{net}")

    # ---- virtual machines
    v_stmt = select(VirtualMachine).where(VirtualMachine.is_demo.is_(demo)).order_by(VirtualMachine.name)
    if not user.is_admin:
        v_stmt = v_stmt.where(VirtualMachine.owner_id == user.id)
    vbox = {"available": True, "mode": "demo"} if demo else get_vbox_adapter().status()
    vms = db.scalars(v_stmt).all() if vbox.get("available") else []  # never show VMs as monitored when disconnected
    if vbox.get("available"):
        hv_id = "virtualbox"
        add(hv_id, "hypervisor", "VirtualBox", "healthy", {"version": vbox.get("version"), "mode": vbox.get("mode")}, link="/vms")
        if host_id:
            edges.append({"source": host_id, "target": hv_id, "kind": "runs"})
        for v in vms:
            vid = f"vm:{v.id}"
            add(vid, "vm", v.name, _vm_health(v), {"state": v.state, "os": v.os_type, "memory_mb": v.memory_mb, "cpus": v.cpus,
                                                   "uuid": v.uuid}, link="/vms")
            edges.append({"source": hv_id, "target": vid, "kind": "hosts"})

    summary = {h: sum(n["health"] == h for n in nodes) for h in HEALTH_ORDER}
    return {
        "nodes": nodes, "edges": edges, "summary": summary, "demo": demo,
        "integrations": {"docker": {"available": bool(docker.get("available")), "message": docker.get("message")},
                         "virtualbox": {"available": bool(vbox.get("available")), "message": vbox.get("message")}},
        "generated_at": utcnow().isoformat(),
    }
