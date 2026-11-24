from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.pagination import PageParams, paginate
from app.core.audit import audit
from app.core.database import get_db, utcnow
from app.core.deps import client_ip, get_current_user, require_admin
from app.models import Alert, DetectionRule, SecurityEvent, User
from app.realtime.bus import manager
from app.schemas import AlertAction, AlertOut, EventOut, Page, RuleOut, RuleUpdate
from app.security_engine.rules import render_condition

router = APIRouter(prefix="/api/security", tags=["Security"])

SEV_PATTERN = "^(critical|high|medium|low)$"


@router.get("/events", response_model=Page[EventOut])
def events(
    params: PageParams = Depends(),
    category: str | None = Query(None, max_length=32), severity: str | None = Query(None, pattern=SEV_PATTERN),
    event_type: str | None = Query(None, max_length=64), q: str | None = Query(None, max_length=128),
    start: datetime | None = None, end: datetime | None = None, include_demo: bool = False,
    _: User = Depends(require_admin), db: Session = Depends(get_db),
):
    stmt = select(SecurityEvent).order_by(SecurityEvent.created_at.desc())
    if not include_demo:
        stmt = stmt.where(SecurityEvent.is_demo.is_(False))
    if category:
        stmt = stmt.where(SecurityEvent.category == category)
    if severity:
        stmt = stmt.where(SecurityEvent.severity == severity)
    if event_type:
        stmt = stmt.where(SecurityEvent.event_type == event_type)
    if q:
        stmt = stmt.where(or_(SecurityEvent.message.ilike(f"%{q}%"), SecurityEvent.resource.ilike(f"%{q}%")))
    if start:
        stmt = stmt.where(SecurityEvent.created_at >= start)
    if end:
        stmt = stmt.where(SecurityEvent.created_at <= end)
    return paginate(db, stmt, params, EventOut)


@router.get("/alerts", response_model=Page[AlertOut])
def alerts(
    params: PageParams = Depends(),
    status_: str | None = Query(None, alias="status", pattern="^(open|acknowledged|resolved|active)$"),
    severity: str | None = Query(None, pattern=SEV_PATTERN),
    category: str | None = Query(None, max_length=32), q: str | None = Query(None, max_length=128),
    start: datetime | None = None, end: datetime | None = None,
    include_demo: bool = Query(False, description="Include labelled demonstration alerts"),
    demo_only: bool = Query(False, description="Only demonstration alerts"),
    _: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Search and filter alerts. status=active returns open + acknowledged. Demo alerts are excluded by default."""
    stmt = select(Alert).order_by(Alert.last_seen_at.desc())
    if demo_only:
        stmt = stmt.where(Alert.is_demo.is_(True))
    elif not include_demo:
        stmt = stmt.where(Alert.is_demo.is_(False))
    if status_ == "active":
        stmt = stmt.where(Alert.status != "resolved")
    elif status_:
        stmt = stmt.where(Alert.status == status_)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if category:
        stmt = stmt.where(Alert.category == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Alert.title.ilike(like), Alert.description.ilike(like), Alert.resource_name.ilike(like)))
    if start:
        stmt = stmt.where(Alert.created_at >= start)
    if end:
        stmt = stmt.where(Alert.created_at <= end)
    return paginate(db, stmt, params, AlertOut)


@router.get("/alerts/stats")
def alert_stats(include_demo: bool = False, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    demo = (Alert.is_demo.is_(False),) if not include_demo else ()
    rows = db.execute(select(Alert.status, Alert.severity, func.count(Alert.id)).where(*demo)
                      .group_by(Alert.status, Alert.severity)).all()
    by_sev = {s: 0 for s in ("critical", "high", "medium", "low")}
    by_status = {s: 0 for s in ("open", "acknowledged", "resolved")}
    active_by_sev = dict(by_sev)
    for st, sev, n in rows:
        by_status[st] += n
        by_sev[sev] += n
        if st != "resolved":
            active_by_sev[sev] += n
    cats = db.execute(select(Alert.category, func.count(Alert.id)).where(Alert.status != "resolved", *demo)
                      .group_by(Alert.category)).all()
    return {"by_severity": by_sev, "by_status": by_status, "active_by_severity": active_by_sev,
            "active_by_category": {c: n for c, n in cats}}


@router.get("/alerts/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    return a


def _transition(alert_id: int, new: str, body: AlertAction, request: Request, user: User, db: Session) -> Alert:
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    if a.status == "resolved":
        raise HTTPException(status.HTTP_409_CONFLICT, "Alert already resolved")
    if new == "acknowledged":
        if a.status == "acknowledged":
            raise HTTPException(status.HTTP_409_CONFLICT, "Alert already acknowledged")
        a.acknowledged_by_id, a.acknowledged_at = user.id, utcnow()
    else:
        a.resolved_by_id, a.resolved_at = user.id, utcnow()
        if a.acknowledged_at is None:
            a.acknowledged_by_id, a.acknowledged_at = user.id, a.resolved_at
    a.status = new
    if body.note:
        a.resolution_note = body.note
    db.commit()
    db.refresh(a)
    audit(db, f"alert.{new}", user.id, "alert", a.id, {"note": body.note[:200]} if body.note else {}, client_ip(request))
    manager.publish("alerts", {"type": "alert.updated", "alert": AlertOut.model_validate(a).model_dump(mode="json")})
    return a


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge(alert_id: int, request: Request, body: AlertAction = AlertAction(),
                user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _transition(alert_id, "acknowledged", body, request, user, db)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve(alert_id: int, request: Request, body: AlertAction = AlertAction(),
            user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _transition(alert_id, "resolved", body, request, user, db)


# ---------------------------------------------------------------- rules
def _rule_out(r: DetectionRule) -> RuleOut:
    out = RuleOut.model_validate(r)
    out.condition = render_condition(r.condition, r.params or {})
    return out


@router.get("/rules", response_model=list[RuleOut])
def rules(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_rule_out(r) for r in db.scalars(select(DetectionRule).order_by(DetectionRule.category, DetectionRule.id))]


@router.patch("/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, body: RuleUpdate, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    r = db.get(DetectionRule, rule_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    if body.enabled is not None:
        r.enabled = body.enabled
    if body.severity:
        r.severity = body.severity
    if body.params is not None:
        # only existing, same-typed numeric/string params may be changed
        new = dict(r.params or {})
        for k, v in body.params.items():
            if k not in new:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown parameter '{k}'")
            old = new[k]
            if isinstance(old, (int, float)) and not isinstance(old, bool):
                if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 or v > 1e9:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Parameter '{k}' must be a positive number")
                v = int(v) if isinstance(old, int) and float(v).is_integer() else v
            elif isinstance(old, str):
                if not isinstance(v, str) or len(v) > 64:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Parameter '{k}' must be a short string")
            new[k] = v
        if {"warning", "critical"} <= new.keys() and new["critical"] < new["warning"]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "critical threshold must be >= warning")
        r.params = new
    db.commit()
    db.refresh(r)
    audit(db, "rule.updated", admin.id, "rule", r.key, body.model_dump(exclude_none=True), client_ip(request))
    return _rule_out(r)
