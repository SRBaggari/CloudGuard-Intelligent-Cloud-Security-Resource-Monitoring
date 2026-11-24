from app.services.alerts import detect


def _make_alerts(db):
    detect(db, "cpu_threshold", title="CPU high", description="cpu", resource_type="host", resource_name="h1")
    detect(db, "container_unhealthy", title="Container web unhealthy", description="unhealthy",
           resource_type="container", resource_name="web")
    detect(db, "fim_change", title="File changed", description="changed", resource_type="directory",
           resource_name="/srv/app", severity="high")


def test_alert_listing_filters_and_search(client, admin, db):
    _make_alerts(db)
    assert client.get("/api/security/alerts", headers=admin).json()["total"] == 3
    assert client.get("/api/security/alerts?category=container", headers=admin).json()["total"] == 1
    assert client.get("/api/security/alerts?severity=high", headers=admin).json()["total"] == 3
    assert client.get("/api/security/alerts?q=web", headers=admin).json()["total"] == 1
    assert client.get("/api/security/alerts?page=1&page_size=2", headers=admin).json()["items"].__len__() == 2
    assert client.get("/api/security/alerts?severity=bogus", headers=admin).status_code == 422


def test_alert_lifecycle(client, admin, db):
    _make_alerts(db)
    aid = client.get("/api/security/alerts", headers=admin).json()["items"][0]["id"]
    r = client.post(f"/api/security/alerts/{aid}/acknowledge", json={"note": "looking"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "acknowledged" and r.json()["acknowledged_at"]
    assert client.post(f"/api/security/alerts/{aid}/acknowledge", headers=admin).status_code == 409
    r = client.post(f"/api/security/alerts/{aid}/resolve", json={"note": "fixed"}, headers=admin)
    assert r.json()["status"] == "resolved" and r.json()["resolution_note"] == "fixed"
    assert client.post(f"/api/security/alerts/{aid}/resolve", headers=admin).status_code == 409
    assert client.get("/api/security/alerts?status=active", headers=admin).json()["total"] == 2
    stats = client.get("/api/security/alerts/stats", headers=admin).json()
    assert stats["by_status"]["resolved"] == 1
    assert client.post("/api/security/alerts/9999/resolve", headers=admin).status_code == 404


def test_resolved_alert_is_not_reused(db):
    a1 = detect(db, "cpu_threshold", title="CPU", description="d", resource_type="host", resource_name="h1")
    a1.status = "resolved"
    db.commit()
    a2 = detect(db, "cpu_threshold", title="CPU", description="d", resource_type="host", resource_name="h1")
    assert a2.id != a1.id


def test_security_events_recorded(client, admin, db):
    client.post("/api/auth/login", json={"username": "nobody", "password": "x1234567"})
    events = client.get("/api/security/events?event_type=login_failed", headers=admin).json()
    assert events["total"] == 1 and "nobody" in events["items"][0]["message"]


def test_rule_update_validation(client, admin):
    rules = client.get("/api/security/rules", headers=admin).json()
    cpu = next(r for r in rules if r["key"] == "cpu_threshold")
    assert "85" in cpu["condition"]
    r = client.patch(f"/api/security/rules/{cpu['id']}", json={"params": {"warning": 70}, "severity": "medium"},
                     headers=admin)
    assert r.status_code == 200 and r.json()["params"]["warning"] == 70 and "70" in r.json()["condition"]
    assert client.patch(f"/api/security/rules/{cpu['id']}", json={"params": {"evil": 1}}, headers=admin).status_code == 422
    assert client.patch(f"/api/security/rules/{cpu['id']}", json={"params": {"warning": "x"}}, headers=admin).status_code == 422
    assert client.patch(f"/api/security/rules/{cpu['id']}", json={"params": {"critical": 10}}, headers=admin).status_code == 422


def test_websocket_requires_token_and_receives_alerts(client, admin, db):
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/alerts?token=bad") as ws:
            ws.receive_json()
    token = admin["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/alerts?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_text("ping")
        assert ws.receive_json()["type"] == "pong"
        detect(db, "cpu_threshold", title="CPU", description="d", resource_type="host", resource_name="ws-host")
        msg = ws.receive_json()
        assert msg["type"] == "alert.created" and msg["alert"]["resource_name"] == "ws-host"
