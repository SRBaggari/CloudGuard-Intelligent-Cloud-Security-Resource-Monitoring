import pytest

from tests.conftest import insert_metrics

STEP = 600  # one sample every 10 minutes


def _report(client, headers, **params):
    r = client.get("/api/capacity", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _metric(rep, name):
    return next(m for m in rep["metrics"] if m["metric"] == name)


def test_insufficient_history_is_explained_not_forecast(client, admin, db):
    insert_metrics(db, 10, step_seconds=60)
    rep = _report(client, admin)
    assert rep["status"] == "insufficient_data" and rep["metrics"] == []
    assert "More monitoring history is needed" in rep["message"]


def test_linear_disk_growth_is_projected_with_eta(client, admin, db):
    # 2 days of history: disk grows exactly 1 percentage point per day from 60%
    n = 2 * 24 * 6
    rows = insert_metrics(db, n, step_seconds=STEP, cpu=20.0, mem=50.0, disk=60.0)
    for i, r in enumerate(rows):
        r.disk_percent = 60.0 + i * STEP / 86400
    db.commit()
    rep = _report(client, admin, lookback_days=3, horizon_days=60)
    assert rep["status"] == "ready" and rep["bucket_minutes"] == 60
    disk = _metric(rep, "disk_percent")
    assert disk["trend"]["slope_per_day"] == pytest.approx(1.0, abs=0.02)
    assert disk["trend"]["r2"] > 0.99 and disk["trend"]["confidence"] in ("medium", "high")
    # warning threshold 90%: currently ~62% -> ~28 days
    assert disk["estimate"]["days_to_warning"] == pytest.approx(28, abs=1.5)
    assert disk["estimate"]["days_to_critical"] == pytest.approx(35, abs=1.5)
    assert disk["status"] == "approaching"
    assert f"in about {disk['estimate']['days_to_warning']:.0f} days" in disk["summary"]
    cap = disk["estimate"]["capacity"]
    assert cap["projected_used_bytes"] > cap["measured_used_bytes"]
    assert cap["required_total_bytes_to_stay_below_warning"] > cap["total_bytes"]
    # measured and estimated points are clearly labelled
    assert {p["kind"] for p in disk["history"]} == {"measured"}
    assert {p["kind"] for p in disk["forecast"]} == {"estimate"} and len(disk["forecast"]) == 60
    assert all(p["lower"] <= p["value"] <= p["upper"] <= 100 for p in disk["forecast"])


def test_flat_usage_is_stable_and_threshold_exceeded_detected(client, admin, db):
    insert_metrics(db, 40, step_seconds=STEP, cpu=10.0, mem=92.0, disk=50.0)
    rep = _report(client, admin, lookback_days=1)
    assert rep["bucket_minutes"] == 10
    cpu = _metric(rep, "cpu_percent")
    assert cpu["status"] == "stable" and cpu["estimate"]["days_to_warning"] is None
    mem = _metric(rep, "memory_percent")
    assert mem["status"] == "exceeding" and "above the warning threshold" in mem["summary"]
    net = _metric(rep, "net_recv_rate")
    assert net["unit"] == "bytes_per_second" and net["thresholds"]["warning"] == 50 * 1024 * 1024


def test_thresholds_follow_rule_configuration(client, admin, db):
    insert_metrics(db, 40, step_seconds=STEP, mem=75.0)
    rules = client.get("/api/security/rules", headers=admin).json()
    mem_rule = next(r for r in rules if r["key"] == "memory_threshold")
    client.patch(f"/api/security/rules/{mem_rule['id']}", json={"params": {"warning": 70}}, headers=admin)
    mem = _metric(_report(client, admin), "memory_percent")
    assert mem["thresholds"]["warning"] == 70 and mem["status"] == "exceeding"


def test_containers_near_limits_listed(client, admin, user, db):
    from app.docker_integration.adapter import get_docker_adapter
    a = get_docker_adapter()
    web = next(c for c in a.containers.values() if c["name"] == "demo-web")
    a.stats_map[web["id"]]["memory_percent"] = 80.0  # 80/90 = 0.89 of the limit
    client.get("/api/containers?refresh=true", headers=admin)
    insert_metrics(db, 40, step_seconds=STEP)
    rep = _report(client, admin)
    assert [c["name"] for c in rep["containers"]] == ["demo-web"]
    assert rep["containers"][0]["status"] == "approaching" and rep["containers"][0]["kind"] == "measured"
    assert _report(client, user)["containers"] == []  # not assigned to the regular user


def test_parameter_validation_and_auth(client, admin):
    assert client.get("/api/capacity").status_code == 401
    assert client.get("/api/capacity?lookback_days=0", headers=admin).status_code == 422
    assert client.get("/api/capacity?horizon_days=500", headers=admin).status_code == 422
