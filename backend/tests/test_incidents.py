from sqlalchemy import select

from app.models import Alert, User
from app.services.alerts import detect


def _alerts(db):
    a1 = detect(db, "cpu_threshold", title="CPU high", description="d", resource_type="host", resource_name="h1")
    a2 = detect(db, "container_unhealthy", title="web unhealthy", description="d", resource_type="container",
                resource_name="web", severity="critical")
    return a1, a2


def _user_id(client, admin, name):
    return next(u["id"] for u in client.get("/api/users", headers=admin).json()["items"] if u["username"] == name)


def _create(client, admin, db, **extra):
    a1, a2 = _alerts(db)
    r = client.post("/api/incidents", json={"title": "Web tier degradation", "alert_ids": [a1.id, a2.id], **extra}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_from_alerts_inherits_severity_and_builds_timeline(client, admin, db):
    inc = _create(client, admin, db)
    assert inc["reference"].startswith("INC-") and inc["severity"] == "critical" and inc["status"] == "detected"
    assert len(inc["alerts"]) == 2
    assert [e["event_type"] for e in inc["timeline"]] == ["created", "alert_linked", "alert_linked"]


def test_create_validation(client, admin, db):
    assert client.post("/api/incidents", json={"title": "No severity"}, headers=admin).status_code == 422
    assert client.post("/api/incidents", json={"title": "Bad alert", "alert_ids": [999]}, headers=admin).status_code == 422
    r = client.post("/api/incidents", json={"title": "Manual", "severity": "low"}, headers=admin)
    assert r.status_code == 201 and r.json()["severity"] == "low"


def test_lifecycle_stages_and_timestamps(client, admin, db):
    inc = _create(client, admin, db)
    iid = inc["id"]
    r = client.post(f"/api/incidents/{iid}/status", json={"status": "acknowledged"}, headers=admin)
    assert r.json()["status"] == "acknowledged" and r.json()["acknowledged_at"]
    r = client.post(f"/api/incidents/{iid}/status", json={"status": "investigating", "note": "checking logs"}, headers=admin)
    assert r.json()["investigation_started_at"]
    # going backwards is not allowed
    assert client.post(f"/api/incidents/{iid}/status", json={"status": "detected"}, headers=admin).status_code == 409
    # resolving requires a summary
    assert client.post(f"/api/incidents/{iid}/status", json={"status": "resolved"}, headers=admin).status_code == 409
    r = client.post(f"/api/incidents/{iid}/status", json={"status": "resolved", "resolution_summary": "Restarted service"}, headers=admin)
    body = r.json()
    assert body["status"] == "resolved" and body["resolved_at"] and body["resolution_summary"] == "Restarted service"
    # linked alerts are resolved with the incident
    assert all(a["status"] == "resolved" for a in body["alerts"])
    # reopen
    r = client.post(f"/api/incidents/{iid}/status", json={"status": "investigating"}, headers=admin)
    assert r.json()["status"] == "investigating" and r.json()["resolved_at"] is None
    types = [e["event_type"] for e in r.json()["timeline"]]
    assert types.count("status_changed") == 3 and types[-1] == "reopened"


def test_skipping_forward_sets_earlier_timestamps(client, admin, db):
    inc = _create(client, admin, db)
    r = client.post(f"/api/incidents/{inc['id']}/status", json={"status": "investigating"}, headers=admin).json()
    assert r["acknowledged_at"] and r["investigation_started_at"]


def test_notes_and_link_alerts(client, admin, db):
    inc = _create(client, admin, db)
    r = client.post(f"/api/incidents/{inc['id']}/notes", json={"message": "Suspect memory leak"}, headers=admin)
    assert r.status_code == 201 and r.json()["event_type"] == "note"
    assert client.post(f"/api/incidents/{inc['id']}/notes", json={"message": ""}, headers=admin).status_code == 422
    a3 = detect(db, "disk_threshold", title="disk", description="d", resource_type="host", resource_name="h9")
    r = client.post(f"/api/incidents/{inc['id']}/alerts", json={"alert_ids": [a3.id]}, headers=admin)
    assert len(r.json()["alerts"]) == 3
    assert client.get(f"/api/incidents?alert_id={a3.id}", headers=admin).json()["total"] == 1


def test_update_severity_and_assignment_notifies_assignee(client, admin, user, db):
    inc = _create(client, admin, db)
    alice = _user_id(client, admin, "alice")
    r = client.patch(f"/api/incidents/{inc['id']}", json={"assignee_id": alice, "root_cause": "Bad deploy", "severity": "high"},
                     headers=admin)
    assert r.json()["assignee_id"] == alice and r.json()["root_cause"] == "Bad deploy" and r.json()["severity"] == "high"
    notes = client.get("/api/notifications?category=incident", headers=user).json()["items"]
    assert notes and "assigned to you" in notes[0]["title"]


def test_rbac_for_regular_users(client, admin, user, db):
    inc = _create(client, admin, db)
    iid = inc["id"]
    # not assigned -> invisible
    assert client.get(f"/api/incidents/{iid}", headers=user).status_code == 404
    assert client.get("/api/incidents", headers=user).json()["total"] == 0
    assert client.post("/api/incidents", json={"title": "x", "severity": "low"}, headers=user).status_code == 403
    client.patch(f"/api/incidents/{iid}", json={"assignee_id": _user_id(client, admin, "alice")}, headers=admin)
    # assignee can progress, add notes and record manual actions...
    assert client.post(f"/api/incidents/{iid}/status", json={"status": "acknowledged"}, headers=user).status_code == 200
    assert client.post(f"/api/incidents/{iid}/notes", json={"message": "on it"}, headers=user).status_code == 201
    r = client.post(f"/api/incidents/{iid}/actions", json={"action_type": "manual", "description": "Called vendor"}, headers=user)
    assert r.status_code == 201 and r.json()["mode"] == "recorded"
    # ...but cannot execute actions, reassign or change severity
    assert client.post(f"/api/incidents/{iid}/actions", json={"action_type": "user_unlock", "target": "admin"},
                       headers=user).status_code == 403
    assert client.patch(f"/api/incidents/{iid}", json={"severity": "low"}, headers=user).status_code == 403


def test_executed_actions_use_real_adapters(client, admin, user, db):
    client.get("/api/containers?refresh=true", headers=admin)
    inc = _create(client, admin, db)
    iid = inc["id"]
    r = client.post(f"/api/incidents/{iid}/actions", json={"action_type": "container_stop", "target": "demo-web"}, headers=admin)
    assert r.status_code == 201 and r.json()["status"] == "completed" and r.json()["mode"] == "executed"
    assert next(c for c in client.get("/api/containers", headers=admin).json()["items"] if c["name"] == "demo-web")["status"] == "exited"
    # failures are recorded, not hidden
    r = client.post(f"/api/incidents/{iid}/actions", json={"action_type": "container_restart", "target": "does-not-exist"}, headers=admin)
    assert r.status_code == 201 and r.json()["status"] == "failed" and "not found" in r.json()["result"]
    # account containment
    r = client.post(f"/api/incidents/{iid}/actions", json={"action_type": "user_disable", "target": "alice"}, headers=admin)
    assert r.json()["status"] == "completed"
    db.expire_all()
    assert db.scalar(select(User).where(User.username == "alice")).is_active is False
    assert client.get("/api/auth/me", headers=user).status_code == 401
    r = client.post(f"/api/incidents/{iid}/actions", json={"action_type": "user_disable", "target": "admin"}, headers=admin)
    assert r.json()["status"] == "failed"  # cannot disable yourself
    # validation
    assert client.post(f"/api/incidents/{iid}/actions", json={"action_type": "manual"}, headers=admin).status_code == 422
    assert client.post(f"/api/incidents/{iid}/actions", json={"action_type": "rm_rf"}, headers=admin).status_code == 422
    detail = client.get(f"/api/incidents/{iid}", headers=admin).json()
    assert len(detail["actions"]) == 4 and sum(e["event_type"] == "action" for e in detail["timeline"]) == 4
    actions = [a["action"] for a in client.get("/api/activity?action=incident.action", headers=admin).json()["items"]]
    assert "incident.action.container_stop" in actions


def test_no_actions_on_resolved_incident(client, admin, db):
    inc = _create(client, admin, db)
    client.post(f"/api/incidents/{inc['id']}/status", json={"status": "resolved", "resolution_summary": "done"}, headers=admin)
    r = client.post(f"/api/incidents/{inc['id']}/actions", json={"action_type": "manual", "description": "x"}, headers=admin)
    assert r.status_code == 409


def test_list_filters_and_stats(client, admin, db):
    inc = _create(client, admin, db)
    client.post("/api/incidents", json={"title": "Low thing", "severity": "low"}, headers=admin)
    assert client.get("/api/incidents?severity=low", headers=admin).json()["total"] == 1
    assert client.get("/api/incidents?q=Web", headers=admin).json()["total"] == 1
    client.post(f"/api/incidents/{inc['id']}/status", json={"status": "resolved", "resolution_summary": "ok"}, headers=admin)
    assert client.get("/api/incidents?status=open", headers=admin).json()["total"] == 1
    s = client.get("/api/incidents/stats", headers=admin).json()
    assert s["total"] == 2 and s["by_status"]["resolved"] == 1 and s["mean_time_to_resolve_minutes"] is not None
    assert s["open_by_severity"]["low"] == 1


def test_alert_deletion_cascade_safe(db, client, admin):
    inc = _create(client, admin, db)
    a = db.get(Alert, inc["alerts"][0]["id"])
    db.delete(a)
    db.commit()
    assert len(client.get(f"/api/incidents/{inc['id']}", headers=admin).json()["alerts"]) == 1
