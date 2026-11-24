"""VirtualBox integration through a safe, validated VBoxManage wrapper.

- Only whitelisted sub-commands are executed.
- Arguments are passed as a list (no shell), VM identifiers are validated.
- Every call has a timeout.
If VirtualBox is not installed, `status()` returns available=False with setup guidance.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
LIST_RE = re.compile(r'^"(?P<name>.*)"\s+\{(?P<uuid>[0-9a-fA-F-]{36})\}$')

SETUP_MESSAGE = (
    "VirtualBox was not found. Install Oracle VirtualBox (free) from https://www.virtualbox.org/ and make sure "
    "VBoxManage is on PATH, or set VBOXMANAGE_PATH in backend/.env. The rest of CloudGuard works without it."
)

ALLOWED = {
    ("list", "vms"), ("list", "runningvms"), ("showvminfo",), ("startvm",), ("controlvm",), ("--version",),
}


class VBoxUnavailable(Exception):
    pass


class VBoxError(Exception):
    pass


def validate_uuid(vm_uuid: str) -> str:
    if not UUID_RE.match(vm_uuid or ""):
        raise ValueError("Invalid VM identifier (UUID expected)")
    return vm_uuid.lower()


def find_vboxmanage(configured: str = "") -> str | None:
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("VBoxManage") or shutil.which("vboxmanage")
    if found:
        return found
    candidates = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("VBOX_MSI_INSTALL_PATH", "")):
            if base:
                candidates += [Path(base) / "Oracle" / "VirtualBox" / "VBoxManage.exe", Path(base) / "VBoxManage.exe"]
    else:
        candidates += [Path("/usr/bin/VBoxManage"), Path("/usr/local/bin/VBoxManage"),
                       Path("/Applications/VirtualBox.app/Contents/MacOS/VBoxManage")]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def parse_machinereadable(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip().strip('"')] = v.strip().strip('"')
    return out


class RealVBoxAdapter:
    mode = "real"

    def __init__(self, configured_path: str = "") -> None:
        self.path = find_vboxmanage(configured_path)

    def _run(self, args: list[str], timeout: int = 30) -> str:
        if not self.path:
            raise VBoxUnavailable(SETUP_MESSAGE)
        head = tuple(args[:2]) if args[:1] == ["list"] else tuple(args[:1])
        if head not in ALLOWED:
            raise VBoxError("Command not permitted")
        try:
            proc = subprocess.run([self.path, *args], capture_output=True, text=True, timeout=timeout, shell=False,
                                  check=False)
        except subprocess.TimeoutExpired as e:
            raise VBoxError("VBoxManage timed out") from e
        except OSError as e:
            raise VBoxUnavailable(f"Unable to execute VBoxManage: {e}") from e
        if proc.returncode != 0:
            raise VBoxError((proc.stderr or proc.stdout or "VBoxManage failed").strip()[:500])
        return proc.stdout

    def status(self) -> dict[str, Any]:
        if not self.path:
            return {"available": False, "mode": self.mode, "message": SETUP_MESSAGE}
        try:
            return {"available": True, "mode": self.mode, "version": self._run(["--version"]).strip(), "path": self.path}
        except (VBoxError, VBoxUnavailable) as e:
            return {"available": False, "mode": self.mode, "message": str(e)}

    def list_vms(self) -> list[dict[str, Any]]:
        vms = []
        for line in self._run(["list", "vms"]).splitlines():
            m = LIST_RE.match(line.strip())
            if m:
                vms.append(self.info(m.group("uuid")))
        return vms

    def info(self, vm_uuid: str) -> dict[str, Any]:
        raw = parse_machinereadable(self._run(["showvminfo", validate_uuid(vm_uuid), "--machinereadable"]))
        return {
            "uuid": raw.get("UUID", vm_uuid).lower(),
            "name": raw.get("name", ""),
            "state": raw.get("VMState", "unknown"),
            "os_type": raw.get("ostype", ""),
            "memory_mb": int(raw.get("memory", 0) or 0),
            "cpus": int(raw.get("cpus", 0) or 0),
            "config": {k: raw[k] for k in (
                "VMStateChangeTime", "firmware", "vram", "graphicscontroller", "nic1", "macaddress1",
                "storagecontrollername0", "CfgFile", "description", "pagefusion", "hwvirtex", "nestedpaging",
                "longmode", "chipset", "clipboard", "draganddrop") if k in raw},
        }

    def start(self, vm_uuid: str) -> None:
        self._run(["startvm", validate_uuid(vm_uuid), "--type", "headless"], timeout=90)

    def stop(self, vm_uuid: str, force: bool = False) -> None:
        self._run(["controlvm", validate_uuid(vm_uuid), "poweroff" if force else "acpipowerbutton"], timeout=60)


class MockVBoxAdapter:
    """DEMO/TEST ONLY - deterministic in-memory VMs, labelled as mock."""

    mode = "mock"

    def __init__(self) -> None:
        self.vms = {
            "11111111-2222-3333-4444-555555555555": {
                "uuid": "11111111-2222-3333-4444-555555555555", "name": "demo-ubuntu-server", "state": "running",
                "os_type": "Ubuntu_64", "memory_mb": 2048, "cpus": 2, "config": {"firmware": "BIOS", "nic1": "nat"}},
            "66666666-7777-8888-9999-000000000000": {
                "uuid": "66666666-7777-8888-9999-000000000000", "name": "demo-windows-lab", "state": "poweroff",
                "os_type": "Windows10_64", "memory_mb": 4096, "cpus": 2, "config": {"firmware": "EFI", "nic1": "nat"}},
        }

    def status(self) -> dict[str, Any]:
        return {"available": True, "mode": self.mode, "version": "mock", "message": "Demo mode: simulated VMs"}

    def list_vms(self) -> list[dict[str, Any]]:
        return [dict(v) for v in self.vms.values()]

    def info(self, vm_uuid: str) -> dict[str, Any]:
        v = self.vms.get(validate_uuid(vm_uuid))
        if not v:
            raise VBoxError("VM not found")
        return dict(v)

    def start(self, vm_uuid: str) -> None:
        self.vms[validate_uuid(vm_uuid)]["state"] = "running"

    def stop(self, vm_uuid: str, force: bool = False) -> None:
        self.vms[validate_uuid(vm_uuid)]["state"] = "poweroff"


_adapter = None


def get_vbox_adapter():
    global _adapter
    if _adapter is None:
        from app.core.config import get_settings
        s = get_settings()
        _adapter = MockVBoxAdapter() if s.integration_mode == "mock" else RealVBoxAdapter(s.vboxmanage_path)
    return _adapter


def set_vbox_adapter(adapter) -> None:
    global _adapter
    _adapter = adapter
