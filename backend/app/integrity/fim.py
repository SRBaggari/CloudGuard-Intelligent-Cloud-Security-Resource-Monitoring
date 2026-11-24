"""File Integrity Monitoring (SHA-256 baselines).

Only directories explicitly added by an administrator are monitored. Sensitive system
locations are blocked so CloudGuard never scans them by default or by accident.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.models import FileIntegrityChange, FileIntegrityRecord, MonitoredDirectory
from app.services.alerts import detect, get_rule

MAX_FILES = 20_000
CHUNK = 1024 * 1024


def _blocked_roots() -> list[Path]:
    roots: list[str] = []
    if os.name == "nt":
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        roots += [sysroot, os.environ.get("ProgramFiles", r"C:\Program Files"),
                  os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                  os.environ.get("ProgramData", r"C:\ProgramData"), r"C:\$Recycle.Bin", r"C:\System Volume Information"]
    else:
        roots += ["/etc", "/proc", "/sys", "/dev", "/boot", "/root", "/var/lib", "/usr", "/bin", "/sbin", "/lib", "/run"]
    home = Path.home()
    roots += [str(home / ".ssh"), str(home / ".gnupg"), str(home / "AppData")]
    return [Path(r).resolve() for r in roots if r]


class PathNotAllowed(ValueError):
    pass


def validate_directory(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise PathNotAllowed("Path must be absolute")
    try:
        p = p.resolve(strict=True)
    except (FileNotFoundError, OSError) as e:
        raise PathNotAllowed("Directory does not exist") from e
    if not p.is_dir():
        raise PathNotAllowed("Path is not a directory")
    if p.parent == p:
        raise PathNotAllowed("Monitoring an entire drive / filesystem root is not allowed")
    for b in _blocked_roots():
        if p == b or b in p.parents:
            raise PathNotAllowed(f"Monitoring sensitive system location '{b}' is not allowed")
        if p in b.parents:
            raise PathNotAllowed(f"Directory contains sensitive location '{b}'; choose a more specific folder")
    return p


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk(root: Path, recursive: bool) -> dict[str, tuple[str, int, datetime]]:
    result: dict[str, tuple[str, int, datetime]] = {}
    iterator = root.rglob("*") if recursive else root.glob("*")
    for f in iterator:
        if len(result) >= MAX_FILES:
            break
        try:
            if not f.is_file() or f.is_symlink():
                continue
            st = f.stat()
            result[str(f)] = (sha256_file(f), st.st_size, datetime.fromtimestamp(st.st_mtime, timezone.utc))
        except (PermissionError, OSError):
            continue
    return result


def create_baseline(db: Session, directory: MonitoredDirectory) -> int:
    root = validate_directory(directory.path)
    files = _walk(root, directory.recursive)
    db.execute(delete(FileIntegrityRecord).where(FileIntegrityRecord.directory_id == directory.id))
    now = utcnow()
    for path, (digest, size, mtime) in files.items():
        db.add(FileIntegrityRecord(directory_id=directory.id, file_path=path, sha256=digest, size=size,
                                   modified_at=mtime, status="baseline", last_checked_at=now))
    directory.baseline_at = now
    directory.last_scan_at = now
    db.commit()
    return len(files)


def scan_directory(db: Session, directory: MonitoredDirectory) -> dict:
    """Compare the directory with its baseline and record changes + alerts."""
    if directory.baseline_at is None:
        n = create_baseline(db, directory)
        return {"directory": directory.path, "baseline_created": True, "files": n, "modified": 0, "new": 0, "deleted": 0}
    root = validate_directory(directory.path)
    current = _walk(root, directory.recursive)
    records = {r.file_path: r for r in db.scalars(
        select(FileIntegrityRecord).where(FileIntegrityRecord.directory_id == directory.id)).all()}
    now = utcnow()
    changes: list[FileIntegrityChange] = []

    for path, (digest, size, mtime) in current.items():
        rec = records.get(path)
        if rec is None:
            db.add(FileIntegrityRecord(directory_id=directory.id, file_path=path, sha256=digest, size=size,
                                       modified_at=mtime, status="new", last_checked_at=now))
            changes.append(FileIntegrityChange(directory_id=directory.id, file_path=path, change_type="new",
                                               new_hash=digest, detected_at=now))
            continue
        if rec.status == "deleted":  # file re-appeared
            changes.append(FileIntegrityChange(directory_id=directory.id, file_path=path, change_type="new",
                                               old_hash=rec.sha256, new_hash=digest, detected_at=now))
            rec.status = "new"
        elif rec.sha256 != digest:
            changes.append(FileIntegrityChange(directory_id=directory.id, file_path=path, change_type="modified",
                                               old_hash=rec.sha256, new_hash=digest, detected_at=now))
            rec.status = "modified"
        rec.sha256, rec.size, rec.modified_at, rec.last_checked_at = digest, size, mtime, now

    for path, rec in records.items():
        if path not in current and rec.status != "deleted":
            changes.append(FileIntegrityChange(directory_id=directory.id, file_path=path, change_type="deleted",
                                               old_hash=rec.sha256, detected_at=now))
            rec.status = "deleted"
            rec.last_checked_at = now

    for c in changes:
        db.add(c)
    directory.last_scan_at = now
    db.commit()

    summary = {"directory": directory.path, "baseline_created": False, "files": len(current),
               "modified": sum(c.change_type == "modified" for c in changes),
               "new": sum(c.change_type == "new" for c in changes),
               "deleted": sum(c.change_type == "deleted" for c in changes)}
    if changes:
        rule = get_rule(db, "fim_change")
        deleted_sev = (rule.params or {}).get("deleted_severity", "high") if rule else "high"
        sample = [f"{c.change_type}: {c.file_path}" for c in changes[:10]]
        detect(db, "fim_change",
               title=f"{len(changes)} file change(s) in {directory.path}",
               description=f"Integrity scan found {summary['modified']} modified, {summary['new']} new and "
                           f"{summary['deleted']} deleted file(s) compared with the baseline.",
               resource_type="directory", resource_name=directory.path,
               severity=deleted_sev if summary["deleted"] else None,
               details={**{k: summary[k] for k in ("modified", "new", "deleted")}, "files": sample})
    return summary


def accept_changes(db: Session, directory: MonitoredDirectory) -> int:
    """Re-baseline after changes were reviewed and approved."""
    return create_baseline(db, directory)
