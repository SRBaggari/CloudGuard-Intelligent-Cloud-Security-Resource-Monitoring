from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.pagination import PageParams, paginate
from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import client_ip, require_admin
from app.integrity.fim import PathNotAllowed, accept_changes, create_baseline, scan_directory, validate_directory
from app.models import FileIntegrityChange, FileIntegrityRecord, MonitoredDirectory, User
from app.schemas import DirectoryCreate, DirectoryOut, FileChangeOut, FileRecordOut, Page

router = APIRouter(prefix="/api/integrity", tags=["File Integrity"])


def _dir(db: Session, dir_id: int) -> MonitoredDirectory:
    d = db.get(MonitoredDirectory, dir_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Directory not found")
    return d


@router.get("/status")
def integrity_status(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    dirs = db.scalars(select(MonitoredDirectory).order_by(MonitoredDirectory.id)).all()
    out = []
    for d in dirs:
        counts = dict(db.execute(select(FileIntegrityRecord.status, func.count(FileIntegrityRecord.id))
                                 .where(FileIntegrityRecord.directory_id == d.id)
                                 .group_by(FileIntegrityRecord.status)).all())
        out.append({**DirectoryOut.model_validate(d).model_dump(), "files": sum(counts.values()),
                    "status_counts": counts,
                    "changed": counts.get("modified", 0) + counts.get("new", 0) + counts.get("deleted", 0)})
    total_changes = db.scalar(select(func.count(FileIntegrityChange.id))) or 0
    return {"directories": out, "total_changes": total_changes}


@router.post("/directories", response_model=DirectoryOut, status_code=status.HTTP_201_CREATED)
def add_directory(body: DirectoryCreate, request: Request, admin: User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    try:
        path = validate_directory(body.path)
    except PathNotAllowed as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    if db.scalar(select(MonitoredDirectory).where(MonitoredDirectory.path == str(path))):
        raise HTTPException(status.HTTP_409_CONFLICT, "Directory already monitored")
    d = MonitoredDirectory(path=str(path), recursive=body.recursive, created_by_id=admin.id)
    db.add(d)
    db.commit()
    create_baseline(db, d)
    db.refresh(d)
    audit(db, "integrity.directory_added", admin.id, "directory", d.id, {"path": d.path}, client_ip(request))
    return d


@router.delete("/directories/{dir_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_directory(dir_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    d = _dir(db, dir_id)
    path = d.path
    db.delete(d)
    db.commit()
    audit(db, "integrity.directory_removed", admin.id, "directory", dir_id, {"path": path}, client_ip(request))


@router.post("/scan")
def scan(request: Request, directory_id: int | None = None, admin: User = Depends(require_admin),
         db: Session = Depends(get_db)):
    """Scan one (or all enabled) monitored directories against their baseline."""
    dirs = [_dir(db, directory_id)] if directory_id else db.scalars(
        select(MonitoredDirectory).where(MonitoredDirectory.enabled.is_(True))).all()
    results = []
    for d in dirs:
        try:
            results.append(scan_directory(db, d))
        except PathNotAllowed as e:
            results.append({"directory": d.path, "error": str(e)})
    audit(db, "integrity.scan", admin.id, "directory", directory_id or "all", {"results": len(results)},
          client_ip(request))
    return {"results": results}


@router.post("/directories/{dir_id}/baseline")
def rebaseline(dir_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Accept current state as the new trusted baseline."""
    d = _dir(db, dir_id)
    try:
        n = accept_changes(db, d)
    except PathNotAllowed as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    audit(db, "integrity.baseline_updated", admin.id, "directory", d.id, {"files": n}, client_ip(request))
    return {"directory": d.path, "files": n}


@router.get("/history", response_model=Page[FileChangeOut])
def history(params: PageParams = Depends(), directory_id: int | None = None,
            change_type: str | None = Query(None, pattern="^(modified|new|deleted)$"),
            _: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(FileIntegrityChange).order_by(FileIntegrityChange.detected_at.desc(), FileIntegrityChange.id.desc())
    if directory_id:
        stmt = stmt.where(FileIntegrityChange.directory_id == directory_id)
    if change_type:
        stmt = stmt.where(FileIntegrityChange.change_type == change_type)
    return paginate(db, stmt, params, FileChangeOut)


@router.get("/directories/{dir_id}/files", response_model=Page[FileRecordOut])
def files(dir_id: int, params: PageParams = Depends(), _: User = Depends(require_admin), db: Session = Depends(get_db)):
    _dir(db, dir_id)
    stmt = select(FileIntegrityRecord).where(FileIntegrityRecord.directory_id == dir_id).order_by(FileIntegrityRecord.file_path)
    return paginate(db, stmt, params, FileRecordOut)
