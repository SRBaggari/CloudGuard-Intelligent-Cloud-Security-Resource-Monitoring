import csv
import io
from datetime import timedelta

import pytest

from app.compliance import checks
from app.compliance.service import grade, score_results
from app.core.database import utcnow
from tests.conftest import insert_metrics


def _checks(client, admin):
    return {c["key"]: c for c in client.get("/api/compliance/checks", headers=admin).json()}


def test_checklist_seeded_and_admin_only(client, admin, user):
    cs = _checks(client, admin)
    assert len(cs) == len(checks.DEFAULT_CHECKS)
    assert {"automated", "manual"} == {c["check_type"] for c in cs.values()}
    assert all("Inspired by" in c["reference"] for c in cs.values())  # never claims certification
    for url in ("/api/compliance/checks", "/api/compliance/posture", "/api/compliance/runs"):
        assert client.get(url, headers=user).status_code == 403
    assert client.post("/api/compliance/run", headers=user).status_code == 403


def test_run_evaluates_real_state_and_scores(client, admin, db):
    insert_metrics(db, 3, start_minutes_ago=0.05)
    r = client.post("/api/compliance/run", headers=admin)
    assert r.status_code == 201
    run = r.json()
    by_key = {x["key"]: x for x in run["results"]}
    # test environment facts: JWT secret set via env (>=32 chars), SQLite, APP_ENV=test, mock Docker
    assert by_key["app_jwt_secret"]["status"] == "pass"
    assert by_key["app_database_server"]["status"] == "warning"
    assert by_key["app_production_mode"]["status"] == "warning"
    assert by_key["id_password_hashing"]["status"] == "pass" and "Argon2id" in by_key["id_password_hashing"]["evidence"]
    assert by_key["id_admin_accounts"]["status"] == "pass"
    assert by_key["mon_collector_running"]["status"] == "pass"
    assert by_key["mon_file_integrity"]["status"] == "fail"
    assert by_key["host_disk_space"]["status"] in ("pass", "warning", "fail")
    assert by_key["host_firewall"]["status"] in ("pass", "fail", "unknown")
    assert by_key["manual_backups"]["status"] == "not_assessed"
    assert all(x["evidence"] for x in run["results"])
    assert 0 <= run["score"] <= 100 and run["grade"] in "ABCDF"
    assert client.get("/api/compliance/posture", headers=admin).json()["id"] == run["id"]
    assert client.get("/api/compliance/runs", headers=admin).json()["total"] == 1


def test_container_checks_use_docker_inspect(client, admin, db):
    client.get("/api/containers?refresh=true", headers=admin)
    run = client.post("/api/compliance/run", headers=admin).json()
    by_key = {x["key"]: x for x in run["results"]}
    assert by_key["docker_no_privileged"]["status"] == "pass"
    # mock containers have no memory limits; demo-db (stopped) is not evaluated
    assert by_key["docker_memory_limits"]["status"] == "warning"
    assert by_key["docker_non_root"]["status"] == "pass"


def test_container_checks_not_applicable_without_docker(client, admin):
    from app.docker_integration.adapter import RealDockerAdapter, set_docker_adapter
    set_docker_adapter(RealDockerAdapter())
    run = client.post("/api/compliance/run", headers=admin).json()
    by_key = {x["key"]: x for x in run["results"]}
    if "not connected" in by_key["docker_no_privileged"]["evidence"]:
        assert by_key["docker_no_privileged"]["status"] == "not_applicable"


def test_rule_based_checks_follow_configuration(client, admin, db):
    rules = client.get("/api/security/rules", headers=admin).json()
    bf = next(r for r in rules if r["key"] == "auth_bruteforce")
    client.patch(f"/api/security/rules/{bf['id']}", json={"enabled": False}, headers=admin)
    by_key = {x["key"]: x for x in client.post("/api/compliance/run", headers=admin).json()["results"]}
    assert by_key["mon_detection_rules"]["status"] == "pass"  # 18/19 = 94.7% >= 90%
    other = next(r for r in rules if r["key"] == "process_spike")
    client.patch(f"/api/security/rules/{other['id']}", json={"enabled": False}, headers=admin)  # 17/19 < 90%
    by_key = {x["key"]: x for x in client.post("/api/compliance/run", headers=admin).json()["results"]}
    assert by_key["id_lockout_policy"]["status"] == "fail"
    assert by_key["mon_detection_rules"]["status"] == "warning"


