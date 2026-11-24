import time

from sqlalchemy import select

from app.models import Alert, SystemMetric
from app.monitoring.collector import SystemCollector
from app.monitoring.service import collect_and_store, health_status
from app.services import settings_service
from tests.conftest import insert_metrics


def test_collector_returns_real_values():
    c = SystemCollector(use_process_worker=False)
    c.collect()
    time.sleep(0.3)
    m = c.collect()
    assert 0 <= m["cpu_percent"] <= 100
    assert 0 < m["memory_percent"] <= 100 and m["memory_total"] > 0
    assert 0 < m["disk_percent"] <= 100 and m["disk_total"] > 0
    assert m["process_count"] > 0
    assert m["net_send_rate"] >= 0 and m["net_recv_rate"] >= 0
    info = c.system_info()
    assert info["uptime_seconds"] > 0 and info["cpu_logical_cores"] >= 1


def test_process_list_in_process_and_interfaces():
    c = SystemCollector(use_process_worker=False)
    procs = c.processes(limit=5)
    assert 0 < len(procs) <= 5 and all("pid" in p and p["pid"] != 0 for p in procs)
    assert {"name", "cpu_percent", "memory_percent", "memory_rss", "username"} <= procs[0].keys()
    by_mem = c.processes(limit=5, sort="memory")
    assert by_mem == sorted(by_mem, key=lambda p: p["memory_rss"], reverse=True)
    assert c.processes(limit=5) is procs  # cached snapshot
    assert isinstance(c.network_interfaces(), list)


def test_process_scan_runs_in_worker_process():
    c = SystemCollector(use_process_worker=True)
    try:
        procs = c.processes(limit=3)
        assert len(procs) == 3 and c._pool is not None  # scanned out-of-process, no fallback
    finally:
        c.shutdown()


def test_collect_and_store_persists(db):
    m = collect_and_store(db)
    assert db.get(SystemMetric, m.id) is not None


def test_system_and_history_endpoints(client, admin, db):
    r = client.get("/api/monitoring/system", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["metric"]["memory_total"] > 0 and body["health"]["status"] in ("healthy", "degraded", "critical")
    insert_metrics(db, 30)
    hist = client.get("/api/monitoring/history?minutes=60", headers=admin).json()
    assert len(hist) >= 30
    hist = client.get("/api/monitoring/history?minutes=60&max_points=10", headers=admin).json()
    assert len(hist) <= 16


def test_network_endpoint_hides_connections_from_users(client, admin, user):
    assert client.get("/api/monitoring/network", headers=user).json()["connections"] is None
    assert client.get("/api/monitoring/network", headers=admin).json()["connections"] is not None


def test_cpu_threshold_rule_triggers_after_consecutive_samples(db):
    from app.security_engine import engine
    rows = insert_metrics(db, 2, cpu=97.0)
    engine.evaluate_metric(db, rows[-1], "host1", rows[0])
    assert db.scalar(select(Alert).where(Alert.fingerprint.like("cpu_threshold%"))) is None  # needs 3
    rows = insert_metrics(db, 1, cpu=97.0, start_minutes_ago=0.001)
    engine.evaluate_metric(db, rows[-1], "host1", None)
    alert = db.scalar(select(Alert).where(Alert.fingerprint.like("cpu_threshold%")))
    assert alert is not None and alert.severity == "critical"


def test_alert_deduplication(db):
    from app.security_engine import engine
    rows = insert_metrics(db, 3, mem=90.0)
    engine.evaluate_metric(db, rows[-1], "host1", None)
    engine.evaluate_metric(db, rows[-1], "host1", None)
    alerts = db.scalars(select(Alert).where(Alert.fingerprint.like("memory_threshold%"))).all()
    assert len(alerts) == 1 and alerts[0].occurrences == 2 and alerts[0].severity == "high"
    rows = insert_metrics(db, 3, mem=91.0, start_minutes_ago=0.001)
    engine.evaluate_metric(db, rows[-1], "host1", None)
    db.refresh(alerts[0])
    assert alerts[0].occurrences == 3 and "91.0%" in alerts[0].title  # title tracks latest value


def test_disabled_rule_does_not_alert(client, admin, db):
    rules = client.get("/api/security/rules", headers=admin).json()
    cpu = next(r for r in rules if r["key"] == "cpu_threshold")
    client.patch(f"/api/security/rules/{cpu['id']}", json={"enabled": False}, headers=admin)
    from app.security_engine import engine
    rows = insert_metrics(db, 3, cpu=99.0)
    db.expire_all()
    engine.evaluate_metric(db, rows[-1], "host1", None)
    assert db.scalar(select(Alert).where(Alert.fingerprint.like("cpu_threshold%"))) is None


def test_process_spike_and_watchlist(db):
    from app.security_engine import engine
    a, b = insert_metrics(db, 2)
    b.process_count = a.process_count + 100
    db.commit()
    engine.evaluate_metric(db, b, "host1", a)
    assert db.scalar(select(Alert).where(Alert.fingerprint.like("process_spike%"))) is not None
    engine.evaluate_processes(db, {"python.exe", "evil-miner.exe"}, ["evil-miner.exe"], "host1")
    assert db.scalar(select(Alert).where(Alert.fingerprint.like("process_watchlist%"))) is not None


def test_health_status_levels():
    assert health_status(10, 20, 30)["status"] == "healthy"
    assert health_status(85, 20, 30)["status"] == "degraded"
    assert health_status(99, 20, 30)["status"] == "critical"


def test_settings_update(client, admin, db):
    s = client.get("/api/settings", headers=admin).json()
    s["monitoring"]["interval_seconds"] = 10
    s["monitoring"]["process_watchlist"] = [" nc.exe ", "nc.exe", ""]
    r = client.put("/api/settings", json=s, headers=admin)
    assert r.status_code == 200
    assert r.json()["monitoring"]["interval_seconds"] == 10
    assert r.json()["monitoring"]["process_watchlist"] == ["nc.exe"]
    assert settings_service.get_section(db, "monitoring")["interval_seconds"] == 10
    s["monitoring"]["interval_seconds"] = 0
    assert client.put("/api/settings", json=s, headers=admin).status_code == 422


def test_dashboard_summary(client, admin):
    client.get("/api/containers?refresh=true", headers=admin)
    client.get("/api/vms?refresh=true", headers=admin)
    s = client.get("/api/dashboard/summary", headers=admin).json()
    assert s["containers"]["available"] and s["containers"]["mode"] == "mock"
    assert s["containers"]["running"] == 2 and s["vms"]["total"] == 2
    assert s["devices"]["total"] == 1 + 2 + 3
    assert "health" in s and "threats" in s


def test_prometheus_endpoint(client, db):
    collect_and_store(db)
    r = client.get("/metrics")
    assert r.status_code == 200 and "cloudguard_host_cpu_percent" in r.text
