"""Demonstration & academic mode.

Creates a clearly labelled, *separate* demonstration environment (every row has ``is_demo=True``
and every name starts with ``demo``) so alert generation and incident handling can be shown
safely, without touching real infrastructure:

* Sample infrastructure: one demo node with three days of generated metrics, five demo containers
  on two networks and two demo VMs.
* Scenarios: most push sample state through CloudGuard's *real* detection code (threshold rules,
  container transition rules) inside ``demo_scope()``; the others record clearly labelled sample
  events. Nothing executes against Docker, VirtualBox, user accounts or the file system.
* Real dashboards, alert lists, reports, analytics and compliance exclude demo data.
"""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Callable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.database import ensure_aware, utcnow
from app.models import Alert, Container, Device, Incident, SecurityEvent, SystemMetric, User, VirtualMachine
from app.security_engine import engine
from app.services.alerts import demo_scope, detect, record_event

DEMO_HOSTNAME = "demo-node-01.cloudguard.demo"
GiB = 1024 ** 3

DEMO_CONTAINERS = [
    # name, image, status, health, networks, cpu %, mem %
    ("demo-web", "nginx:1.27-alpine", "running", "healthy", ["demo-frontend-net"], 6.5, 12.0),
    ("demo-api", "python:3.12-slim", "running", "healthy", ["demo-frontend-net", "demo-backend-net"], 18.0, 41.0),
    ("demo-db", "postgres:16", "running", "healthy", ["demo-backend-net"], 9.0, 63.0),
    ("demo-cache", "redis:7-alpine", "running", "none", ["demo-backend-net"], 2.5, 8.0),
    ("demo-worker", "python:3.12-slim", "exited", "none", ["demo-backend-net"], 0.0, 0.0),
]
DEMO_VMS = [
    ("de000000-0000-4000-8000-000000000001", "demo-ubuntu-app-vm", "running", "Ubuntu_64", 4096, 2),
    ("de000000-0000-4000-8000-000000000002", "demo-windows-lab-vm", "poweroff", "Windows11_64", 8192, 4),
]


def get_demo_device(db: Session) -> Device | None:
    return db.scalar(select(Device).where(Device.hostname == DEMO_HOSTNAME, Device.is_demo.is_(True)))


def _metric(dev: Device, ts, i: int) -> SystemMetric:
    """Deterministic sample metrics: a daily load cycle plus slow memory/disk growth."""
    hours = i / 6
    day = 2 * math.pi * hours / 24
    return SystemMetric(
        device_id=dev.id, timestamp=ts,
        cpu_percent=round(32 + 14 * math.sin(day - 1.2) + 3 * math.sin(i * 1.7), 2),
        memory_percent=round(54 + 6 * math.sin(day) + 1.6 * hours / 24 + 1.5 * math.sin(i * 0.9), 2),
        memory_used=0, memory_total=32 * GiB,
        disk_percent=round(63 + 1.3 * hours / 24 + 0.05 * math.sin(i), 2), disk_used=0, disk_total=512 * GiB,
        net_bytes_sent=0, net_bytes_recv=0,
        net_send_rate=round(180_000 + 120_000 * max(0.0, math.sin(day)), 1),
        net_recv_rate=round(650_000 + 400_000 * max(0.0, math.sin(day - 0.5)), 1),
        process_count=int(215 + 20 * math.sin(day)), connection_count=int(140 + 60 * max(0.0, math.sin(day))),
    )


def seed_demo(db: Session) -> dict[str, Any]:
    """Create the demo environment (idempotent)."""
    if get_demo_device(db):
        return status(db)
    now = utcnow()
    dev = Device(name="Demo cluster node (DEMO)", hostname=DEMO_HOSTNAME, device_type="host",
                 os_info="Ubuntu 24.04 LTS (sample)", ip_address="192.0.2.10", status="online", last_seen_at=now,
                 is_demo=True)
    db.add(dev)
    db.flush()
    n = 3 * 24 * 6  # three days at 10-minute resolution
    start = now - timedelta(minutes=10 * (n - 1))
    db.add_all([_metric(dev, start + timedelta(minutes=10 * i), i) for i in range(n)])
    for i, (name, image, st, health, nets, cpu, mem) in enumerate(DEMO_CONTAINERS):
        db.add(Container(container_id=f"demo{i:02d}" + "d" * 58, name=name, image=image, status=st, health=health,
                         networks=nets, cpu_percent=cpu, memory_percent=mem, memory_usage=int(mem / 100 * 2 * GiB),
                         restart_count=0, exit_code=0 if st == "exited" else None, device_id=dev.id, last_seen_at=now,
                         is_demo=True))
    for uuid, name, state, os_type, mem_mb, cpus in DEMO_VMS:
        db.add(VirtualMachine(uuid=uuid, name=name, state=state, os_type=os_type, memory_mb=mem_mb, cpus=cpus,
                              config={"firmware": "EFI", "nic1": "nat", "note": "demonstration VM"}, device_id=dev.id,
                              last_seen_at=now, is_demo=True))
    db.commit()
    return status(db)


