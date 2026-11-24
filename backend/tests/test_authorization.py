import pytest

from tests.conftest import auth_headers, login, register

ADMIN_ONLY = [
    ("get", "/api/users"), ("get", "/api/activity"), ("get", "/api/security/events"),
    ("get", "/api/security/login-attempts"), ("get", "/api/monitoring/processes"),
    ("get", "/api/integrity/status"), ("post", "/api/integrity/scan"), ("post", "/api/analytics/anomalies/train"),
    ("put", "/api/settings"), ("patch", "/api/security/rules/1"), ("post", "/api/security/alerts/1/acknowledge"),
    ("post", "/api/security/alerts/1/resolve"),
]


@pytest.mark.parametrize("method,url", ADMIN_ONLY)
def test_regular_user_forbidden_on_admin_endpoints(client, user, method, url):
    kwargs = {"json": {}} if method in ("put", "patch", "post") else {}
    r = getattr(client, method)(url, headers=user, **kwargs)
    assert r.status_code == 403, (url, r.status_code, r.text)


@pytest.mark.parametrize("url", ["/api/dashboard/summary", "/api/monitoring/system", "/api/containers", "/api/vms",
                                 "/api/security/alerts", "/api/reports", "/api/analytics/overview"])
def test_unauthenticated_rejected(client, url):
    assert client.get(url).status_code == 401


def test_user_only_sees_and_manages_assigned_containers(client, admin, user):
    containers = client.get("/api/containers?refresh=true", headers=admin).json()["items"]
    assert len(containers) == 3
    # regular user sees nothing until assigned
    assert client.get("/api/containers", headers=user).json()["items"] == []
    web = next(c for c in containers if c["name"] == "demo-web")
    assert client.post(f"/api/containers/{web['container_id']}/stop", headers=user).status_code == 404

    users = client.get("/api/users", headers=admin).json()["items"]
    alice = next(u for u in users if u["username"] == "alice")
    r = client.put(f"/api/containers/{web['container_id']}/owner", json={"owner_id": alice["id"]}, headers=admin)
    assert r.status_code == 200
    visible = client.get("/api/containers", headers=user).json()["items"]
    assert [c["name"] for c in visible] == ["demo-web"]
    assert client.post(f"/api/containers/{web['container_id']}/stop", headers=user).status_code == 200
    # still cannot touch others
    api = next(c for c in containers if c["name"] == "demo-api")
    assert client.post(f"/api/containers/{api['container_id']}/stop", headers=user).status_code == 404


def test_admin_user_management(client, admin, user):
    users = client.get("/api/users", headers=admin).json()["items"]
    alice = next(u for u in users if u["username"] == "alice")
    me = next(u for u in users if u["username"] == "admin")
    assert client.patch(f"/api/users/{me['id']}", json={"role": "user"}, headers=admin).status_code == 400
    r = client.patch(f"/api/users/{alice['id']}", json={"is_active": False}, headers=admin)
    assert r.json()["is_active"] is False
    # disabled user's existing token stops working
    assert client.get("/api/auth/me", headers=user).status_code == 401
    r = client.patch(f"/api/users/{alice['id']}", json={"is_active": True, "role": "admin"}, headers=admin)
    assert r.json()["role_name"] == "admin"


def test_activity_log_records_actions(client, admin):
    client.post("/api/auth/logout", headers=admin)
    h = auth_headers(login(client, "admin"))
    actions = [a["action"] for a in client.get("/api/activity", headers=h).json()["items"]]
    assert "auth.login" in actions and "auth.logout" in actions and "user.registered" in actions


def test_rate_limit(client, monkeypatch):
    from app.core.ratelimit import RateLimitMiddleware

    # find middleware instance and lower its limit
    register(client, "root")
    stack = client.app.middleware_stack
    mw = stack
    while mw is not None and not isinstance(mw, RateLimitMiddleware):
        mw = getattr(mw, "app", None)
    assert mw is not None
    monkeypatch.setattr(mw, "auth_limit", 3)
    codes = [client.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code for _ in range(5)]
    assert 429 in codes
