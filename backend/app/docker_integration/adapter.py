"""Docker Engine adapters.

RealDockerAdapter talks to the local Docker Engine via the Docker Python SDK.
MockDockerAdapter is an explicitly labelled in-memory demo/test adapter (INTEGRATION_MODE=mock).
The Docker socket is never exposed; only the whitelisted operations below are available.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("cloudguard.docker")

CONTAINER_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


class DockerUnavailable(Exception):
    pass


class DockerOperationError(Exception):
    pass


def validate_container_ref(ref: str) -> str:
    if not CONTAINER_ID_RE.match(ref or ""):
        raise ValueError("Invalid container identifier")
    return ref


def _cpu_percent(stats: dict) -> float:
    try:
        cpu = stats["cpu_stats"]
        pre = stats["precpu_stats"]
        cpu_delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        sys_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        online = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or [1])
        if sys_delta > 0 and cpu_delta >= 0:
            return round(cpu_delta / sys_delta * online * 100.0, 2)
    except (KeyError, TypeError):
        pass
    return 0.0


def parse_stats(stats: dict) -> dict[str, Any]:
    mem = stats.get("memory_stats") or {}
    usage = int(mem.get("usage") or 0)
    cache = int((mem.get("stats") or {}).get("inactive_file") or (mem.get("stats") or {}).get("cache") or 0)
    usage = max(0, usage - cache)
    limit = int(mem.get("limit") or 0)
    rx = tx = 0
    for n in (stats.get("networks") or {}).values():
        rx += int(n.get("rx_bytes", 0))
        tx += int(n.get("tx_bytes", 0))
    return {
        "cpu_percent": _cpu_percent(stats),
        "memory_usage": usage,
        "memory_limit": limit,
        "memory_percent": round(usage / limit * 100.0, 2) if limit else 0.0,
        "net_rx_bytes": rx,
        "net_tx_bytes": tx,
    }


def _summarise(attrs: dict) -> dict[str, Any]:
    state = attrs.get("State") or {}
    health = (state.get("Health") or {}).get("Status") or "none"
    name = (attrs.get("Name") or "").lstrip("/")
    return {
        "id": attrs.get("Id", ""),
        "short_id": attrs.get("Id", "")[:12],
        "name": name,
        "image": (attrs.get("Config") or {}).get("Image", ""),
        "status": state.get("Status", "unknown"),
        "health": health,
        "restart_count": int(attrs.get("RestartCount") or 0),
        "exit_code": state.get("ExitCode"),
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "networks": sorted(((attrs.get("NetworkSettings") or {}).get("Networks") or {}).keys()),
    }


class RealDockerAdapter:
    mode = "real"

    RETRY_SECONDS = 10

    def __init__(self) -> None:
        self._client = None
        self._lock = threading.Lock()
        self._error = ""
        self._failed_at = 0.0

    def _get(self):
        with self._lock:
            if self._client is None and self._failed_at and time.monotonic() - self._failed_at < self.RETRY_SECONDS:
                raise DockerUnavailable(
                    "Docker Engine is not reachable. Install Docker Desktop / Docker Engine and make sure it is running.")
            if self._client is not None:
                try:
                    self._client.ping()
                    return self._client
                except Exception:
                    self._client = None
            try:
                import docker  # type: ignore
                client = docker.from_env(timeout=5)
                client.ping()
                self._client = client
                self._error = ""
                return client
            except Exception as e:  # docker not installed / daemon down
                self._error = str(e)
                self._failed_at = time.monotonic()
                raise DockerUnavailable(
                    "Docker Engine is not reachable. Install Docker Desktop / Docker Engine and make sure it is running."
                ) from e

    def status(self) -> dict[str, Any]:
        try:
            c = self._get()
            v = c.version()
            info = c.info()
            return {"available": True, "mode": self.mode, "version": v.get("Version"),
                    "api_version": v.get("ApiVersion"), "os": info.get("OperatingSystem"),
                    "containers": info.get("Containers"), "images": info.get("Images")}
        except DockerUnavailable as e:
            return {"available": False, "mode": self.mode, "message": str(e), "error": self._error[:300]}

    def list_containers(self) -> list[dict[str, Any]]:
        c = self._get()
        return [_summarise(x.attrs) for x in c.containers.list(all=True)]

    def inspect(self, ref: str) -> dict[str, Any]:
        c = self._get()
        try:
            cont = c.containers.get(validate_container_ref(ref))
        except Exception as e:
            raise DockerOperationError(f"Container not found: {ref}") from e
        a = cont.attrs
        cfg = a.get("Config") or {}
        host = a.get("HostConfig") or {}
        return {
            **_summarise(a),
            "created": a.get("Created"),
            "command": cfg.get("Cmd"),
            "entrypoint": cfg.get("Entrypoint"),
            # environment variable *names* only; values may contain secrets
            "env_keys": sorted({e.split("=", 1)[0] for e in (cfg.get("Env") or [])}),
            "labels": cfg.get("Labels") or {},
            "ports": (a.get("NetworkSettings") or {}).get("Ports") or {},
            "networks": list(((a.get("NetworkSettings") or {}).get("Networks") or {}).keys()),
            "mounts": [{"source": m.get("Source"), "destination": m.get("Destination"), "mode": m.get("Mode")}
                       for m in a.get("Mounts") or []],
            "restart_policy": host.get("RestartPolicy"),
            "memory_limit": host.get("Memory"),
            "nano_cpus": host.get("NanoCpus"),
            "privileged": host.get("Privileged", False),
        }

    def stats(self, ref: str) -> dict[str, Any]:
        c = self._get()
        cont = c.containers.get(validate_container_ref(ref))
        return parse_stats(cont.stats(stream=False))

    def action(self, ref: str, action: str) -> None:
        if action not in ("start", "stop", "restart"):
            raise ValueError("Unsupported action")
        c = self._get()
        try:
            cont = c.containers.get(validate_container_ref(ref))
            if action == "stop":
                cont.stop(timeout=10)
            else:
                getattr(cont, action)()
        except Exception as e:
            raise DockerOperationError(f"Failed to {action} container: {e}") from e

    def logs(self, ref: str, tail: int) -> str:
        c = self._get()
        cont = c.containers.get(validate_container_ref(ref))
        return cont.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")


class MockDockerAdapter:
    """DEMO/TEST ONLY - deterministic in-memory containers. Clearly labelled as mock in the API/UI."""

    mode = "mock"

    def __init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.containers: dict[str, dict[str, Any]] = {}
        for i, (name, image, status, health) in enumerate([
            ("demo-web", "nginx:alpine", "running", "healthy"),
            ("demo-api", "python:3.12-slim", "running", "none"),
            ("demo-db", "postgres:16", "exited", "none"),
        ]):
            cid = f"{i + 1:02d}" + "a1b2c3d4e5f6" * 5
            self.containers[cid] = {
                "id": cid, "short_id": cid[:12], "name": name, "image": image, "status": status,
                "health": health, "restart_count": 0, "exit_code": 0, "started_at": now, "finished_at": None,
                "networks": ["bridge"] if name == "demo-db" else ["bridge", "demo-app-net"],
            }
        self.stats_map: dict[str, dict[str, Any]] = {
            cid: {"cpu_percent": 3.5 * (i + 1), "memory_usage": 50_000_000 * (i + 1), "memory_limit": 1_000_000_000,
                  "memory_percent": 5.0 * (i + 1), "net_rx_bytes": 1_000_000 * (i + 1), "net_tx_bytes": 400_000 * (i + 1)}
            for i, cid in enumerate(self.containers)
        }

    def _find(self, ref: str) -> dict[str, Any]:
        validate_container_ref(ref)
        for c in self.containers.values():
            if c["id"] == ref or c["id"].startswith(ref) or c["name"] == ref:
                return c
        raise DockerOperationError(f"Container not found: {ref}")

    def status(self) -> dict[str, Any]:
        return {"available": True, "mode": self.mode, "version": "mock", "message": "Demo mode: simulated containers"}

    def list_containers(self) -> list[dict[str, Any]]:
        return [dict(c) for c in self.containers.values()]

    def inspect(self, ref: str) -> dict[str, Any]:
        c = self._find(ref)
        return {**c, "created": c["started_at"], "command": ["demo"], "entrypoint": None, "env_keys": ["PATH"],
                "labels": {"cloudguard.demo": "true"}, "ports": {}, "networks": ["bridge"], "mounts": [],
                "restart_policy": {"Name": "no"}, "memory_limit": 0, "nano_cpus": 0, "privileged": False}

    def stats(self, ref: str) -> dict[str, Any]:
        c = self._find(ref)
        if c["status"] != "running":
            return {"cpu_percent": 0.0, "memory_usage": 0, "memory_limit": 0, "memory_percent": 0.0,
                    "net_rx_bytes": 0, "net_tx_bytes": 0}
        return dict(self.stats_map.get(c["id"], {}))

    def action(self, ref: str, action: str) -> None:
        if action not in ("start", "stop", "restart"):
            raise ValueError("Unsupported action")
        c = self._find(ref)
        c["status"] = "exited" if action == "stop" else "running"

    def logs(self, ref: str, tail: int) -> str:
        c = self._find(ref)
        lines = [f"2026-01-01T00:00:{i:02d}Z [demo] {c['name']} log line {i}" for i in range(min(tail, 20))]
        return "\n".join(lines)


_adapter = None


def get_docker_adapter():
    global _adapter
    if _adapter is None:
        from app.core.config import get_settings
        _adapter = MockDockerAdapter() if get_settings().integration_mode == "mock" else RealDockerAdapter()
    return _adapter


def set_docker_adapter(adapter) -> None:
    global _adapter
    _adapter = adapter