def test_manual_assessment_and_custom_checks(client, admin):
    cs = _checks(client, admin)
    mid = cs["manual_backups"]["id"]
    assert client.post(f"/api/compliance/checks/{mid}/assess", json={"status": "pass", "evidence": ""}, headers=admin).status_code == 422
    r = client.post(f"/api/compliance/checks/{mid}/assess", json={"status": "pass", "evidence": "Nightly backup, restore tested 2026-11-01"}, headers=admin)
    assert r.json()["last_status"] == "pass" and r.json()["assessed_at"]
    auto = cs["host_disk_space"]["id"]
    assert client.post(f"/api/compliance/checks/{auto}/assess", json={"status": "pass", "evidence": "trust me"}, headers=admin).status_code == 409
    # custom item
    r = client.post("/api/compliance/checks", json={"title": "Visitor log reviewed weekly", "severity": "low"}, headers=admin)
    assert r.status_code == 201 and r.json()["is_custom"] and r.json()["check_type"] == "manual"
    cid = r.json()["id"]
    assert client.patch(f"/api/compliance/checks/{cid}", json={"title": "Visitor log reviewed daily"}, headers=admin).json()["title"].endswith("daily")
    assert client.patch(f"/api/compliance/checks/{auto}", json={"title": "renamed"}, headers=admin).status_code == 422
    assert client.delete(f"/api/compliance/checks/{auto}", headers=admin).status_code == 409
    assert client.delete(f"/api/compliance/checks/{cid}", headers=admin).status_code == 204
    # disabled checks are skipped
    client.patch(f"/api/compliance/checks/{auto}", json={"enabled": False}, headers=admin)
    keys = {x["key"] for x in client.post("/api/compliance/run", headers=admin).json()["results"]}
    assert "host_disk_space" not in keys and "manual_backups" in keys


def test_scoring_weights_and_grades():
    results = [{"status": "pass", "severity": "critical"}, {"status": "fail", "severity": "low"},
               {"status": "warning", "severity": "medium"}, {"status": "not_applicable", "severity": "high"}]
    score, counts = score_results(results)
    assert score == round((4 + 0 + 1) / (4 + 1 + 2) * 100, 1)
    assert counts == {"pass": 1, "fail": 1, "warning": 1, "not_applicable": 1}
    assert grade(95) == "A" and grade(80) == "B" and grade(65) == "C" and grade(45) == "D" and grade(10) == "F"


def test_broken_check_reported_as_unknown(client, admin, monkeypatch):
    def boom(db):
        raise RuntimeError("probe failed")
    monkeypatch.setitem(checks.AUTOMATED, "host_disk_space", boom)
    by_key = {x["key"]: x for x in client.post("/api/compliance/run", headers=admin).json()["results"]}
    assert by_key["host_disk_space"]["status"] == "unknown" and "RuntimeError" in by_key["host_disk_space"]["evidence"]


def test_posture_report_pdf_and_csv(client, admin, user):
    now = utcnow()
    rng = {"start_date": (now - timedelta(days=1)).isoformat(), "end_date": (now + timedelta(minutes=1)).isoformat()}
    r = client.post("/api/reports/generate", json={**rng, "format": "pdf", "sections": ["posture"], "title": "Posture"}, headers=admin)
    assert r.status_code == 201 and "posture_score" in r.json()["summary"]
    assert client.get(f"/api/reports/{r.json()['id']}/download", headers=admin).content[:4] == b"%PDF"
    r = client.post("/api/reports/generate", json={**rng, "format": "csv", "sections": ["posture"]}, headers=admin)
    text = client.get(f"/api/reports/{r.json()['id']}/download", headers=admin).text
    assert "# Security posture" in text and "not a formal CIS assessment" in text
    assert client.post("/api/reports/generate", json={**rng, "sections": ["posture"]}, headers=user).status_code == 403


# ---------------------------------------------------------------- audit log
def test_audit_log_usernames_filters_and_export(client, admin):
    items = client.get("/api/activity", headers=admin).json()["items"]
    assert any(i["username"] == "admin" for i in items)
    future = (utcnow() + timedelta(days=1)).isoformat()
    assert client.get("/api/activity", params={"start": future}, headers=admin).json()["total"] == 0
    assert client.get("/api/activity?action=auth.", headers=admin).json()["total"] >= 1
    r = client.get("/api/activity/export?action=auth.", headers=admin)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:5] == ["id", "timestamp_utc", "user_id", "username", "action"]
    assert all(row[4].startswith("auth.") for row in rows[1:])
    assert any(i["action"] == "audit.exported" for i in client.get("/api/activity", headers=admin).json()["items"])


def test_audit_export_admin_only(client, user):
    assert client.get("/api/activity/export", headers=user).status_code == 403


@pytest.mark.parametrize("fn", ["host_firewall", "host_ssh_root_login", "host_recent_reboot"])
def test_host_checks_return_valid_status(fn):
    status, evidence = getattr(checks, fn)(None)
    assert status in ("pass", "fail", "warning", "not_applicable", "unknown") and evidence
