"""Incident response workflow.

Lifecycle: detected -> acknowledged -> investigating -> resolved (stages may be skipped forwards;
a resolved incident can be reopened to `investigating`). Every change is written to an immutable
timeline. Response actions are either *executed* through CloudGuard's existing, authorised
adapters (Docker, VirtualBox, account controls, FIM) or *recorded* as manual actions.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import utcnow
from app.models import Alert, Container, Incident, IncidentAction, IncidentEvent, MonitoredDirectory, RefreshToken, User, VirtualMachine
from app.services.alerts import SEVERITY_ORDER
from app.services.notifications import notify_user

ORDER = {"detected": 0, "acknowledged": 1, "investigating": 2, "resolved": 3}


class IncidentError(ValueError):
    """Business-rule violation (mapped to HTTP 409/422 by the API)."""


def add_event(db: Session, inc: Incident, event_type: str, message: str, user: User | None = None,
              details: dict[str, Any] | None = None) -> IncidentEvent:
    ev = IncidentEvent(incident_id=inc.id, event_type=event_type, message=message,
                       user_id=user.id if user else None, details=details or {})
    db.add(ev)
    return ev


def _notify_assignee(db: Session, inc: Incident, actor: User | None, key: str, title: str, message: str = "") -> None:
    if inc.assignee_id and (actor is None or inc.assignee_id != actor.id):
        notify_user(db, inc.assignee_id, category="incident", severity=inc.severity, title=title, message=message,
                    link=f"/incidents/{inc.id}", dedupe_key=f"incident:{inc.id}:{key}")


def _load_alerts(db: Session, alert_ids: list[int]) -> list[Alert]:
    ids = list(dict.fromkeys(alert_ids))
    alerts = db.scalars(select(Alert).where(Alert.id.in_(ids))).all() if ids else []
    missing = set(ids) - {a.id for a in alerts}
    if missing:
        raise IncidentError(f"Unknown alert id(s): {sorted(missing)}")
    return list(alerts)


def create_incident(db: Session, *, title: str, description: str, severity: str | None, category: str,
                    alert_ids: list[int], assignee_id: int | None, user: User) -> Incident:
    alerts = _load_alerts(db, alert_ids)
    if severity is None:
        if not alerts:
            raise IncidentError("Severity is required when no alerts are linked")
        severity = max((a.severity for a in alerts), key=lambda s: SEVERITY_ORDER[s])
    if assignee_id is not None and not db.get(User, assignee_id):
        raise IncidentError("Assignee not found")
    detected = min((a.created_at for a in alerts), default=None) or utcnow()
    inc = Incident(title=title, description=description, severity=severity, category=category,
                   assignee_id=assignee_id, created_by_id=user.id, detected_at=detected,
                   is_demo=bool(alerts) and all(a.is_demo for a in alerts))
    inc.alerts = alerts
    db.add(inc)
    db.flush()
    add_event(db, inc, "created", f"Incident created by {user.username}", user,
              {"severity": severity, "alerts": [a.id for a in alerts]})
    for a in alerts:
        add_event(db, inc, "alert_linked", f"Alert #{a.id} linked: {a.title}", user, {"alert_id": a.id})
    if assignee_id:
        add_event(db, inc, "assigned", f"Assigned to user #{assignee_id}", user, {"assignee_id": assignee_id})
    db.commit()
    db.refresh(inc)
    _notify_assignee(db, inc, user, f"assigned:{assignee_id}", f"{inc.reference} assigned to you: {inc.title}")
    return inc


def update_incident(db: Session, inc: Incident, changes: dict[str, Any], user: User) -> Incident:
    if "assignee_id" in changes and changes["assignee_id"] is not None and not db.get(User, changes["assignee_id"]):
        raise IncidentError("Assignee not found")
    for field in ("title", "description", "root_cause"):
        if changes.get(field) is not None and changes[field] != getattr(inc, field):
            setattr(inc, field, changes[field])
            add_event(db, inc, "updated", f"{field.replace('_', ' ').capitalize()} updated", user)
    if changes.get("severity") and changes["severity"] != inc.severity:
        add_event(db, inc, "severity_changed", f"Severity changed {inc.severity} → {changes['severity']}", user,
                  {"from": inc.severity, "to": changes["severity"]})
        inc.severity = changes["severity"]
    new_assignee = None if changes.get("unassign") else changes.get("assignee_id", inc.assignee_id)
    if new_assignee != inc.assignee_id:
        add_event(db, inc, "assigned", f"Assigned to user #{new_assignee}" if new_assignee else "Unassigned", user,
                  {"assignee_id": new_assignee})
        inc.assignee_id = new_assignee
        db.commit()
        _notify_assignee(db, inc, user, f"assigned:{new_assignee}", f"{inc.reference} assigned to you: {inc.title}")
    db.commit()
    db.refresh(inc)
    return inc


def change_status(db: Session, inc: Incident, new: str, user: User, note: str = "", resolution_summary: str = "") -> Incident:
    old = inc.status
    if new == old:
        raise IncidentError(f"Incident is already {old}")
    reopening = old == "resolved" and new == "investigating"
    if ORDER[new] < ORDER[old] and not reopening:
        raise IncidentError(f"Cannot move an incident from {old} back to {new}")
    if new == "resolved" and not (resolution_summary or inc.resolution_summary).strip():
        raise IncidentError("A resolution summary is required to resolve an incident")
    now = utcnow()
    if ORDER[new] >= 1 and inc.acknowledged_at is None:
        inc.acknowledged_at = now
    if ORDER[new] >= 2 and inc.investigation_started_at is None:
        inc.investigation_started_at = now
    if new == "resolved":
        inc.resolved_at = now
        inc.resolution_summary = resolution_summary or inc.resolution_summary
        # resolving the incident closes the alerts it contains
        for a in inc.alerts:
            if a.status != "resolved":
                a.status, a.resolved_at, a.resolved_by_id = "resolved", now, user.id
                a.acknowledged_at = a.acknowledged_at or now
                a.resolution_note = a.resolution_note or f"Resolved with {inc.reference}"
    if reopening:
        inc.resolved_at = None
    inc.status = new
    add_event(db, inc, "reopened" if reopening else "status_changed",
              f"Status changed {old} → {new}" + (f": {note}" if note else ""), user,
              {"from": old, "to": new, "note": note})
    db.commit()
    db.refresh(inc)
    _notify_assignee(db, inc, user, f"status:{new}:{int(now.timestamp())}", f"{inc.reference} is now {new}", note)
    return inc


def add_note(db: Session, inc: Incident, message: str, user: User) -> IncidentEvent:
    ev = add_event(db, inc, "note", message, user)
    inc.updated_at = utcnow()
    db.commit()
    db.refresh(ev)
    return ev


def link_alerts(db: Session, inc: Incident, alert_ids: list[int], user: User) -> Incident:
    current = {a.id for a in inc.alerts}
    for a in _load_alerts(db, alert_ids):
        if a.id in current:
            continue
        inc.alerts.append(a)
        add_event(db, inc, "alert_linked", f"Alert #{a.id} linked: {a.title}", user, {"alert_id": a.id})
        if SEVERITY_ORDER[a.severity] > SEVERITY_ORDER[inc.severity]:
            add_event(db, inc, "severity_changed", f"Severity raised {inc.severity} → {a.severity} by linked alert", user)
            inc.severity = a.severity
    db.commit()
    db.refresh(inc)
    return inc


# ---------------------------------------------------------------- response actions
def _container(db: Session, ref: str) -> Container:
    from app.docker_integration.adapter import validate_container_ref
    validate_container_ref(ref)
    conds = [Container.container_id == ref, Container.name == ref]
    if len(ref) >= 12:
        conds.append(Container.container_id.startswith(ref))
    row = db.scalar(select(Container).where(or_(*conds), Container.is_demo.is_(False)))
    if row is None:
        raise IncidentError(f"Container '{ref}' not found")
    return row


def _execute(db: Session, action_type: str, target: str, force: bool, user: User) -> str:
    """Run an authorised action and return a human-readable result. Raises on failure."""
    if action_type in ("container_stop", "container_restart"):
        from app.docker_integration.adapter import get_docker_adapter
        from app.docker_integration.service import sync_containers
        row = _container(db, target)
        row.expected_stop_at = utcnow()
        db.commit()
        get_docker_adapter().action(row.container_id, action_type.split("_")[1])
        sync_containers(db, with_stats=False)
        return f"Container '{row.name}' {action_type.split('_')[1]} requested"
    if action_type == "vm_stop":
        from app.virtualization.service import mark_expected_stop, sync_vms
        from app.virtualization.vbox import get_vbox_adapter, validate_uuid
        vm = db.scalar(select(VirtualMachine).where(VirtualMachine.uuid == validate_uuid(target), VirtualMachine.is_demo.is_(False)))
        if vm is None:
            raise IncidentError(f"VM '{target}' not found")
        mark_expected_stop(vm.uuid)
        get_vbox_adapter().stop(vm.uuid, force=force)
        sync_vms(db)
        return f"VM '{vm.name}' {'powered off' if force else 'ACPI shutdown requested'}"
    if action_type in ("user_disable", "user_revoke_sessions", "user_unlock"):
        target_user = db.scalar(select(User).where(or_(User.username == target, User.email == target.lower())))
        if target_user is None:
            raise IncidentError(f"User '{target}' not found")
        if action_type == "user_disable":
            if target_user.id == user.id:
                raise IncidentError("You cannot disable your own account")
            target_user.is_active = False
        if action_type in ("user_disable", "user_revoke_sessions"):
            db.execute(update(RefreshToken).where(RefreshToken.user_id == target_user.id).values(revoked=True))
        if action_type == "user_unlock":
            target_user.locked_until, target_user.failed_login_count = None, 0
        db.commit()
        return {"user_disable": "Account disabled and sessions revoked", "user_revoke_sessions": "All sessions revoked",
                "user_unlock": "Account unlocked"}[action_type] + f" for '{target_user.username}'"
    if action_type == "fim_rebaseline":
        from app.integrity.fim import create_baseline
        d = db.get(MonitoredDirectory, int(target)) if target.isdigit() else db.scalar(
            select(MonitoredDirectory).where(MonitoredDirectory.path == target))
        if d is None:
            raise IncidentError(f"Monitored directory '{target}' not found")
        n = create_baseline(db, d)
        return f"Baseline recreated for {d.path} ({n} files)"
    raise IncidentError(f"Unsupported action '{action_type}'")


def perform_action(db: Session, inc: Incident, action_type: str, target: str, description: str, force: bool,
                   user: User, ip: str = "") -> IncidentAction:
    if action_type == "manual":
        if not description.strip():
            raise IncidentError("Describe the manual action that was taken")
        mode, status, result = "recorded", "recorded", description.strip()
    else:
        if not target.strip():
            raise IncidentError("A target is required for this action")
        mode = "executed"
        try:
            result = _execute(db, action_type, target.strip(), force, user)
            status = "completed"
            if description.strip():
                result += f" — {description.strip()}"
        except Exception as e:  # failures are recorded, never hidden
            db.rollback()
            status, result = "failed", str(e)[:1000] or e.__class__.__name__
    act = IncidentAction(incident_id=inc.id, action_type=action_type, target=target.strip(), mode=mode,
                         status=status, result=result, performed_by_id=user.id)
    db.add(act)
    add_event(db, inc, "action", f"Response action {action_type} ({status}): {result}", user,
              {"action_type": action_type, "target": target, "status": status})
    db.commit()
    db.refresh(act)
    audit(db, f"incident.action.{action_type}", user.id, "incident", inc.id,
          {"target": target, "status": status, "mode": mode}, ip)
    return act
