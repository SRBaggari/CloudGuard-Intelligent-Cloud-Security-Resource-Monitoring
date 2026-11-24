"""Demonstration scenarios that trigger CloudGuard detections on YOUR OWN local machine.

Safety: every scenario only targets this computer. The brute-force scenario refuses any API URL
that is not a loopback address, the CPU scenario stops after the given duration, and the file
scenario only touches a directory you name (it creates the directory if needed).

Usage (from the backend folder, with the venv active):
    python scripts/demo_scenarios.py bruteforce --user admin --attempts 6
    python scripts/demo_scenarios.py spray --attempts 4
    python scripts/demo_scenarios.py cpu --seconds 60
    python scripts/demo_scenarios.py fim --dir C:\\CloudGuardDemo\\site
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import multiprocessing as mp
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def _require_loopback(url: str) -> None:
    host = urlparse(url).hostname or ""
    try:
        ok = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        ok = False
    if not ok:
        sys.exit(f"Refusing to target {host!r}: demo scenarios only run against this machine (localhost).")


def _login(api: str, username: str, password: str) -> int:
    req = urllib.request.Request(
        f"{api}/api/auth/login", data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def bruteforce(args) -> None:
    """Repeated wrong passwords for one account -> 'Multiple failed login attempts' + lockout."""
    _require_loopback(args.api)
    for i in range(args.attempts):
        code = _login(args.api, args.user, f"wrong-password-{i}")
        print(f"attempt {i + 1}: HTTP {code}")
    print("Expect a HIGH 'Multiple failed login attempts' alert; the account is temporarily locked.")
    print("An administrator can unlock it under Settings -> Users -> Unlock.")


def spray(args) -> None:
    """One source failing against several accounts -> 'Suspicious access pattern'."""
    _require_loopback(args.api)
    for i in range(args.attempts):
        code = _login(args.api, f"demo-nonexistent-{i}", "wrong-password")
        print(f"account demo-nonexistent-{i}: HTTP {code}")
    print("Expect a HIGH 'Suspicious access pattern (multiple accounts from one IP)' alert.")


def _burn(stop_at: float) -> None:
    x = 0
    while time.time() < stop_at:
        x = (x * 31 + 7) % 1_000_003


def cpu(args) -> None:
    """Saturate all CPU cores for N seconds -> 'High CPU utilisation' alert."""
    n = os.cpu_count() or 2
    stop_at = time.time() + args.seconds
    print(f"Loading {n} cores for {args.seconds}s (Ctrl+C to stop early)...")
    procs = [mp.Process(target=_burn, args=(stop_at,)) for _ in range(n)]
    for p in procs:
        p.start()
    try:
        for p in procs:
            p.join()
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()
    print("Done. Expect a HIGH/CRITICAL CPU alert after the configured number of consecutive samples.")


def fim(args) -> None:
    """Create a demo site, then (after you add it in CloudGuard) modify / add / delete files."""
    root = Path(args.dir).expanduser().resolve()
    if args.step == "create":
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "index.html").write_text("<h1>Welcome</h1>\n")
        (root / "config" / "app.ini").write_text("debug=false\n")
        (root / "robots.txt").write_text("User-agent: *\n")
        print(f"Created {root}. Add it under File Integrity, then run:  fim --dir \"{root}\" --step tamper")
    else:
        (root / "config" / "app.ini").write_text("debug=true\n")
        (root / "unexpected-admin.html").write_text("<form>login</form>\n")
        (root / "robots.txt").unlink(missing_ok=True)
        print("Modified app.ini, added unexpected-admin.html, deleted robots.txt. Click 'Scan' in File Integrity.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bruteforce")
    b.add_argument("--api", default="http://127.0.0.1:8000")
    b.add_argument("--user", default="admin")
    b.add_argument("--attempts", type=int, default=6)
    b.set_defaults(fn=bruteforce)
    s = sub.add_parser("spray")
    s.add_argument("--api", default="http://127.0.0.1:8000")
    s.add_argument("--attempts", type=int, default=4)
    s.set_defaults(fn=spray)
    c = sub.add_parser("cpu")
    c.add_argument("--seconds", type=int, default=60)
    c.set_defaults(fn=cpu)
    f = sub.add_parser("fim")
    f.add_argument("--dir", required=True)
    f.add_argument("--step", choices=["create", "tamper"], default="create")
    f.set_defaults(fn=fim)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
