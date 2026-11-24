import csv
import io
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import utcnow
from app.integrity import fim
from app.models import Alert, AnomalyRecord
from tests.conftest import insert_metrics


# ---------------------------------------------------------------- File integrity
@pytest.fixture
def watched(tmp_path, monkeypatch):
    # tmp dirs live under AppData on Windows, which is blocked by default; allow them for tests only
    monkeypatch.setattr(fim, "_blocked_roots", lambda: [])
    d = tmp_path / "site"
    d.mkdir()
    (d / "index.html").write_text("hello")
    (d / "config.ini").write_text("a=1")
    (d / "sub").mkdir()
    (d / "sub" / "app.js").write_text("console.log(1)")
    return d


def test_fim_baseline_and_change_detection(client, admin, db, watched: Path):
    r = client.post("/api/integrity/directories", json={"path": str(watched)}, headers=admin)
    assert r.status_code == 201, r.text
    dir_id = r.json()["id"]
    st = client.get("/api/integrity/status", headers=admin).json()
    assert st["directories"][0]["files"] == 3

    r = client.post("/api/integrity/scan", headers=admin).json()["results"][0]
    assert (r["modified"], r["new"], r["deleted"]) == (0, 0, 0)

    (watched / "index.html").write_text("hacked")
    (watched / "backdoor.php").write_text("<?php ?>")
    (watched / "config.ini").unlink()
    r = client.post(f"/api/integrity/scan?directory_id={dir_id}", headers=admin).json()["results"][0]
    assert (r["modified"], r["new"], r["deleted"]) == (1, 1, 1)

    hist = client.get("/api/integrity/history", headers=admin).json()
    assert {h["change_type"] for h in hist["items"]} == {"modified", "new", "deleted"}
    modified = next(h for h in hist["items"] if h["change_type"] == "modified")
    assert modified["old_hash"] != modified["new_hash"] and len(modified["new_hash"]) == 64

    alert = db.scalar(select(Alert).where(Alert.fingerprint.like("fim_change%")))
    assert alert is not None and alert.severity == "high"  # deletions escalate

    # rescanning without further changes yields nothing new
    r = client.post("/api/integrity/scan", headers=admin).json()["results"][0]
    assert (r["modified"], r["new"], r["deleted"]) == (0, 0, 0)

    # accept changes => new baseline
    assert client.post(f"/api/integrity/directories/{dir_id}/baseline", headers=admin).json()["files"] == 3
    files = client.get(f"/api/integrity/directories/{dir_id}/files", headers=admin).json()
    assert all(f["status"] == "baseline" for f in files["items"])


def test_fim_rejects_unsafe_paths(client, admin, watched):
    assert client.post("/api/integrity/directories", json={"path": "relative/path"}, headers=admin).status_code == 400
    assert client.post("/api/integrity/directories", json={"path": str(watched / "nope")}, headers=admin).status_code == 400
    assert client.post("/api/integrity/directories", json={"path": str(watched / "index.html")}, headers=admin).status_code == 400
    root = Path(watched.anchor)
    assert client.post("/api/integrity/directories", json={"path": str(root)}, headers=admin).status_code == 400
    client.post("/api/integrity/directories", json={"path": str(watched)}, headers=admin)
    assert client.post("/api/integrity/directories", json={"path": str(watched)}, headers=admin).status_code == 409


def test_fim_blocks_sensitive_system_dirs():
    for p in fim._blocked_roots():
        if p.exists():
            with pytest.raises(fim.PathNotAllowed):
                fim.validate_directory(str(p))
    with pytest.raises(fim.PathNotAllowed):
        fim.validate_directory(str(Path.home().parent))  # contains users' .ssh / AppData


def test_sha256():
    import hashlib
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"abc")
    assert fim.sha256_file(Path(f.name)) == hashlib.sha256(b"abc").hexdigest()
    Path(f.name).unlink()


# ---------------------------------------------------------------- ML anomaly detection
def test_ml_insufficient_data(client, admin, db):
    insert_metrics(db, 20)
    body = client.get("/api/analytics/anomalies", headers=admin).json()
    assert body["status"] == "insufficient_data" and "More monitoring data is needed" in body["message"]
    r = client.post("/api/analytics/anomalies/train", headers=admin)
    assert r.status_code == 409