def reset_demo(db: Session) -> dict[str, Any]:
    """Delete every demonstration row (real data is untouched)."""
    db.execute(delete(Incident).where(Incident.is_demo.is_(True)))
    db.execute(delete(Alert).where(Alert.is_demo.is_(True)))  # notifications cascade via alert FK
    db.execute(delete(SecurityEvent).where(SecurityEvent.is_demo.is_(True)))
    db.execute(delete(Container).where(Container.is_demo.is_(True)))
    db.execute(delete(VirtualMachine).where(VirtualMachine.is_demo.is_(True)))
    dev = get_demo_device(db)
    if dev:
        db.execute(delete(SystemMetric).where(SystemMetric.device_id == dev.id))
        db.delete(dev)
    db.commit()
    return status(db)


def status(db: Session) -> dict[str, Any]:
    dev = get_demo_device(db)

    def count(model, *where):
        return db.scalar(select(func.count(model.id)).where(*where)) or 0

    return {
        "active": dev is not None,
        "device": dev.name if dev else None,
        "metrics": count(SystemMetric, SystemMetric.device_id == dev.id) if dev else 0,
        "containers": count(Container, Container.is_demo.is_(True)),
        "vms": count(VirtualMachine, VirtualMachine.is_demo.is_(True)),
        "alerts": count(Alert, Alert.is_demo.is_(True)),
        "open_alerts": count(Alert, Alert.is_demo.is_(True), Alert.status != "resolved"),
        "events": count(SecurityEvent, SecurityEvent.is_demo.is_(True)),
        "incidents": count(Incident, Incident.is_demo.is_(True)),
    }


# ------------------------------------------------------------------ scenarios
class DemoNotReady(Exception):
    pass


def _container(db: Session, name: str) -> Container:
    c = db.scalar(select(Container).where(Container.name == name, Container.is_demo.is_(True)))
    if c is None:
        raise DemoNotReady("Create the demonstration environment first")
    return c


def _cpu_spike(db: Session, user: User) -> list[Alert | None]:
    dev = get_demo_device(db)
    if dev is None:
        raise DemoNotReady("Create the demonstration environment first")
    last = db.scalar(select(SystemMetric).where(SystemMetric.device_id == dev.id).order_by(SystemMetric.timestamp.desc()).limit(1))
    # always place the spike after the newest existing sample so it forms the "last N samples" the rule reads
    base = max(utcnow(), ensure_aware(last.timestamp) if last else utcnow())
    rows = []
    for k, cpu in enumerate((96.4, 97.8, 98.6)):
        m = _metric(dev, base + timedelta(seconds=10 * (k + 1)), 999 + k)
        m.cpu_percent = cpu
        db.add(m)
        rows.append(m)
    db.commit()
    engine.evaluate_metric(db, rows[-1], DEMO_HOSTNAME, last)  # real threshold rule
    return [db.scalar(select(Alert).where(Alert.fingerprint == f"demo:cpu_threshold:host:{DEMO_HOSTNAME}"))]


def _container_crash(db: Session, user: User) -> list[Alert | None]:
    from app.docker_integration.service import evaluate_container_transition
    c = _container(db, "demo-api")
    now = utcnow()
    if c.status != "running":  # recover first so the scenario can be repeated
        prev_restarts = c.restart_count
        c.status, c.exit_code, c.restart_count = "running", None, c.restart_count + 1
        db.commit()
        evaluate_container_transition(db, c, "exited", prev_restarts, c.health, now)
    c.status, c.exit_code = "exited", 137
    c.cpu_percent = c.memory_percent = 0.0
    db.commit()
    evaluate_container_transition(db, c, "running", c.restart_count, c.health, now)  # real container rules
    return [db.scalar(select(Alert).where(Alert.fingerprint == "demo:container_unexpected_exit:container:demo-api"))]


def _container_unhealthy(db: Session, user: User) -> list[Alert | None]:
    from app.docker_integration.service import evaluate_container_transition
    c = _container(db, "demo-web")
    prev = c.health
    if prev == "unhealthy":
        c.health = "healthy"
        db.commit()
        prev = "healthy"
    c.health = "unhealthy"
    db.commit()
    evaluate_container_transition(db, c, c.status, c.restart_count, prev, utcnow())
    return [db.scalar(select(Alert).where(Alert.fingerprint == "demo:container_unhealthy:container:demo-web"))]


def _brute_force(db: Session, user: User) -> list[Alert | None]:
    # Sample events only: real login tables and real accounts are never touched.
    for i in range(6):
        record_event(db, "login_failed", "authentication", f"[Sample] Failed login for 'demo-analyst' from 198.51.100.23 (attempt {i + 1})",
                     severity="low", resource="demo-analyst", details={"ip": "198.51.100.23", "sample": True})
    db.commit()
    return [detect(db, "auth_bruteforce", title="6 failed logins for 'demo-analyst'",
                   description="[Sample] 6 failed login attempts for demo account 'demo-analyst' within 10 minutes from "
                               "198.51.100.23 (documentation address range).",
                   resource_type="account", resource_name="demo-analyst", details={"failures": 6, "sample": True})]


