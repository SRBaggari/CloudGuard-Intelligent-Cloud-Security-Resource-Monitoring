import pytest
from sqlalchemy import select

from app.models import Alert, Container, Device, SecurityEvent, SystemMetric, User
from app.services.alerts import detect


def _seed(client, admin):
    r = client.post("/api/demo/seed", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def test_seed_is_admin_only_idempotent_and_labelled(client, admin, user, db):
    assert client.post("/api/demo/seed", headers=user).status_code == 403
    st = _seed(client, admin)
    assert st["active"] and st["containers"] == 5 and st["vms"] == 2 and st["metrics"] == 432
    assert _seed(client, admin)["metrics"] == 432  # idempotent
    assert all(c.is_demo and c.name.startswith("demo") for c in db.scalars(select(Container)).all())
    dev = db.scalar(select(Device).where(Device.is_demo.is_(True)))
    assert "DEMO" in dev.name and dev.hostname.endswith(".demo")
    listing = client.get("/api/demo", headers=user).json()
    assert listing["active"] and {s["key"] for s in listing["scenarios"]} >= {"cpu_spike", "incident"}


def test_scenarios_require_environment(client, admin):
    assert client.post("/api/demo/scenarios/cpu_spike", headers=admin).status_code == 409
    assert client.post("/api/demo/scenarios/nope", headers=admin).status_code == 404


@pytest.mark.parametrize("name,rule", [
    ("cpu_spike", "cpu_threshold"), ("container_crash", "container_unexpected_exit"),
    ("container_unhealthy", "container_unhealthy"), ("brute_force", "auth_bruteforce"),
    ("file_tamper", "fim_change"), ("vm_abort", "vm_unexpected_stop"), ("anomaly", "ml_anomaly"),
])
def test_each_scenario_raises_a_labelled_demo_alert(client, admin, db, name, rule):
    _seed(client, admin)
    r = client.post(f"/api/demo/scenarios/{name}", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["alert_ids"], r.json()
    a = db.get(Alert, r.json()["alert_ids"][0])
    assert a.is_demo and a.fingerprint.startswith(f"demo:{rule}:")
    # repeatable
    assert client.post(f"/api/demo/scenarios/{name}", headers=admin).status_code == 200


def test_cpu_spike_goes_through_real_threshold_rule(client, admin, db):
    _seed(client, admin)
    rules = client.get("/api/security/rules", headers=admin).json()
    cpu = next(r for r in rules if r["key"] == "cpu_threshold")
    client.patch(f"/api/security/rules/{cpu['id']}", json={"enabled": False}, headers=admin)
    # with the real rule disabled, the scenario produces no alert - proof it is not hard-coded
    assert client.post("/api/demo/scenarios/cpu_spike", headers=admin).json()["alert_ids"] == []


def test_demo_data_is_excluded_from_real_views(client, admin, db):
    real = detect(db, "disk_threshold", title="real disk", description="d", resource_type="host", resource_name="real-host")
    _seed(client, admin)
    for name in ("cpu_spike", "container_crash", "brute_force"):
        client.post(f"/api/demo/scenarios/{name}", headers=admin)
    alerts = client.get("/api/security/alerts", headers=admin).json()
    assert [a["id"] for a in alerts["items"]] == [real.id]
    demo_only = client.get("/api/security/alerts?demo_only=true", headers=admin).json()
    assert demo_only["total"] >= 3 and all(a["is_demo"] for a in demo_only["items"])
    assert client.get("/api/security/alerts?include_demo=true", headers=admin).json()["total"] == demo_only["total"] + 1
    assert sum(client.get("/api/security/alerts/stats", headers=admin).json()["by_severity"].values()) == 1
    events = client.get("/api/security/events", headers=admin).json()["items"]
    assert not any("[Sample]" in e["message"] for e in events)
    real_ids = [c["container_id"] for c in client.get("/api/containers?refresh=true", headers=admin).json()["items"]]
    assert real_ids and not any(cid.startswith("demo") for cid in real_ids)  # only the (mock) Docker engine's containers
    summary = client.get("/api/dashboard/summary", headers=admin).json()
    assert summary["alerts"]["active"] == 1 and summary["devices"]["hosts"] == 1
    assert client.get("/api/analytics/overview?days=1", headers=admin).json()["total_alerts"] == 1
    assert [d["hostname"] for d in client.get("/api/monitoring/devices", headers=admin).json()] != []
    assert all(not d["hostname"].endswith(".demo") for d in client.get("/api/monitoring/devices", headers=admin).json())


def test_demo_resources_are_never_actionable(client, admin, db):
    _seed(client, admin)
    demo_c = db.scalar(select(Container).where(Container.is_demo.is_(True)))
    assert client.post(f"/api/containers/{demo_c.container_id}/stop", headers=admin).status_code in (404, 422)
    assert client.post("/api/vms/de000000-0000-4000-8000-000000000001/stop", headers=admin).status_code == 404


def test_real_docker_sync_leaves_demo_containers_alone(client, admin, db):
    _seed(client, admin)
    client.get("/api/containers?refresh=true", headers=admin)
    db.expire_all()
    assert {c.status for c in db.scalars(select(Container).where(Container.is_demo.is_(True))).all()} <= {"running", "exited"}


def test_incident_walkthrough_and_demo_topology_and_capacity(client, admin, db):
    _seed(client, admin)
    r = client.post("/api/demo/scenarios/incident", headers=admin).json()
    inc = client.get(f"/api/incidents/{r['incident_id']}", headers=admin).json()
    assert inc["is_demo"] and inc["status"] == "acknowledged" and any(e["event_type"] == "note" for e in inc["timeline"])
    assert client.get("/api/incidents", headers=admin).json()["total"] == 0  # real list excludes demo incidents
    assert client.get("/api/incidents?include_demo=true", headers=admin).json()["total"] == 1
    topo = client.get("/api/topology?include_demo=true", headers=admin).json()
    assert topo["demo"] and sum(n["type"] == "container" for n in topo["nodes"]) == 5
    assert {n["label"] for n in topo["nodes"] if n["type"] == "network"} == {"demo-frontend-net", "demo-backend-net"}
    real_topo = client.get("/api/topology", headers=admin).json()
    assert not any(n["label"].startswith("demo-") and n["type"] == "network" for n in real_topo["nodes"])
    cap = client.get("/api/capacity?demo=true&lookback_days=7&horizon_days=60", headers=admin).json()
    assert cap["status"] == "ready" and cap["demo"] and "DEMO" in cap["device"]
    disk = next(m for m in cap["metrics"] if m["metric"] == "disk_percent")
    assert disk["trend"]["slope_per_day"] == pytest.approx(1.3, abs=0.1)
    assert disk["estimate"]["days_to_warning"] is not None


def test_notifications_for_demo_alerts_are_labelled(client, admin):
    _seed(client, admin)
    client.post("/api/demo/scenarios/file_tamper", headers=admin)
    titles = [n["title"] for n in client.get("/api/notifications", headers=admin).json()["items"]]
    assert titles and all(t.startswith("[DEMO]") for t in titles)


def test_reset_removes_only_demo_data(client, admin, db):
    real = detect(db, "disk_threshold", title="real disk", description="d", resource_type="host", resource_name="real-host")
    from app.monitoring.service import collect_and_store
    collect_and_store(db)
    _seed(client, admin)
    client.post("/api/demo/scenarios/incident", headers=admin)
    st = client.post("/api/demo/reset", headers=admin).json()
    assert not st["active"] and st["alerts"] == st["incidents"] == st["containers"] == st["metrics"] == 0
    db.expire_all()
    assert db.get(Alert, real.id) is not None
    assert db.scalar(select(SystemMetric).limit(1)) is not None  # real metrics untouched
    assert db.scalar(select(SecurityEvent).where(SecurityEvent.is_demo.is_(True))) is None
    assert db.scalar(select(User).where(User.username == "admin")).is_active
    acts = [a["action"] for a in client.get("/api/activity?action=demo.", headers=admin).json()["items"]]
    assert {"demo.seeded", "demo.scenario", "demo.reset"} <= set(acts)