def test_ml_train_and_detect_spike(client, admin, db):
    # normal behaviour: gentle periodic pattern
    insert_metrics(db, 400, cpu=lambda i: 20 + (i % 10), mem=lambda i: 45 + (i % 5), start_minutes_ago=60)
    r = client.post("/api/analytics/anomalies/train", headers=admin)
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["n_samples"] == 400 and "evaluation" in info and info["evaluation"]["holdout_samples"] == 80

    from app.ml_engine.detector import detector
    spike = insert_metrics(db, 1, cpu=99.0, mem=97.0, start_minutes_ago=0.01)[0]
    rec = detector.score_and_store(db, spike)
    assert rec is not None and rec.is_anomaly and "CPU" in rec.explanation and "σ" in rec.explanation
    normal = insert_metrics(db, 1, cpu=24.0, mem=47.0, start_minutes_ago=0.005)[0]
    assert detector.score_and_store(db, normal) is None  # normal samples are not stored

    body = client.get("/api/analytics/anomalies?points=50", headers=admin).json()
    assert body["status"] == "ready" and any(s["is_anomaly"] for s in body["series"])
    assert len(body["records"]) == 1
    assert db.scalar(select(AnomalyRecord)).is_anomaly


# ---------------------------------------------------------------- Reports & analytics
def _range():
    now = utcnow()
    return {"start_date": (now - timedelta(days=1)).isoformat(), "end_date": (now + timedelta(minutes=1)).isoformat()}


def test_generate_pdf_and_csv_reports(client, admin, user, db):
    insert_metrics(db, 50, cpu=lambda i: 30 + i % 20)
    client.get("/api/containers?refresh=true", headers=admin)
    from app.services.alerts import detect
    detect(db, "cpu_threshold", title="CPU high", description="d", resource_type="host", resource_name="h1")

    r = client.post("/api/reports/generate", json={**_range(), "format": "pdf", "title": "Weekly"}, headers=admin)
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["summary"]["alerts"] == 1 and rep["summary"]["samples"] == 50
    dl = client.get(f"/api/reports/{rep['id']}/download", headers=admin)
    assert dl.status_code == 200 and dl.content[:4] == b"%PDF"

    r = client.post("/api/reports/generate", json={**_range(), "format": "csv", "sections": ["resources", "alerts", "containers"]},
                    headers=admin)
    dl = client.get(f"/api/reports/{r.json()['id']}/download", headers=admin)
    rows = list(csv.reader(io.StringIO(dl.text)))
    assert ["# Alert history"] in rows and ["# Containers"] in rows and ["# Anomalies"] not in rows

    # regular users cannot see admin's reports
    assert client.get(f"/api/reports/{rep['id']}/download", headers=user).status_code == 404
    assert client.get("/api/reports", headers=user).json()["total"] == 0
    assert client.get("/api/reports", headers=admin).json()["total"] == 2
    assert client.delete(f"/api/reports/{rep['id']}", headers=admin).status_code == 204


def test_report_validation(client, admin):
    now = utcnow()
    bad = {"start_date": now.isoformat(), "end_date": (now - timedelta(days=1)).isoformat()}
    assert client.post("/api/reports/generate", json=bad, headers=admin).status_code == 422
    assert client.post("/api/reports/generate", json={**_range(), "format": "docx"}, headers=admin).status_code == 422
    assert client.post("/api/reports/generate", json={**_range(), "sections": []}, headers=admin).status_code == 422


def test_analytics_overview(client, admin, db):
    insert_metrics(db, 30)
    from app.services.alerts import detect
    detect(db, "cpu_threshold", title="CPU", description="d", resource_type="host", resource_name="h1")
    body = client.get("/api/analytics/overview?days=1", headers=admin).json()
    assert body["samples"] == 30 and body["timeline"] and body["total_alerts"] == 1
    assert body["alerts_by_category"] == {"system": 1}
