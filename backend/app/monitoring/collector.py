"""Real local system metrics collection using psutil (no simulated values)."""
from __future__ import annotations

import os
import platform
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any

import psutil


def system_disk_path() -> str:
    if os.name == "nt":
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


def primary_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))  # no packet is sent for UDP connect
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


class SystemCollector:
    """Collects host metrics. Keeps previous network counters to compute rates."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_net: tuple[float, int, int] | None = None
        self._procs: dict[int, psutil.Process] = {}
        psutil.cpu_percent(interval=None)  # prime the CPU counter

    # ------------------------------------------------------------ metrics
    def collect(self) -> dict[str, Any]:
        with self._lock:
            cpu = psutil.cpu_percent(interval=None)
            vm = psutil.virtual_memory()
            disk = psutil.disk_usage(system_disk_path())
            net = psutil.net_io_counters()
            now = time.monotonic()
            send_rate = recv_rate = 0.0
            if self._last_net is not None:
                dt = now - self._last_net[0]
                if dt > 0:
                    send_rate = max(0.0, (net.bytes_sent - self._last_net[1]) / dt)
                    recv_rate = max(0.0, (net.bytes_recv - self._last_net[2]) / dt)
            self._last_net = (now, net.bytes_sent, net.bytes_recv)
            return {
                "timestamp": datetime.now(timezone.utc),
                "cpu_percent": float(cpu),
                "memory_percent": float(vm.percent),
                "memory_used": int(vm.used),
                "memory_total": int(vm.total),
                "disk_percent": float(disk.percent),
                "disk_used": int(disk.used),
                "disk_total": int(disk.total),
                "net_bytes_sent": int(net.bytes_sent),
                "net_bytes_recv": int(net.bytes_recv),
                "net_send_rate": float(send_rate),
                "net_recv_rate": float(recv_rate),
                "process_count": len(psutil.pids()),
                "connection_count": self.connection_count(),
            }

    @staticmethod
    def connection_count() -> int:
        try:
            return len(psutil.net_connections(kind="inet"))
        except (psutil.AccessDenied, PermissionError, OSError):
            return 0

    # ------------------------------------------------------------ processes
    def processes(self, limit: int = 25, sort: str = "cpu") -> list[dict[str, Any]]:
        """Top processes. Process objects are cached so cpu_percent reflects usage since last call."""
        with self._lock:
            out = []
            current = set()
            cpu_count = psutil.cpu_count() or 1
            for p in psutil.process_iter(["pid", "name", "username", "status", "create_time", "memory_percent", "memory_info"]):
                pid = p.info["pid"]
                if pid == 0:  # 'System Idle Process' (Windows) / kernel swapper - not a real workload
                    continue
                current.add(pid)
                cached = self._procs.setdefault(pid, p)
                try:
                    cpu = cached.cpu_percent(interval=None) / cpu_count
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                mi = p.info.get("memory_info")
                out.append({
                    "pid": pid,
                    "name": p.info.get("name") or "?",
                    "username": p.info.get("username") or "",
                    "status": p.info.get("status") or "",
                    "cpu_percent": round(cpu, 2),
                    "memory_percent": round(p.info.get("memory_percent") or 0.0, 2),
                    "memory_rss": int(mi.rss) if mi else 0,
                    "started_at": datetime.fromtimestamp(p.info["create_time"], timezone.utc).isoformat()
                    if p.info.get("create_time") else None,
                })
            for pid in list(self._procs):
                if pid not in current:
                    self._procs.pop(pid, None)
        key = "memory_percent" if sort == "memory" else "cpu_percent"
        out.sort(key=lambda x: x[key], reverse=True)
        return out[:limit]

    @staticmethod
    def process_names() -> set[str]:
        names = set()
        for p in psutil.process_iter(["name"]):
            if p.info.get("name"):
                names.add(p.info["name"])
        return names

    # ------------------------------------------------------------ info
    @staticmethod
    def system_info() -> dict[str, Any]:
        boot = psutil.boot_time()
        freq = None
        try:
            f = psutil.cpu_freq()
            freq = round(f.current, 0) if f else None
        except (NotImplementedError, OSError, FileNotFoundError):
            pass
        return {
            "hostname": socket.gethostname(),
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "cpu_physical_cores": psutil.cpu_count(logical=False),
            "cpu_logical_cores": psutil.cpu_count(logical=True),
            "cpu_freq_mhz": freq,
            "memory_total": psutil.virtual_memory().total,
            "boot_time": datetime.fromtimestamp(boot, timezone.utc).isoformat(),
            "uptime_seconds": int(time.time() - boot),
            "ip_address": primary_ip(),
            "python_version": platform.python_version(),
        }

    @staticmethod
    def network_interfaces() -> list[dict[str, Any]]:
        stats = psutil.net_if_stats()
        counters = psutil.net_io_counters(pernic=True)
        addrs = psutil.net_if_addrs()
        out = []
        for name, st in stats.items():
            c = counters.get(name)
            ipv4 = [a.address for a in addrs.get(name, []) if a.family == socket.AF_INET]
            out.append({
                "name": name, "is_up": st.isup, "speed_mbps": st.speed, "mtu": st.mtu,
                "ipv4": ipv4,
                "bytes_sent": c.bytes_sent if c else 0, "bytes_recv": c.bytes_recv if c else 0,
                "errors_in": c.errin if c else 0, "errors_out": c.errout if c else 0,
            })
        return out

    @staticmethod
    def connection_summary(limit: int = 15) -> dict[str, Any]:
        try:
            conns = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, PermissionError, OSError):
            return {"available": False, "reason": "Insufficient permissions to list connections", "by_status": {}, "top_remote": [], "listening": []}
        by_status: dict[str, int] = {}
        remotes: dict[str, int] = {}
        listening = set()
        for c in conns:
            by_status[c.status] = by_status.get(c.status, 0) + 1
            if c.raddr:
                remotes[c.raddr.ip] = remotes.get(c.raddr.ip, 0) + 1
            if c.status == psutil.CONN_LISTEN and c.laddr:
                listening.add(c.laddr.port)
        top = sorted(remotes.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        return {
            "available": True, "total": len(conns), "by_status": by_status,
            "top_remote": [{"ip": ip, "connections": n} for ip, n in top],
            "listening": sorted(listening)[:100],
        }


collector = SystemCollector()
