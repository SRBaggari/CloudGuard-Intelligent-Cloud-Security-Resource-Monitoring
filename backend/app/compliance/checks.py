"""Security checklist definitions and automated check implementations.

Checks are *inspired by* CIS Controls v8 and CIS Benchmarks (Docker, operating systems). They are
basic, read-only verifications of this installation; passing them does NOT constitute CIS
certification or a formal benchmark assessment.

Every automated check returns ``(status, evidence)`` where status is one of
pass | fail | warning | not_applicable | unknown.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import time
from datetime import timedelta
from pathlib import Path
from typing import Callable

import psutil
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import config as config_module
from app.core.config import get_settings
from app.core.database import ensure_aware, utcnow
from app.models import ActivityLog, Alert, Container, DetectionRule, MonitoredDirectory, Role, SystemMetric, User
from app.monitoring.collector import system_disk_path
from app.services import settings_service

Result = tuple[str, str]

DEFAULT_CHECKS: list[dict] = [
    # ---------------- application configuration
    {"key": "app_jwt_secret", "category": "application", "severity": "critical",
     "title": "Token signing secret is configured", "reference": "Inspired by CIS Controls v8 3.11 (encrypt sensitive data)",
     "description": "JWT_SECRET_KEY is set explicitly (not generated at start-up) and is at least 32 characters.",
     "remediation": "Generate a secret with `python -c \"import secrets; print(secrets.token_urlsafe(64))\"` and set JWT_SECRET_KEY in .env."},
    {"key": "app_production_mode", "category": "application", "severity": "medium",
     "title": "Application runs in production mode", "reference": "Inspired by CIS Controls v8 4.1 (secure configuration)",
     "description": "APP_ENV=production enforces mandatory secrets.", "remediation": "Set APP_ENV=production for deployed instances."},
    {"key": "app_database_server", "category": "application", "severity": "medium",
     "title": "Server-grade database in use", "reference": "Inspired by CIS Controls v8 11 (data recovery)",
     "description": "PostgreSQL is used instead of the local SQLite fallback.", "remediation": "Set DATABASE_URL to a PostgreSQL database."},
    {"key": "app_cors_restricted", "category": "application", "severity": "high",
     "title": "CORS restricted to explicit origins", "reference": "Inspired by CIS Controls v8 4.1",
     "description": "No wildcard (*) origin is allowed.", "remediation": "List the exact frontend origin(s) in CORS_ORIGINS."},
    {"key": "app_rate_limiting", "category": "application", "severity": "high",
     "title": "Authentication rate limiting enabled", "reference": "Inspired by CIS Controls v8 13 (network defence)",
     "description": "Login/registration requests are limited to at most 30 per minute per IP.",
     "remediation": "Set RATE_LIMIT_AUTH_PER_MINUTE to 30 or lower."},
    {"key": "app_metrics_protected", "category": "application", "severity": "low",
     "title": "Prometheus endpoint protected", "reference": "Inspired by CIS Controls v8 3.3 (data access control)",
     "description": "If /metrics is enabled, it requires a bearer token.", "remediation": "Set PROMETHEUS_TOKEN or PROMETHEUS_ENABLED=false."},
    # ---------------- identity & access
    {"key": "id_admin_accounts", "category": "identity", "severity": "high",
     "title": "Administrative accounts are limited", "reference": "Inspired by CIS Controls v8 5.4 (restrict admin privileges)",
     "description": "Between 1 and 3 active administrator accounts exist.", "remediation": "Demote unnecessary administrators in Settings → Users."},
    {"key": "id_dormant_accounts", "category": "identity", "severity": "medium",
     "title": "No dormant accounts", "reference": "Inspired by CIS Controls v8 5.3 (disable dormant accounts)",
     "description": "Active accounts have signed in within the last 45 days (new accounts get a 7-day grace period).",
     "remediation": "Disable accounts that are no longer used."},
    {"key": "id_password_hashing", "category": "identity", "severity": "critical",
     "title": "Passwords stored with Argon2id", "reference": "Inspired by CIS Controls v8 3.11 / NIST SP 800-63B",
     "description": "Every stored password hash uses the Argon2id algorithm.", "remediation": "Reset passwords of accounts with legacy hashes."},
    {"key": "id_lockout_policy", "category": "identity", "severity": "high",
     "title": "Account lockout on repeated failures", "reference": "Inspired by CIS Controls v8 6.x / CIS Benchmark lockout policy",
     "description": "The brute-force rule is enabled and locks accounts after at most 10 failures.",
     "remediation": "Enable and tune the 'Multiple failed login attempts' rule."},
    # ---------------- logging & monitoring
    {"key": "log_audit_active", "category": "logging", "severity": "high",
     "title": "Audit logging active", "reference": "Inspired by CIS Controls v8 8.2 (collect audit logs)",
     "description": "Audit entries were recorded in the last 7 days.", "remediation": "Investigate why user and administrative actions are not being logged."},
    {"key": "log_retention", "category": "logging", "severity": "medium",
     "title": "Metric retention of at least 30 days", "reference": "Inspired by CIS Controls v8 8.10 (retain audit logs)",
     "description": "Historical monitoring data is kept long enough for investigations.", "remediation": "Increase retention in Settings → Monitoring."},
    {"key": "mon_collector_running", "category": "logging", "severity": "high",
     "title": "Metric collector is running", "reference": "Inspired by CIS Controls v8 8.11 (conduct audit log reviews)",
     "description": "A metric sample was recorded within three collection intervals.", "remediation": "Check the backend scheduler and logs."},
    {"key": "mon_detection_rules", "category": "logging", "severity": "medium",
     "title": "Detection rules enabled", "reference": "Inspired by CIS Controls v8 13.1 (centralise alerting)",
     "description": "At least 90% of detection rules are enabled.", "remediation": "Re-enable disabled rules under Detection & Events."},
    {"key": "mon_file_integrity", "category": "logging", "severity": "medium",
     "title": "File integrity monitoring configured", "reference": "Inspired by CIS Controls v8 3.14 / 8 (log sensitive data access)",
     "description": "At least one directory is monitored for changes.", "remediation": "Add critical application/configuration folders under File Integrity."},
    {"key": "mon_alert_backlog", "category": "logging", "severity": "high",
     "title": "No stale high-severity alerts", "reference": "Inspired by CIS Controls v8 17 (incident response)",
     "description": "No critical or high alert has been open for more than 24 hours.", "remediation": "Triage the alert backlog in the Alert Center."},
    # ---------------- host
    {"key": "host_firewall", "category": "host", "severity": "high",
     "title": "Host firewall enabled", "reference": "Inspired by CIS Benchmarks (Windows/Linux) host firewall section",
     "description": "The operating-system firewall is active on all profiles.", "remediation": "Enable Windows Defender Firewall / ufw / firewalld."},
    {"key": "host_ssh_root_login", "category": "host", "severity": "high",
     "title": "SSH root login disabled", "reference": "Inspired by CIS Linux Benchmark 5.2 (SSH server configuration)",
     "description": "sshd_config sets PermitRootLogin to no or prohibit-password (Linux/macOS with OpenSSH).",
     "remediation": "Set `PermitRootLogin no` in /etc/ssh/sshd_config and reload sshd."},
    {"key": "host_disk_space", "category": "host", "severity": "medium",
     "title": "Sufficient free disk space", "reference": "Inspired by CIS Controls v8 8.3 (adequate log storage)",
     "description": "At least 15% of the system volume is free (warning below 15%, fail below 5%).", "remediation": "Free or extend disk space."},
    {"key": "host_recent_reboot", "category": "host", "severity": "low",
     "title": "Host restarted within 30 days", "reference": "Inspired by CIS Controls v8 7.3/7.4 (automated patching)",
     "description": "Heuristic: very long uptime can mean installed updates are waiting for a restart.",
     "remediation": "Apply pending OS updates and restart during a maintenance window."},
    # ---------------- containers
    {"key": "docker_no_privileged", "category": "containers", "severity": "critical",
     "title": "No privileged containers", "reference": "Inspired by CIS Docker Benchmark 5.4",
     "description": "Running containers do not use --privileged.", "remediation": "Remove --privileged; grant only required capabilities."},
    {"key": "docker_non_root", "category": "containers", "severity": "medium",
     "title": "Containers run as non-root users", "reference": "Inspired by CIS Docker Benchmark 4.1",
     "description": "Running containers define a non-root USER.", "remediation": "Add a USER instruction to images or use --user."},
    {"key": "docker_memory_limits", "category": "containers", "severity": "low",
     "title": "Container memory limits set", "reference": "Inspired by CIS Docker Benchmark 5.10",
     "description": "Running containers have a memory limit.", "remediation": "Start containers with --memory."},
    # ---------------- manual (organisational) items
    {"key": "manual_backups", "category": "organisational", "severity": "high", "check_type": "manual",
     "title": "Backups are taken and restore-tested", "reference": "Inspired by CIS Controls v8 11.2 / 11.5",
     "description": "Critical data is backed up automatically and a restore was tested in the last quarter.",
     "remediation": "Schedule backups and document a restore test."},
    {"key": "manual_patching", "category": "organisational", "severity": "high", "check_type": "manual",
     "title": "OS and application patches applied within 30 days", "reference": "Inspired by CIS Controls v8 7.3 / 7.4",
     "description": "Security updates are applied on a defined schedule.", "remediation": "Enable automatic updates or define a patch window."},
    {"key": "manual_ir_plan", "category": "organisational", "severity": "medium", "check_type": "manual",
     "title": "Incident response contacts documented", "reference": "Inspired by CIS Controls v8 17.1 / 17.2",
     "description": "Responsible people and escalation contacts are documented.", "remediation": "Document an incident response contact list."},
    {"key": "manual_mfa_remote", "category": "organisational", "severity": "high", "check_type": "manual",
     "title": "MFA for remote and administrative access", "reference": "Inspired by CIS Controls v8 6.4 / 6.5",
     "description": "Remote access and administrator accounts on the host use multi-factor authentication.",
     "remediation": "Enable MFA on VPN, RDP/SSH gateways and cloud consoles."},
]


# ------------------------------------------------------------------ helpers
def _run(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess | None:
    """Run a fixed, read-only system command (no shell). Returns None if unavailable."""
    exe = shutil.which(args[0]) or (args[0] if Path(args[0]).is_file() else None)
    if not exe:
        return None
    try:
        return subprocess.run([exe, *args[1:]], capture_output=True, text=True, timeout=timeout, shell=False, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


# ------------------------------------------------------------------ application
def app_jwt_secret(db: Session) -> Result:
    s = get_settings()
    if config_module.EPHEMERAL_JWT_SECRET:
        return "fail", "JWT_SECRET_KEY is not set; an ephemeral secret was generated at start-up."
    if len(s.jwt_secret_key) < 32:
        return "fail", f"JWT_SECRET_KEY is only {len(s.jwt_secret_key)} characters long."
    return "pass", f"Explicit secret configured ({len(s.jwt_secret_key)} characters)."


def app_production_mode(db: Session) -> Result:
    env = get_settings().app_env
    return ("pass", "APP_ENV=production") if env == "production" else ("warning", f"APP_ENV={env}")


def app_database_server(db: Session) -> Result:
    s = get_settings()
    return ("warning", "SQLite fallback database in use.") if s.is_sqlite else ("pass", f"{db.get_bind().dialect.name} database.")


def app_cors_restricted(db: Session) -> Result:
    origins = get_settings().cors_origin_list
    if "*" in origins:
        return "fail", "Wildcard origin '*' is allowed."
    return "pass", f"{len(origins)} explicit origin(s): {', '.join(origins[:4])}"


def app_rate_limiting(db: Session) -> Result:
    n = get_settings().rate_limit_auth_per_minute
    return ("pass", f"{n} auth requests/min per IP") if 0 < n <= 30 else ("fail", f"Auth limit is {n}/min per IP.")


def app_metrics_protected(db: Session) -> Result:
    s = get_settings()
    if not s.prometheus_enabled:
        return "pass", "Prometheus endpoint disabled."
    return ("pass", "Bearer token required.") if s.prometheus_token else ("warning", "/metrics is enabled without a token.")


# ------------------------------------------------------------------ identity
def id_admin_accounts(db: Session) -> Result:
    n = db.scalar(select(func.count(User.id)).join(Role).where(Role.name == "admin", User.is_active.is_(True))) or 0
    if n == 0:
        return "fail", "No active administrator."
    return ("pass", f"{n} active administrator(s).") if n <= 3 else ("fail", f"{n} active administrators (more than 3).")


def id_dormant_accounts(db: Session) -> Result:
    now = utcnow()
    dormant = []
    for u in db.scalars(select(User).where(User.is_active.is_(True))).all():
        last = ensure_aware(u.last_login_at)
        created = ensure_aware(u.created_at)
        if (last and now - last > timedelta(days=45)) or (last is None and now - created > timedelta(days=7)):
            dormant.append(u.username)
    return ("pass", "No dormant active accounts.") if not dormant else ("fail", f"Dormant accounts: {', '.join(dormant[:10])}")


def id_password_hashing(db: Session) -> Result:
    hashes = db.scalars(select(User.hashed_password)).all()
    legacy = sum(not h.startswith("$argon2id$") for h in hashes)
    if not hashes:
        return "not_applicable", "No accounts yet."
    return ("pass", f"All {len(hashes)} hashes use Argon2id.") if not legacy else ("fail", f"{legacy} account(s) use another algorithm.")


def id_lockout_policy(db: Session) -> Result:
    r = db.scalar(select(DetectionRule).where(DetectionRule.key == "auth_bruteforce"))
    if not r or not r.enabled:
        return "fail", "Brute-force rule is disabled."
    n = int((r.params or {}).get("max_failures", 0))
    return ("pass", f"Lockout after {n} failures for {r.params.get('lockout_minutes')} min.") if 0 < n <= 10 \
        else ("fail", f"Lockout threshold is {n} failures.")


# ------------------------------------------------------------------ logging & monitoring
def log_audit_active(db: Session) -> Result:
    n = db.scalar(select(func.count(ActivityLog.id)).where(ActivityLog.created_at >= utcnow() - timedelta(days=7))) or 0
    return ("pass", f"{n} audit entries in the last 7 days.") if n else ("fail", "No audit entries in the last 7 days.")


def log_retention(db: Session) -> Result:
    days = int(settings_service.get_section(db, "monitoring")["retention_days"])
    if days >= 30:
        return "pass", f"Retention {days} days."
    return ("warning" if days >= 7 else "fail"), f"Retention only {days} days."


def mon_collector_running(db: Session) -> Result:
    interval = int(settings_service.get_section(db, "monitoring")["interval_seconds"])
    from app.monitoring.service import get_local_device
    dev = get_local_device(db)
    last = db.scalar(select(func.max(SystemMetric.timestamp)).where(SystemMetric.device_id == dev.id))
    if last is None:
        return "fail", "No metric samples recorded."
    age = (utcnow() - ensure_aware(last)).total_seconds()
    return ("pass", f"Last sample {int(age)} s ago.") if age <= max(60, interval * 3) else ("fail", f"Last sample {int(age)} s ago.")


def mon_detection_rules(db: Session) -> Result:
    rules = db.scalars(select(DetectionRule)).all()
    on = sum(r.enabled for r in rules)
    pct = on / len(rules) * 100 if rules else 0
    disabled = [r.key for r in rules if not r.enabled]
    return ("pass" if pct >= 90 else "warning"), f"{on}/{len(rules)} rules enabled" + (f" (disabled: {', '.join(disabled[:6])})" if disabled else "")


def mon_file_integrity(db: Session) -> Result:
    n = db.scalar(select(func.count(MonitoredDirectory.id)).where(MonitoredDirectory.enabled.is_(True))) or 0
    return ("pass", f"{n} monitored director{'y' if n == 1 else 'ies'}.") if n else ("fail", "No directories monitored.")


def mon_alert_backlog(db: Session) -> Result:
    cutoff = utcnow() - timedelta(hours=24)
    stmt = select(func.count(Alert.id)).where(Alert.status != "resolved", Alert.severity.in_(("critical", "high")),
                                              Alert.created_at < cutoff)
    stmt = stmt.where(Alert.is_demo.is_(False))
    n = db.scalar(stmt) or 0
    return ("pass", "No stale high-severity alerts.") if not n else ("fail", f"{n} high/critical alert(s) open for more than 24 h.")


# ------------------------------------------------------------------ host
def host_firewall(db: Session) -> Result:
    system = platform.system()
    if system == "Windows":
        p = _run(["netsh", "advfirewall", "show", "allprofiles", "state"])
        if p is None or p.returncode != 0:
            return "unknown", "Could not query Windows Firewall (netsh)."
        states = [ln.split()[-1].upper() for ln in p.stdout.splitlines() if ln.strip().lower().startswith("state")]
        if not states:
            return "unknown", "Unexpected netsh output."
        on = sum(s == "ON" for s in states)
        return ("pass", f"Firewall ON for all {len(states)} profiles.") if on == len(states) \
            else ("fail", f"Firewall ON for {on} of {len(states)} profiles.")
    if system == "Darwin":
        p = _run(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"])
        if p is None:
            return "unknown", "socketfilterfw not available."
        return ("pass", p.stdout.strip()) if "enabled" in p.stdout.lower() else ("fail", p.stdout.strip())
    for cmd, ok in ((["firewall-cmd", "--state"], "running"), (["systemctl", "is-active", "ufw"], "active"),
                    (["systemctl", "is-active", "firewalld"], "active"), (["systemctl", "is-active", "nftables"], "active")):
        p = _run(cmd)
        if p is not None and p.stdout.strip() == ok:
            return "pass", f"`{' '.join(cmd)}` → {ok}"
    return "fail", "No active firewall service (firewalld, ufw, nftables) detected."


def host_ssh_root_login(db: Session) -> Result:
    cfg = Path("/etc/ssh/sshd_config")
    if platform.system() == "Windows" or not cfg.exists():
        return "not_applicable", "OpenSSH server configuration not present on this host."
    try:
        lines = cfg.read_text(errors="replace").splitlines()
    except OSError as e:
        return "unknown", f"Cannot read sshd_config: {e.strerror}"
    value = next((ln.split()[1].lower() for ln in lines
                  if ln.strip().lower().startswith("permitrootlogin") and len(ln.split()) > 1), "prohibit-password (default)")
    return ("pass", f"PermitRootLogin {value}") if value.startswith(("no", "prohibit-password", "without-password")) \
        else ("fail", f"PermitRootLogin {value}")


def host_disk_space(db: Session) -> Result:
    u = psutil.disk_usage(system_disk_path())
    free = 100 - u.percent
    if free >= 15:
        return "pass", f"{free:.1f}% free on {system_disk_path()}"
    return ("warning" if free >= 5 else "fail"), f"Only {free:.1f}% free on {system_disk_path()}"


def host_recent_reboot(db: Session) -> Result:
    days = (time.time() - psutil.boot_time()) / 86400
    return ("pass", f"Uptime {days:.1f} days.") if days <= 30 else ("warning", f"Uptime {days:.0f} days — check for pending updates.")


# ------------------------------------------------------------------ containers
def _running_details(db: Session) -> tuple[list[dict] | None, str]:
    from app.docker_integration.adapter import get_docker_adapter
    adapter = get_docker_adapter()
    st = adapter.status()
    if not st.get("available"):
        return None, "Docker Engine not connected."
    stmt = select(Container).where(Container.status == "running", Container.is_demo.is_(False))
    out = []
    for c in db.scalars(stmt.limit(100)).all():
        try:
            out.append(adapter.inspect(c.container_id))
        except Exception:
            continue
    return out, ""


def _container_check(db: Session, bad: Callable[[dict], bool], what: str, severity_if_bad: str = "fail") -> Result:
    details, msg = _running_details(db)
    if details is None:
        return "not_applicable", msg
    if not details:
        return "not_applicable", "No running containers."
    offenders = [d["name"] for d in details if bad(d)]
    if not offenders:
        return "pass", f"All {len(details)} running container(s) compliant."
    return severity_if_bad, f"{len(offenders)} container(s) {what}: {', '.join(offenders[:8])}"


def docker_no_privileged(db: Session) -> Result:
    return _container_check(db, lambda d: bool(d.get("privileged")), "run privileged")


def docker_non_root(db: Session) -> Result:
    return _container_check(db, lambda d: (d.get("user") or "root").split(":")[0] in ("", "root", "0"), "run as root", "warning")


def docker_memory_limits(db: Session) -> Result:
    return _container_check(db, lambda d: not d.get("memory_limit"), "have no memory limit", "warning")


AUTOMATED: dict[str, Callable[[Session], Result]] = {
    name: fn for name, fn in globals().items()
    if callable(fn) and name in {c["key"] for c in DEFAULT_CHECKS if c.get("check_type", "automated") == "automated"}
}
assert len(AUTOMATED) == sum(c.get("check_type", "automated") == "automated" for c in DEFAULT_CHECKS)
