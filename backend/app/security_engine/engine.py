"""Rule-based detection engine.

Each `evaluate_*` function receives observed facts (a metric sample, a login attempt,
a container state transition...) and applies the enabled DetectionRules to them.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.core.database import ensure_aware, utcnow
from app.models import LoginAttempt, SystemMetric, User
from app.services.alerts import count_recent_events, detect, get_rule, record_event

MB = 1024 * 1024


# ------------------------------------------------------------------ system metrics
def _threshold(db: Session, key: str, label: str, field: str, metric: SystemMetric, host: str) -> None:
    rule = get_rule(db, key)
    if not rule or not rule.enabled:
        return
    p = rule.params or {}
    warning, critical, n = float(p.get("warning", 85)), float(p.get("critical", 95)), int(p.get("consecutive", 1))
    recent = db.scalars(
        select(SystemMetric).where(SystemMetric.device_id == metric.device_id)
        .order_by(SystemMetric.timestamp.desc()).limit(max(n, 1))
    ).all()
    if len(recent) < n:
        return
    values = [getattr(m, field) for m in recent]
    if all(v >= warning for v in values):
        sev = "critical" if all(v >= critical for v in values) else rule.severity
        cur = values[0]
        detect(
            db, key, title=f"{label} at {cur:.1f}% on {host}",
            description=f"{label} has been >= {warning:.0f}% for {n} consecutive samples (current {cur:.1f}%).",
            resource_type="host", resource_name=host, severity=sev,
            details={"value": round(cur, 2), "warning": warning, "critical": critical},
        )


def evaluate_metric(db: Session, metric: SystemMetric, host: str, previous: SystemMetric | None) -> None:
    _threshold(db, "cpu_threshold", "CPU utilisation", "cpu_percent", metric, host)
    _threshold(db, "memory_threshold", "Memory utilisation", "memory_percent", metric, host)
    _threshold(db, "disk_threshold", "Disk usage", "disk_percent", metric, host)

    rule = get_rule(db, "process_spike")
    if rule and rule.enabled and previous is not None:
        inc = metric.process_count - previous.process_count
        if inc >= int(rule.params.get("increase", 60)):
            detect(db, "process_spike", title=f"Process count jumped by {inc} on {host}",
                   description=f"Running processes rose from {previous.process_count} to {metric.process_count} "
                               f"between two samples.",
                   resource_type="host", resource_name=host,
                   details={"previous": previous.process_count, "current": metric.process_count})

    rule = get_rule(db, "network_connections")
    if rule and rule.enabled and metric.connection_count >= int(rule.params.get("max_connections", 800)):
        detect(db, "network_connections", title=f"{metric.connection_count} open network connections on {host}",
               description=f"Open inet connections ({metric.connection_count}) exceeded the configured limit "
                           f"of {rule.params.get('max_connections')}.",
               resource_type="host", resource_name=host, details={"connections": metric.connection_count})

    rule = get_rule(db, "network_traffic")
    if rule and rule.enabled:
        n = int(rule.params.get("consecutive", 3))
        limit = float(rule.params.get("mbps", 50)) * MB
        recent = db.scalars(
            select(SystemMetric).where(SystemMetric.device_id == metric.device_id)
            .order_by(SystemMetric.timestamp.desc()).limit(n)
        ).all()
        if len(recent) >= n and all(max(m.net_send_rate, m.net_recv_rate) >= limit for m in recent):
            direction = "upload" if metric.net_send_rate >= metric.net_recv_rate else "download"
            rate = max(metric.net_send_rate, metric.net_recv_rate) / MB
            detect(db, "network_traffic", title=f"Sustained {direction} of {rate:.1f} MB/s on {host}",
                   description=f"Network {direction} rate has exceeded {rule.params.get('mbps')} MB/s for {n} samples.",
                   resource_type="host", resource_name=host, details={"direction": direction, "mb_per_s": round(rate, 2)})


def evaluate_processes(db: Session, process_names: set[str], watchlist: list[str], host: str) -> None:
    if not watchlist:
        return
    lowered = {n.lower() for n in process_names}
    for name in watchlist:
        if name.strip() and name.strip().lower() in lowered:
            detect(db, "process_watchlist", title=f"Watch-listed process '{name}' running on {host}",
                   description=f"Process '{name}' is on the administrator watchlist and is currently running.",
                   resource_type="host", resource_name=host, dedupe_key=f"{host}:{name.lower()}",
                   details={"process": name})


# ------------------------------------------------------------------ authentication
def evaluate_login(db: Session, attempt: LoginAttempt, user: User | None) -> None:
    now = utcnow()
    if not attempt.success:
        rule = get_rule(db, "auth_bruteforce")
        if rule and rule.enabled:
            p = rule.params
            since = now - timedelta(minutes=int(p.get("window_minutes", 10)))
            fails = db.scalar(select(func.count(LoginAttempt.id)).where(
                LoginAttempt.identifier == attempt.identifier, LoginAttempt.success.is_(False),
                LoginAttempt.created_at >= since)) or 0
            if fails >= int(p.get("max_failures", 5)):
                if user is not None:
                    user.locked_until = now + timedelta(minutes=int(p.get("lockout_minutes", 15)))
                    db.commit()
                detect(db, "auth_bruteforce", title=f"{fails} failed logins for '{attempt.identifier}'",
                       description=f"{fails} failed login attempts for account '{attempt.identifier}' within "
                                   f"{p.get('window_minutes')} minutes (latest from {attempt.ip_address}). "
                                   + ("Account temporarily locked." if user else "Account does not exist."),
                       resource_type="account", resource_name=attempt.identifier,
                       details={"failures": fails, "ip": attempt.ip_address})

        rule = get_rule(db, "auth_ip_spray")
        if rule and rule.enabled:
            p = rule.params
            since = now - timedelta(minutes=int(p.get("window_minutes", 10)))
            accounts = db.scalar(select(func.count(distinct(LoginAttempt.identifier))).where(
                LoginAttempt.ip_address == attempt.ip_address, LoginAttempt.success.is_(False),
                LoginAttempt.created_at >= since)) or 0
            if accounts >= int(p.get("distinct_accounts", 3)):
                detect(db, "auth_ip_spray", title=f"Login failures across {accounts} accounts from {attempt.ip_address}",
                       description=f"Client {attempt.ip_address} failed to log in to {accounts} different accounts "
                                   f"within {p.get('window_minutes')} minutes.",
                       resource_type="ip", resource_name=attempt.ip_address, details={"accounts": accounts})
        return

    # successful login
    assert user is not None
    rule = get_rule(db, "auth_new_ip")
    if rule and rule.enabled:
        since = now - timedelta(days=int(rule.params.get("lookback_days", 30)))
        prior = db.scalars(select(LoginAttempt.ip_address).where(
            LoginAttempt.user_id == user.id, LoginAttempt.success.is_(True),
            LoginAttempt.created_at >= since, LoginAttempt.id != attempt.id)).all()
        if prior and attempt.ip_address not in set(prior):
            detect(db, "auth_new_ip", title=f"New login location for {user.username}",
                   description=f"User '{user.username}' logged in from {attempt.ip_address}, an IP not seen for "
                               f"this account in the last {rule.params.get('lookback_days')} days.",
                   resource_type="account", resource_name=user.username,
                   dedupe_key=f"{user.username}:{attempt.ip_address}",
                   details={"ip": attempt.ip_address, "known_ips": sorted(set(prior))[:10]})

    rule = get_rule(db, "auth_repeated_logins")
    if rule and rule.enabled:
        since = now - timedelta(minutes=int(rule.params.get("window_minutes", 5)))
        n = db.scalar(select(func.count(LoginAttempt.id)).where(
            LoginAttempt.user_id == user.id, LoginAttempt.success.is_(True), LoginAttempt.created_at >= since)) or 0
        if n >= int(rule.params.get("max_logins", 10)):
            detect(db, "auth_repeated_logins", title=f"{n} logins in {rule.params.get('window_minutes')} min for {user.username}",
                   description=f"Account '{user.username}' logged in {n} times within "
                               f"{rule.params.get('window_minutes')} minutes.",
                   resource_type="account", resource_name=user.username, details={"logins": n})


def is_locked(user: User) -> bool:
    lu = ensure_aware(user.locked_until)
    return bool(lu and lu > utcnow())


# ------------------------------------------------------------------ resource failures
def register_failure(db: Session, resource_type: str, resource_name: str, reason: str) -> None:
    """Record a failure and raise 'repeated service failures' when the threshold is crossed."""
    record_event(db, "resource_failure", "infrastructure", f"{resource_type} '{resource_name}': {reason}",
                 severity="medium", resource=resource_name, details={"reason": reason})
    db.commit()
    rule = get_rule(db, "service_failures")
    if not rule or not rule.enabled:
        return
    window = int(rule.params.get("failures_window", rule.params.get("window_minutes", 15)))
    n = count_recent_events(db, "resource_failure", resource_name, window)
    if n >= int(rule.params.get("failures", 3)):
        detect(db, "service_failures", title=f"Repeated failures of {resource_type} '{resource_name}'",
               description=f"{resource_type} '{resource_name}' failed {n} times within {window} minutes "
                           f"(latest: {reason}).",
               resource_type=resource_type, resource_name=resource_name, details={"failures": n})
