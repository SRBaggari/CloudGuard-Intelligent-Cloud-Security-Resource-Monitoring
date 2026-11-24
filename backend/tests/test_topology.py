from app.services.alerts import detect


def _topo(client, headers):
    r = client.get("/api/topology", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _node(t, node_id):
    return next(n for n in t["nodes"] if n["id"] == node_id)


def test_topology_graph_from_real_resources(client, admin, db):
    from app.monitoring.service import collect_and_store
    collect_and_store(db)
    client.get("/api/containers?refresh=true", headers=admin)
    client.get("/api/vms?refresh=true", headers=admin)
    t = _topo(client, admin)
    types = {n["type"] for n in t["nodes"]}
    assert types == {"host", "docker", "container", "network", "hypervisor", "vm"}
    assert sum(n["type"] == "container" for n in t["nodes"]) == 3
    assert {n["label"] for n in t["nodes"] if n["type"] == "network"} == {"bridge", "demo-app-net"}
    host = next(n for n in t["nodes"] if n["type"] == "host")
    assert host["health"] in ("healthy", "warning", "critical") and host["details"]["cpu_percent"] is not None
    kinds = {(e["source"].split(":")[0], e["target"].split(":")[0]) for e in t["edges"]}
    assert ("device", "docker-engine") in kinds and ("docker-engine", "container") in kinds
    assert ("container", "network") in kinds and ("virtualbox", "vm") in kinds
    ids = {n["id"] for n in t["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in t["edges"])  # no dangling edges


def test_unhealthy_and_stopped_resources_highlighted(client, admin, db):
    from app.docker_integration.adapter import get_docker_adapter
    from app.docker_integration.service import sync_containers
    from app.virtualization.vbox import get_vbox_adapter
    from app.virtualization.service import sync_vms
    a = get_docker_adapter()
    web = next(c for c in a.containers.values() if c["name"] == "demo-web")
    web["health"] = "unhealthy"
    sync_containers(db)
    get_vbox_adapter().vms["11111111-2222-3333-4444-555555555555"]["state"] = "aborted"
    sync_vms(db)
    t = _topo(client, admin)
    by_label = {n["label"]: n for n in t["nodes"]}
    assert by_label["demo-web"]["health"] == "critical"
    assert by_label["demo-db"]["health"] == "stopped"           # exited cleanly
    assert by_label["demo-ubuntu-server"]["health"] == "critical"  # aborted VM
    assert by_label["demo-windows-lab"]["health"] == "stopped"
    assert t["summary"]["critical"] >= 2


def test_active_alerts_counted_on_nodes(client, admin, db):
    client.get("/api/containers?refresh=true", headers=admin)
    detect(db, "container_resource", title="busy", description="d", resource_type="container", resource_name="demo-api")
    n = next(n for n in _topo(client, admin)["nodes"] if n["label"] == "demo-api")
    assert n["alerts"] == 1 and n["health"] == "warning"


def test_unavailable_integrations_produce_no_fake_nodes(client, admin, monkeypatch):
    from app.docker_integration.adapter import RealDockerAdapter, set_docker_adapter
    from app.virtualization import vbox
    set_docker_adapter(RealDockerAdapter())
    monkeypatch.setattr(vbox, "find_vboxmanage", lambda configured="": None)
    vbox.set_vbox_adapter(vbox.RealVBoxAdapter())
    t = _topo(client, admin)
    if not t["integrations"]["docker"]["available"]:
        assert not any(n["type"] in ("docker", "container") for n in t["nodes"])
    assert not any(n["type"] in ("hypervisor", "vm") for n in t["nodes"])


def test_regular_user_sees_only_assigned_resources(client, admin, user):
    client.get("/api/containers?refresh=true", headers=admin)
    t = _topo(client, user)
    assert not any(n["type"] == "container" for n in t["nodes"])
    assert any(n["type"] == "host" for n in t["nodes"])


def test_topology_requires_auth(client):
    assert client.get("/api/topology").status_code == 401
