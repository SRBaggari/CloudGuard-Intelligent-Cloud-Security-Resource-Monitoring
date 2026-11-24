import pytest
from sqlalchemy import select

from app.docker_integration.adapter import (
    MockDockerAdapter, RealDockerAdapter, get_docker_adapter, parse_stats, set_docker_adapter, validate_container_ref,
)
from app.docker_integration.service import sync_containers
from app.models import Alert, Container
from app.virtualization.service import sync_vms
from app.virtualization.vbox import (
    LIST_RE, MockVBoxAdapter, RealVBoxAdapter, VBoxError, get_vbox_adapter, parse_machinereadable, validate_uuid,
)

# ---------------------------------------------------------------- Docker


def test_container_listing_and_summary(client, admin):
    body = client.get("/api/containers?refresh=true", headers=admin).json()
    assert body["docker"]["mode"] == "mock"
    assert body["summary"] == {"total": 3, "running": 2, "stopped": 1, "unhealthy": 0}


def test_container_actions_and_logs(client, admin, db):
    items = client.get("/api/containers?refresh=true", headers=admin).json()["items"]
    web = next(c for c in items if c["name"] == "demo-web")
    r = client.post(f"/api/containers/{web['container_id'][:12]}/stop", headers=admin)
    assert r.status_code == 200 and r.json()["container"]["status"] == "exited"
    # a stop issued by CloudGuard must NOT be flagged as unexpected
    assert db.scalar(select(Alert).where(Alert.fingerprint.like("container_unexpected_exit%"))) is None
    assert client.post(f"/api/containers/{web['container_id']}/start", headers=admin).json()["container"]["status"] == "running"
    assert client.post(f"/api/containers/{web['container_id']}/restart", headers=admin).status_code == 200
    logs = client.get(f"/api/containers/{web['container_id']}/logs?tail=5", headers=admin).json()
    assert len(logs["logs"].splitlines()) == 5
    detail = client.get(f"/api/containers/{web['container_id']}", headers=admin).json()
    assert detail["details"]["image"] == "nginx:alpine" and "env_keys" in detail["details"]


def test_container_input_validation(client, admin):
    assert client.post("/api/containers/..%2F..%2Fetc/stop", headers=admin).status_code in (404, 422)
    assert client.post("/api/containers/bad;rm -rf/stop", headers=admin).status_code == 422
    assert client.get("/api/containers/doesnotexist/logs?tail=99999", headers=admin).status_code == 422
    with pytest.raises(ValueError):
        validate_container_ref("$(whoami)")


def test_unexpected_exit_restart_and_repeated_failures(db):
    adapter: MockDockerAdapter = get_docker_adapter()
    sync_containers(db)
    api = next(c for c in adapter.containers.values() if c["name"] == "demo-api")
    api["status"], api["exit_code"] = "exited", 137
    sync_containers(db)
    a = db.scalar(select(Alert).where(Alert.fingerprint.like("container_unexpected_exit%")))
    assert a is not None and "137" in a.description
    for _ in range(3):
        api["status"] = "running"
        api["restart_count"] += 1
        sync_containers(db)
    assert db.scalar(select(Alert).where(Alert.fingerprint.like("container_restart%"))).occurrences == 3
    assert db.scalar(select(Alert).where(Alert.fingerprint.like("service_failures%"))) is not None


def test_unhealthy_and_resource_detection(db):
    adapter: MockDockerAdapter = get_docker_adapter()
    sync_containers(db)
    web = next(c for c in adapter.containers.values() if c["name"] == "demo-web")
    web["health"] = "unhealthy"
    adapter.stats_map[web["id"]]["cpu_percent"] = 99.0
    sync_containers(db)
    assert db.scalar(select(Alert).where(Alert.fingerprint.like("container_unhealthy%"))) is not None
    assert db.scalar(select(Alert).where(Alert.fingerprint.like("container_resource%"))) is not None


def test_removed_containers_marked(db):
    adapter: MockDockerAdapter = get_docker_adapter()
    sync_containers(db)
    cid = next(iter(adapter.containers))
    del adapter.containers[cid]
    sync_containers(db)
    assert db.scalar(select(Container).where(Container.container_id == cid)).status == "removed"