def _file_tamper(db: Session, user: User) -> list[Alert | None]:
    return [detect(db, "fim_change", title="3 file change(s) in /srv/demo-app",
                   description="[Sample] Integrity scan found 1 modified, 1 new and 1 deleted file(s) compared with the baseline.",
                   resource_type="directory", resource_name="/srv/demo-app", severity="high",
                   details={"modified": 1, "new": 1, "deleted": 1, "sample": True,
                            "files": ["modified: /srv/demo-app/config/app.ini", "new: /srv/demo-app/upload.php",
                                      "deleted: /srv/demo-app/robots.txt"]})]


def _vm_abort(db: Session, user: User) -> list[Alert | None]:
    vm = db.scalar(select(VirtualMachine).where(VirtualMachine.name == "demo-ubuntu-app-vm", VirtualMachine.is_demo.is_(True)))
    if vm is None:
        raise DemoNotReady("Create the demonstration environment first")
    vm.state = "aborted"
    db.commit()
    a = detect(db, "vm_unexpected_stop", title=f"VM '{vm.name}' stopped unexpectedly",
               description=f"[Sample] Demo VM '{vm.name}' changed from running to aborted without a CloudGuard action.",
               resource_type="vm", resource_name=vm.name, severity="critical", details={"state": "aborted", "sample": True})
    engine.register_failure(db, "vm", vm.name, "state aborted")
    vm.state = "running"  # ready for the next demonstration
    db.commit()
    return [a]


def _anomaly(db: Session, user: User) -> list[Alert | None]:
    return [detect(db, "ml_anomaly", title="Anomalous resource behaviour detected",
                   description="[Sample] Isolation Forest flagged 2 consecutive samples. Download rate 48.2 MB/s is 6.1σ above "
                               "normal (0.8 MB/s); Connections 912 is 4.3σ above normal (151).",
                   resource_type="host", resource_name=DEMO_HOSTNAME, details={"score": -0.142, "sample": True})]


def _incident(db: Session, user: User) -> dict[str, Any]:
    from app.services import incidents as inc_svc
    alerts = db.scalars(select(Alert).where(Alert.is_demo.is_(True), Alert.status != "resolved")
                        .order_by(Alert.id.desc()).limit(3)).all()
    if not alerts:
        alerts = [a for a in _cpu_spike(db, user) + _container_crash(db, user) if a]
    inc = inc_svc.create_incident(
        db, title="[Demo] API outage under high CPU load",
        description="Demonstration incident: the demo API container crashed while the demo node was under sustained CPU load.",
        severity=None, category="availability", alert_ids=[a.id for a in alerts], assignee_id=user.id, user=user)
    inc_svc.change_status(db, inc, "acknowledged", user, "Demo: on-call engineer acknowledged")
    inc_svc.add_note(db, inc, "Demo note: CPU spike started shortly before the container exited with code 137 (OOM kill).", user)
    return {"incident_id": inc.id, "reference": inc.reference, "alert_ids": [a.id for a in alerts]}


SCENARIOS: dict[str, dict[str, Any]] = {
    "cpu_spike": {"title": "CPU saturation", "engine": True, "fn": _cpu_spike,
                  "description": "Adds three demo samples at 96–99% CPU; the real CPU threshold rule raises the alert."},
    "container_crash": {"title": "Container crash (exit 137)", "engine": True, "fn": _container_crash,
                        "description": "demo-api goes from running to exited; the real container rules raise 'unexpected termination'."},
    "container_unhealthy": {"title": "Unhealthy container", "engine": True, "fn": _container_unhealthy,
                            "description": "demo-web's health check turns unhealthy; evaluated by the real container rules."},
    "brute_force": {"title": "Brute-force login attempts", "engine": False, "fn": _brute_force,
                    "description": "Records six sample failed-login events for a demo account (no real account is affected)."},
    "file_tamper": {"title": "File tampering", "engine": False, "fn": _file_tamper,
                    "description": "Sample integrity finding: modified, new and deleted files in a demo directory."},
    "vm_abort": {"title": "VM crash", "engine": False, "fn": _vm_abort,
                 "description": "Demo VM aborts unexpectedly (critical) and counts towards repeated-failure detection."},
    "anomaly": {"title": "ML anomaly", "engine": False, "fn": _anomaly,
                "description": "Sample anomaly alert with a per-feature explanation."},
    "incident": {"title": "Incident walkthrough", "engine": False, "fn": _incident,
                 "description": "Creates a demo incident from open demo alerts, acknowledges it and adds a note."},
}


def run_scenario(db: Session, name: str, user: User) -> dict[str, Any]:
    sc = SCENARIOS[name]
    if get_demo_device(db) is None:
        raise DemoNotReady("Create the demonstration environment first")
    fn: Callable = sc["fn"]
    with demo_scope():
        result = fn(db, user)
    if isinstance(result, dict):
        return {"scenario": name, **result}
    alerts = [a for a in result if a is not None]
    return {"scenario": name, "alert_ids": [a.id for a in alerts], "alerts": [a.title for a in alerts]}
