from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.pagination import PageParams, paginate
from app.core.audit import audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import client_ip, get_current_user
from app.models import Report, User
from app.reports.generator import gather, render_csv, render_pdf, summary_of
from app.schemas import Page, ReportOut, ReportRequest

router = APIRouter(prefix="/api/reports", tags=["Reports"])


def _visible(stmt, user: User):
    return stmt if user.is_admin else stmt.where(Report.created_by_id == user.id)


def _get(db: Session, report_id: int, user: User) -> Report:
    r = db.get(Report, report_id)
    if not r or (not user.is_admin and r.created_by_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    return r


@router.get("", response_model=Page[ReportOut])
def list_reports(params: PageParams = Depends(), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return paginate(db, _visible(select(Report), user).order_by(Report.created_at.desc()), params, ReportOut)


@router.post("/generate", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def generate(body: ReportRequest, request: Request, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    if body.end_date <= body.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end_date must be after start_date")
    if (body.end_date - body.start_date).days > 366:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Date range may not exceed one year")
    data = gather(db, body.start_date, body.end_date)
    file_name = f"cloudguard-report-{uuid.uuid4().hex[:12]}.{body.format}"
    path = get_settings().data_dir / "reports" / file_name
    if body.format == "pdf":
        render_pdf(data, body.sections, body.title, path)
    else:
        render_csv(data, body.sections, path)
    r = Report(title=body.title, format=body.format, start_date=body.start_date, end_date=body.end_date,
               sections=body.sections, file_name=file_name, file_size=path.stat().st_size,
               summary=summary_of(data), created_by_id=user.id)
    db.add(r)
    db.commit()
    db.refresh(r)
    audit(db, "report.generated", user.id, "report", r.id, {"format": r.format}, client_ip(request))
    return r


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get(db, report_id, user)


@router.get("/{report_id}/download")
def download(report_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _get(db, report_id, user)
    path = get_settings().data_dir / "reports" / r.file_name
    if not path.is_file():
        raise HTTPException(status.HTTP_410_GONE, "Report file no longer exists")
    media = "application/pdf" if r.format == "pdf" else "text/csv"
    return FileResponse(path, media_type=media, filename=r.file_name)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report_id: int, request: Request, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    r = _get(db, report_id, user)
    path = get_settings().data_dir / "reports" / r.file_name
    path.unlink(missing_ok=True)
    db.delete(r)
    db.commit()
    audit(db, "report.deleted", user.id, "report", report_id, ip=client_ip(request))