def test_real_docker_adapter_degrades_gracefully(client, admin, db):
    real = RealDockerAdapter()
    st = real.status()
    assert "available" in st
    if not st["available"]:
        set_docker_adapter(real)
        assert "Docker" in st["message"]
        body = client.get("/api/containers?refresh=true", headers=admin).json()
        assert body["docker"]["available"] is False and body["items"] == []
        assert sync_containers(db)["available"] is False


def test_parse_docker_stats():
    stats = {
        "cpu_stats": {"cpu_usage": {"total_usage": 2_000}, "system_cpu_usage": 20_000, "online_cpus": 4},
        "precpu_stats": {"cpu_usage": {"total_usage": 1_000}, "system_cpu_usage": 10_000},
        "memory_stats": {"usage": 600, "limit": 1000, "stats": {"inactive_file": 100}},
        "networks": {"eth0": {"rx_bytes": 10, "tx_bytes": 5}, "eth1": {"rx_bytes": 1, "tx_bytes": 1}},
    }
    p = parse_stats(stats)
    assert p["cpu_percent"] == 40.0 and p["memory_percent"] == 50.0 and p["net_rx_bytes"] == 11


# ---------------------------------------------------------------- VirtualBox
UUID1 = "11111111-2222-3333-4444-555555555555"


def test_vm_list_and_actions(client, admin, db):
    body = client.get("/api/vms?refresh=true", headers=admin).json()
    assert body["virtualbox"]["mode"] == "mock" and body["summary"] == {"total": 2, "running": 1}
    r = client.post(f"/api/vms/{UUID1}/stop", headers=admin)
    assert r.status_code == 200 and r.json()["vm"]["state"] == "poweroff"
    assert db.scalar(select(Alert).where(Alert.fingerprint.like("vm_unexpected_stop%"))) is None
    assert client.post(f"/api/vms/{UUID1}/start", headers=admin).json()["vm"]["state"] == "running"
    assert client.get(f"/api/vms/{UUID1}", headers=admin).json()["details"]["os_type"] == "Ubuntu_64"


def test_vm_validation_and_authorization(client, admin, user):
    client.get("/api/vms?refresh=true", headers=admin)
    assert client.post("/api/vms/not-a-uuid/start", headers=admin).status_code == 422
    assert client.post(f"/api/vms/{UUID1}/stop", headers=user).status_code == 404


def test_vm_unexpected_stop_detection(db):
    adapter: MockVBoxAdapter = get_vbox_adapter()
    sync_vms(db)
    adapter.vms[UUID1]["state"] = "aborted"
    sync_vms(db)
    a = db.scalar(select(Alert).where(Alert.fingerprint.like("vm_unexpected_stop%")))
    assert a is not None and a.severity == "critical"


def test_virtualbox_missing_shows_setup_message(client, admin, monkeypatch):
    from app.virtualization import vbox
    monkeypatch.setattr(vbox, "find_vboxmanage", lambda configured="": None)
    vbox.set_vbox_adapter(RealVBoxAdapter())
    body = client.get("/api/vms?refresh=true", headers=admin).json()
    assert body["virtualbox"]["available"] is False
    assert "VirtualBox" in body["virtualbox"]["message"] and body["items"] == []


def test_vbox_wrapper_rejects_unlisted_commands():
    a = RealVBoxAdapter()
    a.path = "VBoxManage"  # pretend installed; whitelist check happens before execution
    with pytest.raises(VBoxError):
        a._run(["modifyvm", UUID1, "--memory", "1"])
    with pytest.raises(VBoxError):
        a._run(["list", "hostinfo"])
    with pytest.raises(ValueError):
        validate_uuid("x; shutdown")


def test_vbox_parsers():
    m = LIST_RE.match('"Ubuntu Server" {11111111-2222-3333-4444-555555555555}')
    assert m and m.group("name") == "Ubuntu Server"
    info = parse_machinereadable('name="Ubuntu"\nVMState="running"\nmemory=2048\n')
    assert info == {"name": "Ubuntu", "VMState": "running", "memory": "2048"}
