"""Synchronise VirtualBox VMs into the database and detect unexpected shutdowns."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import ensure_aware, utcnow
from app.models import VirtualMachine
from app.security_engine import engine
from app.services.alerts import detect
from app.virtualization.vbox import VBoxError, VBoxUnavailable, get_vbox_adapter

STOPPED = {"poweroff", "aborted", "saved"}

# uuid -> time CloudGuard issued a stop, to avoid flagging our own actions
_expected_stops: dict[str, object] = {}


def mark_expected_stop(vm_uuid: str) -> None:
    _expected_stops[vm_uuid] = utcnow()


def sync_vms(db: Session) -> dict:
    adapter = get_vbox_adapter()
    st = adapter.status()
    if not st.get("available"):
        return {"available": False, "message": st.get("message"), "synced": 0}
    try:
        vms = adapter.list_vms()
    except (VBoxError, VBoxUnavailable) as e:
        return {"available": False, "message": str(e), "synced": 0}
    now = utcnow()
    for v in vms:
        row = db.scalar(select(VirtualMachine).where(VirtualMachine.uuid == v["uuid"], VirtualMachine.is_demo.is_(False)))
        prev = None
        if row is None:
            row = VirtualMachine(uuid=v["uuid"], name=v["name"])
            db.add(row)
        else:
            prev = row.state
        row.name, row.state, row.os_type = v["name"], v["state"], v["os_type"]
        row.memory_mb, row.cpus, row.config = v["memory_mb"], v["cpus"], v.get("config", {})
        row.last_seen_at = now
        db.commit()
        if prev and prev != row.state:
            audit(db, "vm.state_changed", resource_type="vm", resource_id=row.uuid,
                  details={"name": row.name, "from": prev, "to": row.state})
        if prev == "running" and row.state in STOPPED:
            exp = _expected_stops.pop(row.uuid, None)
            if exp and now - ensure_aware(exp) < timedelta(minutes=10):
                continue
            sev = "critical" if row.state == "aborted" else None
            detect(db, "vm_unexpected_stop", title=f"VM '{row.name}' stopped unexpectedly",
                   description=f"VirtualBox VM '{row.name}' changed from running to {row.state} without a CloudGuard action.",
                   resource_type="vm", resource_name=row.name, severity=sev, details={"state": row.state})
            engine.register_failure(db, "vm", row.name, f"state {row.state}")
    return {"available": True, "synced": len(vms)}
