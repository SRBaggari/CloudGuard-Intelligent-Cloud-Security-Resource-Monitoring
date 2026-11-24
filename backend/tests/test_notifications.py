from sqlalchemy import select

from app.models import Notification
from app.services.alerts import detect


def _cpu_alert(db, host="h1", severity=None):
    return detect(db, "cpu_threshold", title=f"CPU high on {host}", description="cpu", resource_type="host",
                  resource_name=host, severity=severity)


def test_new_alert_notifies_every_active_user(client, admin, user, db):
    _cpu_alert(db)
    for headers in (admin, user):
        body = client.get("/api/notifications", headers=headers).json()
        assert body["total"] == 1 and body["unread"] == 1
        n = body["items"][0]
        assert n["category"] == "alert" and n["severity"] == "high" and n["link"].startswith("/alerts?id=")


def test_repeated_detection_does_not_duplicate_notifications(client, admin, db):
    for _ in range(4):
        _cpu_alert(db)
    assert client.get("/api/notifications", headers=admin).json()["total"] == 1


def test_escalation_resurfaces_existing_notification(client, admin, db):
    _cpu_alert(db)
    nid = client.get("/api/notifications", headers=admin).json()["items"][0]["id"]
    client.post(f"/api/notifications/{nid}/read", headers=admin)
    assert client.get("/api/notifications/unread-count", headers=admin).json()["unread"] == 0
    _cpu_alert(db, severity="critical")
    body = client.get("/api/notifications", headers=admin).json()
    assert body["total"] == 1 and body["unread"] == 1
    assert body["items"][0]["severity"] == "critical" and body["items"][0]["title"].startswith("Escalated:")


def test_severity_preference_filters_notifications(client, admin, db):
    assert client.put("/api/notifications/preferences", json={"min_severity": "critical"}, headers=admin).status_code == 200
    assert client.get("/api/notifications/preferences", headers=admin).json() == {"min_severity": "critical"}
    _cpu_alert(db)  # high < critical
    assert client.get("/api/notifications", headers=admin).json()["total"] == 0
    _cpu_alert(db, host="h2", severity="critical")
    assert client.get("/api/notifications", headers=admin).json()["total"] == 1
    assert client.put("/api/notifications/preferences", json={"min_severity": "bogus"}, headers=admin).status_code == 422


def test_mark_read_only_own_and_read_all(client, admin, user, db):
    _cpu_alert(db, "a")
    _cpu_alert(db, "b")
    admin_items = client.get("/api/notifications", headers=admin).json()["items"]
    # another user's notification is invisible
    assert client.post(f"/api/notifications/{admin_items[0]['id']}/read", headers=user).status_code == 404
    r = client.post(f"/api/notifications/{admin_items[0]['id']}/read", headers=admin)
    assert r.status_code == 200 and r.json()["is_read"] and r.json()["read_at"]
    assert client.get("/api/notifications?unread_only=true", headers=admin).json()["total"] == 1
    assert "1 notification" in client.post("/api/notifications/read-all", headers=admin).json()["detail"]
    assert client.get("/api/notifications/unread-count", headers=admin).json()["unread"] == 0
    # user's notifications are untouched
    assert client.get("/api/notifications/unread-count", headers=user).json()["unread"] == 2


def test_filters_and_history_retained(client, admin, db):
    _cpu_alert(db)
    detect(db, "container_unhealthy", title="web unhealthy", description="d", resource_type="container", resource_name="web")
    client.post("/api/notifications/read-all", headers=admin)
    assert client.get("/api/notifications", headers=admin).json()["total"] == 2  # history kept after reading
    assert client.get("/api/notifications?severity=high&category=alert", headers=admin).json()["total"] == 2
    assert client.get("/api/notifications?category=incident", headers=admin).json()["total"] == 0
    assert client.get("/api/notifications?severity=nope", headers=admin).status_code == 422


def test_inactive_users_not_notified(client, admin, user, db):
    alice = next(u for u in client.get("/api/users", headers=admin).json()["items"] if u["username"] == "alice")
    client.patch(f"/api/users/{alice['id']}", json={"is_active": False}, headers=admin)
    _cpu_alert(db)
    assert db.scalars(select(Notification).where(Notification.user_id == alice["id"])).all() == []


def test_notifications_require_auth(client):
    assert client.get("/api/notifications").status_code == 401


def test_personal_websocket_delivers_only_own_notifications(client, admin, db):
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/notifications?token=bad") as ws:
            ws.receive_json()
    token = admin["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/notifications?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        _cpu_alert(db, "ws-host")
        msg = ws.receive_json()
        assert msg["type"] == "notification.created" and "ws-host" in msg["notification"]["title"]
