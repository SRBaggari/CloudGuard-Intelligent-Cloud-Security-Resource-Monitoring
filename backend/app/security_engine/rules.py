"""Default, transparent detection rules.

Each rule has an explicit, human-readable detection condition and tunable params.
CloudGuard does NOT claim to detect malware; it detects observable, rule-defined conditions.
"""
from __future__ import annotations

DEFAULT_RULES: list[dict] = [
    # ---------------- Authentication
    {
        "key": "auth_bruteforce", "name": "Multiple failed login attempts", "category": "authentication",
        "severity": "high",
        "description": "Repeated failed logins against a single account, typical of password guessing.",
        "condition": "failed logins for one account >= {max_failures} within {window_minutes} min",
        "params": {"max_failures": 5, "window_minutes": 10, "lockout_minutes": 15},
        "recommended_response": "Verify with the account owner, keep the temporary lockout in place, "
                                "review source IPs and enforce a strong password.",
    },
    {
        "key": "auth_ip_spray", "name": "Suspicious access pattern (multiple accounts from one IP)",
        "category": "authentication", "severity": "high",
        "description": "One client IP failing logins across several different accounts (password spraying pattern).",
        "condition": "failed logins from one IP across >= {distinct_accounts} accounts within {window_minutes} min",
        "params": {"distinct_accounts": 3, "window_minutes": 10},
        "recommended_response": "Block or rate-limit the source IP at the firewall and review all targeted accounts.",
    },
    {
        "key": "auth_new_ip", "name": "Unusual authentication activity (new source IP)",
        "category": "authentication", "severity": "low",
        "description": "Successful login for a user from an IP address never used by that user before.",
        "condition": "successful login from IP not in user's previous {lookback_days}-day history",
        "params": {"lookback_days": 30},
        "recommended_response": "Confirm the login with the user. If not recognised, reset the password and revoke sessions.",
    },
    {
        "key": "auth_repeated_logins", "name": "Repeated login activity", "category": "authentication",
        "severity": "medium",
        "description": "Unusually many successful logins for one account in a short period (possible token or session abuse).",
        "condition": "successful logins for one account >= {max_logins} within {window_minutes} min",
        "params": {"max_logins": 10, "window_minutes": 5},
        "recommended_response": "Check for automated scripts using the account and rotate credentials if unexpected.",
    },
    # ---------------- System
    {
        "key": "cpu_threshold", "name": "High CPU utilisation", "category": "system", "severity": "high",
        "description": "Host CPU utilisation above threshold for consecutive samples.",
        "condition": "CPU >= {warning}% (critical >= {critical}%) for {consecutive} consecutive samples",
        "params": {"warning": 85, "critical": 95, "consecutive": 3},
        "recommended_response": "Identify the top CPU processes in the Monitoring page and stop or throttle unexpected workloads.",
    },
    {
        "key": "memory_threshold", "name": "High memory utilisation", "category": "system", "severity": "high",
        "description": "Host RAM utilisation above threshold for consecutive samples.",
        "condition": "RAM >= {warning}% (critical >= {critical}%) for {consecutive} consecutive samples",
        "params": {"warning": 85, "critical": 95, "consecutive": 3},
        "recommended_response": "Check memory-heavy processes/containers, look for leaks and consider adding capacity.",
    },
    {
        "key": "disk_threshold", "name": "Disk space critically low", "category": "infrastructure", "severity": "high",
        "description": "System disk usage above threshold.",
        "condition": "Disk >= {warning}% (critical >= {critical}%)",
        "params": {"warning": 90, "critical": 97, "consecutive": 1},
        "recommended_response": "Remove unused files, logs, Docker images (docker image prune) or expand the volume.",
    },
    {
        "key": "process_spike", "name": "Unexpected process activity", "category": "system", "severity": "medium",
        "description": "Sudden increase in the number of running processes between samples.",
        "condition": "process count increased by >= {increase} since previous sample",
        "params": {"increase": 60},
        "recommended_response": "Review newly started processes in the process list; investigate unknown executables.",
    },
    {
        "key": "process_watchlist", "name": "Watch-listed process running", "category": "system", "severity": "high",
        "description": "A process whose name is on the administrator-configured watchlist is running.",
        "condition": "running process name matches Settings > process watchlist",
        "params": {},
        "recommended_response": "Confirm whether the process is authorised; terminate it and investigate its origin if not.",
    },
    {
        "key": "network_connections", "name": "Unusual network connection volume", "category": "network",
        "severity": "medium",
        "description": "Number of open inet connections above threshold.",
        "condition": "open connections >= {max_connections}",
        "params": {"max_connections": 800},
        "recommended_response": "Inspect connections (netstat/ss) for unexpected remote hosts or scanning behaviour.",
    },
    {
        "key": "network_traffic", "name": "Abnormal network throughput", "category": "network", "severity": "medium",
        "description": "Sustained upload or download rate above threshold.",
        "condition": "upload or download >= {mbps} MB/s for {consecutive} consecutive samples",
        "params": {"mbps": 50, "consecutive": 3},
        "recommended_response": "Identify the process generating traffic; unexpected uploads may indicate data exfiltration.",
    },
    {
        "key": "fim_change", "name": "Monitored file changed", "category": "integrity", "severity": "medium",
        "description": "A file in a monitored directory was modified, created or deleted versus the baseline.",
        "condition": "SHA-256 differs from baseline, or file added/removed",
        "params": {"deleted_severity": "high"},
        "recommended_response": "Verify the change was authorised. If so, update the baseline; otherwise restore from backup.",
    },
    # ---------------- Containers
    {
        "key": "container_unexpected_exit", "name": "Unexpected container termination", "category": "container",
        "severity": "high",
        "description": "A running container stopped without being stopped through CloudGuard.",
        "condition": "container state running -> exited/dead without a CloudGuard stop action",
        "params": {},
        "recommended_response": "Inspect container logs for crash causes (OOM, application error) and restart if appropriate.",
    },
    {
        "key": "container_unhealthy", "name": "Unhealthy container", "category": "container", "severity": "high",
        "description": "Docker HEALTHCHECK reports the container as unhealthy.",
        "condition": "container health status == unhealthy",
        "params": {},
        "recommended_response": "Review the health check output and application logs; restart or redeploy the container.",
    },
    {
        "key": "container_restart", "name": "Unexpected container restart", "category": "container",
        "severity": "medium",
        "description": "The Docker restart counter of a container increased.",
        "condition": "RestartCount increased since last poll",
        "params": {},
        "recommended_response": "A restart loop often means a crashing process; check logs and resource limits.",
    },
    {
        "key": "container_resource", "name": "Abnormal container resource usage", "category": "container",
        "severity": "medium",
        "description": "Container CPU or memory usage above threshold.",
        "condition": "container CPU >= {cpu}% or memory >= {memory}% of its limit",
        "params": {"cpu": 90, "memory": 90},
        "recommended_response": "Set resource limits (--cpus/--memory) and investigate unexpected load inside the container.",
    },
    # ---------------- VMs / infrastructure
    {
        "key": "vm_unexpected_stop", "name": "Unexpected VM shutdown", "category": "virtualization",
        "severity": "high",
        "description": "A running VirtualBox VM stopped or aborted without a CloudGuard action.",
        "condition": "VM state running -> poweroff/aborted without a CloudGuard stop action",
        "params": {},
        "recommended_response": "Check the VM logs in VirtualBox (Show Log) and host resources before restarting.",
    },
    {
        "key": "service_failures", "name": "Repeated service failures", "category": "infrastructure",
        "severity": "high",
        "description": "The same resource failed (crash/restart/unexpected stop) repeatedly.",
        "condition": ">= {failures} failures of one resource within {window_minutes} min",
        "params": {"failures": 3, "window_minutes": 15},
        "recommended_response": "Treat as a service outage: stop the restart loop, collect logs, fix the root cause.",
    },
    {
        "key": "ml_anomaly", "name": "Anomalous resource behaviour (ML)", "category": "anomaly", "severity": "medium",
        "description": "Isolation Forest model scored the latest metrics as outside learned normal behaviour.",
        "condition": "Isolation Forest predicts outlier for {consecutive} consecutive samples",
        "params": {"consecutive": 2},
        "recommended_response": "Review the anomaly explanation (which metrics deviate) and correlate with recent activity.",
    },
]


def render_condition(template: str, params: dict) -> str:
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template
