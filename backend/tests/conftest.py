"""Test configuration.

Tests run against an in-memory SQLite database with the explicitly labelled MOCK Docker and
VirtualBox adapters (production uses the real integrations). System metrics come from real psutil.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="cloudguard-test-")
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": "sqlite://",
    "JWT_SECRET_KEY": "test-secret-key-not-for-production-0123456789",
    "INTEGRATION_MODE": "mock",
    "ENABLE_BACKGROUND_TASKS": "false",
    "DATA_DIR": _TMP,
    "RATE_LIMIT_AUTH_PER_MINUTE": "1000",
    "RATE_LIMIT_DEFAULT_PER_MINUTE": "100000",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, SessionLocal, engine, utcnow  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402
from app.docker_integration.adapter import MockDockerAdapter, set_docker_adapter  # noqa: E402
from app.main import app  # noqa: E402
from app.ml_engine.detector import detector  # noqa: E402
from app.models import SystemMetric  # noqa: E402
from app.monitoring.service import get_local_device  # noqa: E402
from app.services.seed import seed  # noqa: E402
from app.virtualization.vbox import MockVBoxAdapter, set_vbox_adapter  # noqa: E402

PASSWORD = "Str0ngPassw0rd"


@pytest.fixture(autouse=True)
def _fresh_state():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    limiter.reset()
    set_docker_adapter(MockDockerAdapter())
    set_vbox_adapter(MockVBoxAdapter())
    detector.reset()
    yield


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def register(client, username: str, email: str | None = None, password: str = PASSWORD):
    r = client.post("/api/auth/register", json={
        "email": email or f"{username}@example.com", "username": username, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def login(client, username: str, password: str = PASSWORD) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def auth_headers(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
def admin(client):
    register(client, "admin")
    return auth_headers(login(client, "admin"))


@pytest.fixture
def user(client, admin):
    register(client, "alice")
    return auth_headers(login(client, "alice"))


def insert_metrics(db, n: int, cpu=20.0, mem=40.0, disk=50.0, start_minutes_ago=None, step_seconds=5, **extra):
    """Insert synthetic metric rows for rule/ML tests (test data only)."""
    dev = get_local_device(db)
    start = utcnow() - timedelta(seconds=(start_minutes_ago * 60 if start_minutes_ago else n * step_seconds))
    rows = []
    for i in range(n):
        c = cpu(i) if callable(cpu) else cpu
        m = mem(i) if callable(mem) else mem
        rows.append(SystemMetric(
            device_id=dev.id, timestamp=start + timedelta(seconds=i * step_seconds), cpu_percent=c,
            memory_percent=m, disk_percent=disk, net_send_rate=extra.get("tx", 1000.0),
            net_recv_rate=extra.get("rx", 5000.0), process_count=extra.get("procs", 200),
            connection_count=extra.get("conns", 50), memory_total=16 * 2**30, disk_total=500 * 2**30,
        ))
    db.add_all(rows)
    db.commit()
    return rows
