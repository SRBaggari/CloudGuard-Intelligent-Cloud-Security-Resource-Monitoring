"""Process table scanning, executed in a dedicated worker process.

Enumerating every process (especially on Windows, where each per-process query opens a handle)
takes 1-2 seconds of mostly-Python work. Running it in a thread of the API process starves other
request threads through GIL convoying, so the scan runs in a separate, persistent process with its
own interpreter. The module only depends on psutil to keep worker start-up light.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psutil

# pid -> Process, kept between calls so cpu_percent() measures usage since the previous scan
_procs: dict[int, psutil.Process] = {}


def top_processes(limit: int = 25, sort: str = "cpu") -> list[dict[str, Any]]:
    cpu_count = psutil.cpu_count() or 1
    total_mem = psutil.virtual_memory().total or 1
    current, rows = set(), []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        pid = p.info["pid"]
        if pid == 0:  # 'System Idle Process' (Windows) / kernel swapper - not a real workload
            continue
        current.add(pid)
        cached = _procs.setdefault(pid, p)
        try:
            cpu = cached.cpu_percent(interval=None) / cpu_count
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            cpu = 0.0
        mi = p.info.get("memory_info")
        rows.append({"pid": pid, "name": p.info.get("name") or "?", "cpu_percent": round(cpu, 2),
                     "memory_rss": int(mi.rss) if mi else 0})
    for pid in list(_procs):
        if pid not in current:
            _procs.pop(pid, None)

    key = "memory_rss" if sort == "memory" else "cpu_percent"
    top = sorted(rows, key=lambda x: x[key], reverse=True)[:limit]
    for row in top:  # expensive details only for the rows that are displayed
        row["memory_percent"] = round(row["memory_rss"] / total_mem * 100, 2)
        row["username"], row["started_at"], row["status"] = "", None, ""
        proc = _procs.get(row["pid"])
        if proc is None:
            continue
        try:
            with proc.oneshot():
                row["status"] = proc.status()
                row["started_at"] = datetime.fromtimestamp(proc.create_time(), timezone.utc).isoformat()
                row["username"] = proc.username()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            pass
    return top
