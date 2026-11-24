from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.pagination import PageParams, paginate
from app.compliance import service
from app.core.audit import audit
from app.core.database import get_db, utcnow
from app.core.deps import client_ip, require_admin
from app.models import ComplianceCheck, ComplianceRun, User
from app.schemas import (
    ComplianceCheckCreate, ComplianceCheckOut, ComplianceCheckUpdate, ComplianceRunOut, ComplianceRunSummary,
    ManualAssessment, Page,
)

# Administrators only: posture details reveal configuration weaknesses.
router = APIRouter(prefix="/api/compliance", tags=["Audit & Compliance"])


def _check(db: Session, check_id: int) -> ComplianceCheck:
    c = db.get(ComplianceCheck, check_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Check not found")
    return c


@router.get("/checks", response_model=list[ComplianceCheckOut])
def list_checks(category: str | None = Query(None, max_length=32), _: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    stmt = select(ComplianceCheck).order_by(ComplianceCheck.category, ComplianceCheck.id)
    if category:
        stmt = stmt.where(ComplianceCheck.category == category)
    return db.scalars(stmt).all()


@router.post("/checks", response_model=ComplianceCheckOut, status_code=status.HTTP_201_CREATED)
def create_check(body: ComplianceCheckCreate, request: Request, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    """Add a custom (manually assessed) checklist item."""
    c = ComplianceCheck(key=f"custom_{utcnow().strftime('%Y%m%d%H%M%S%f')}", check_type="manual", is_custom=True,
                        **body.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    audit(db, "compliance.check_created", admin.id, "compliance_check", c.id, {"title": c.title}, client_ip(request))
    return c


@router.patch("/checks/{check_id}", response_model=ComplianceCheckOut)
def update_check(check_id: int, body: ComplianceCheckUpdate, request: Request, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    c = _check(db, check_id)
    changes = body.model_dump(exclude_none=True)
    if not c.is_custom and {"title", "description", "remediation"} & changes.keys():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Only custom checks can be renamed or redescribed")
    for k, v in changes.items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    audit(db, "compliance.check_updated", admin.id, "compliance_check", c.key, changes, client_ip(request))
    return c


@router.delete("/checks/{check_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_check(check_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = _check(db, check_id)
    if not c.is_custom:
        raise HTTPException(status.HTTP_409_CONFLICT, "Built-in checks can be disabled but not deleted")
    db.delete(c)
    db.commit()
    audit(db, "compliance.check_deleted", admin.id, "compliance_check", check_id, ip=client_ip(request))


@router.post("/checks/{check_id}/assess", response_model=ComplianceCheckOut)
def assess(check_id: int, body: ManualAssessment, request: Request, admin: User = Depends(require_admin),
           db: Session = Depends(get_db)):
    """Record the result of a manual checklist item together with evidence."""
    c = _check(db, check_id)
    if c.check_type != "manual":
        raise HTTPException(status.HTTP_409_CONFLICT, "Automated checks are evaluated by CloudGuard")
    now = utcnow()
    c.manual_status, c.manual_evidence, c.assessed_by_id, c.assessed_at = body.status, body.evidence, admin.id, now
    c.last_status, c.last_evidence, c.last_checked_at = body.status, body.evidence, now
    db.commit()
    db.refresh(c)
    audit(db, "compliance.manual_assessment", admin.id, "compliance_check", c.key, {"status": body.status},
          client_ip(request))
    return c


@router.post("/run", response_model=ComplianceRunOut, status_code=status.HTTP_201_CREATED)
def run(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Evaluate every enabled check now and store a posture snapshot."""
    r = service.run_checks(db, admin)
    audit(db, "compliance.run", admin.id, "compliance_run", r.id, {"score": r.score}, client_ip(request))
    return r


@router.get("/posture", response_model=ComplianceRunOut | None)
def posture(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Latest posture snapshot (null if the checklist has never been run)."""
    return service.latest_run(db)


@router.get("/runs", response_model=Page[ComplianceRunSummary])
def runs(params: PageParams = Depends(), _: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(ComplianceRun).order_by(ComplianceRun.created_at.desc(), ComplianceRun.id.desc())
    return paginate(db, stmt, params, ComplianceRunSummary)
