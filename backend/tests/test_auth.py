from sqlalchemy import select

from app.models import Alert, LoginAttempt, RefreshToken, User
from tests.conftest import PASSWORD, auth_headers, login, register


def test_first_user_is_admin_then_regular_users(client):
    assert register(client, "root")["role_name"] == "admin"
    assert register(client, "bob")["role_name"] == "user"


def test_register_validation_and_duplicates(client):
    register(client, "root")
    r = client.post("/api/auth/register", json={"email": "x@example.com", "username": "root", "password": PASSWORD})
    assert r.status_code == 409
    r = client.post("/api/auth/register", json={"email": "bad", "username": "u1", "password": PASSWORD})
    assert r.status_code == 422
    r = client.post("/api/auth/register", json={"email": "w@example.com", "username": "weak", "password": "password"})
    assert r.status_code == 422
    r = client.post("/api/auth/register", json={"email": "w@example.com", "username": "bad name!", "password": PASSWORD})
    assert r.status_code == 422


def test_password_is_hashed(client, db):
    register(client, "root")
    u = db.scalar(select(User).where(User.username == "root"))
    assert u.hashed_password != PASSWORD and u.hashed_password.startswith("$argon2")


def test_login_success_and_failure(client, db):
    register(client, "root")
    tokens = login(client, "root")
    assert tokens["token_type"] == "bearer" and tokens["user"]["username"] == "root"
    # login with email also works
    login(client, "root@example.com")
    r = client.post("/api/auth/login", json={"username": "root", "password": "wrong-password1"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "ghost", "password": "wrong-password1"})
    assert r.status_code == 401
    attempts = db.scalars(select(LoginAttempt)).all()
    assert sum(a.success for a in attempts) == 2 and sum(not a.success for a in attempts) == 2


def test_me_requires_valid_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    register(client, "root")
    tokens = login(client, "root")
    # refresh token must not be accepted as access token
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}).status_code == 401
    assert client.get("/api/auth/me", headers=auth_headers(tokens)).json()["username"] == "root"


def test_refresh_rotation_and_reuse_detection(client, db):
    register(client, "root")
    t1 = login(client, "root")
    r = client.post("/api/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert r.status_code == 200
    t2 = r.json()
    # re-using the rotated token is rejected and revokes all sessions
    r = client.post("/api/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert r.status_code == 401
    r = client.post("/api/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert r.status_code == 401
    assert all(t.revoked for t in db.scalars(select(RefreshToken)).all())


def test_logout_revokes_refresh_token(client):
    register(client, "root")
    t = login(client, "root")
    r = client.post("/api/auth/logout", json={"refresh_token": t["refresh_token"]}, headers=auth_headers(t))
    assert r.status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_profile_update_and_password_change(client):
    register(client, "root")
    h = auth_headers(login(client, "root"))
    r = client.patch("/api/auth/me", json={"full_name": "Root User"}, headers=h)
    assert r.json()["full_name"] == "Root User"
    r = client.post("/api/auth/change-password", json={"current_password": "nope", "new_password": "NewPassw0rd"}, headers=h)
    assert r.status_code == 400
    r = client.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "NewPassw0rd"}, headers=h)
    assert r.status_code == 200
    login(client, "root", "NewPassw0rd")


def test_login_history(client):
    register(client, "root")
    client.post("/api/auth/login", json={"username": "root", "password": "wrong-pass1"})
    h = auth_headers(login(client, "root"))
    items = client.get("/api/auth/login-history", headers=h).json()["items"]
    assert [i["success"] for i in items] == [True, False]


def test_bruteforce_detection_and_lockout(client, db):
    register(client, "root")
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "root", "password": "badpass123"}).status_code == 401
    # correct password is now refused because the account is locked
    r = client.post("/api/auth/login", json={"username": "root", "password": PASSWORD})
    assert r.status_code == 423
    alert = db.scalar(select(Alert).where(Alert.fingerprint.like("auth_bruteforce%")))
    assert alert is not None and alert.severity == "high" and alert.resource_name == "root"


def test_password_spray_detection(client, db):
    for name in ("u1", "u2", "u3"):
        client.post("/api/auth/login", json={"username": name, "password": "badpass123"})
    alert = db.scalar(select(Alert).where(Alert.fingerprint.like("auth_ip_spray%")))
    assert alert is not None and alert.resource_type == "ip"


def test_new_ip_detection(client, db):
    register(client, "root")
    login(client, "root")
    from app.core.database import SessionLocal
    from app.models import LoginAttempt as LA
    with SessionLocal() as s:  # simulate earlier login history from a different address
        for a in s.scalars(select(LA)).all():
            a.ip_address = "10.0.0.99"
        s.commit()
    login(client, "root")
    alert = db.scalar(select(Alert).where(Alert.fingerprint.like("auth_new_ip%")))
    assert alert is not None and alert.severity == "low"
