from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.pagination import PageParams, paginate
from app.core.audit import audit
from app.core.database import ensure_aware, get_db
from app.core.deps import client_ip, get_current_user, require_admin
from app.models import Incident, User, incident_alerts
from app.schemas import (
    IncidentActionOut, IncidentActionRequest, IncidentCreate, IncidentEventOut, IncidentLinkAlerts, IncidentNote,
    IncidentOut, IncidentStatusChange, IncidentSummaryOut, IncidentUpdate, Page,
)
from app.services import incidents as svc

router = APIRouter(prefix="/api/incidents", tags=["Incident Response"])


def _visible(stmt, user: User):
    if user.is_admin:
        return stmt
    return stmt.where(or_(Incident.assignee_id == user.id, Incident.created_by_id == user.id))


def _get(db: Session, incident_id: int, user: User) -> Incident:
    inc = db.get(Incident, incident_id)
    if inc is None or not (user.is_admin or user.id in (inc.assignee_id, inc.created_by_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    return inc


def _require_responder(inc: Incident, user: User) -> None:
    if not (user.is_admin or inc.assignee_id == user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators or the assignee can update this incident")


def _rule_error(e: svc.IncidentError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(e))


@router.get("", response_model=Page[IncidentSummaryOut])
def list_incidents(
    params: PageParams = Depends(),
    status_: str | None = Query(None, alias="status", pattern="^(detected|acknowledged|investigating|resolved|open)$"),
    severity: str | None = Query(None, pattern="^(critical|high|medium|low)$"),
    q: str | None = Query(None, max_length=128),
    assigned_to_me: bool = False,
    alert_id: int | None = None,
    include_demo: bool = False,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Incidents visible to the user. `status=open` returns everything not yet resolved."""
    stmt = _visible(select(Incident), user).order_by(Incident.updated_at.desc())
    if status_ == "open":
        stmt = stmt.where(Incident.status != "resolved")
    elif status_:
        stmt = stmt.where(Incident.status == status_)
    if severity:
        stmt = stmt.where(Incident.severity == severity)
    if q:
        stmt = stmt.where(or_(Incident.title.ilike(f"%{q}%"), Incident.description.ilike(f"%{q}%")))
    if assigned_to_me:
        stmt = stmt.where(Incident.assignee_id == user.id)
    if alert_id:
        stmt = stmt.where(Incident.id.in_(select(incident_alerts.c.incident_id).where(incident_alerts.c.alert_id == alert_id)))
    if not include_demo:
        stmt = stmt.where(Incident.is_demo.is_(False))
    return paginate(db, stmt, params, IncidentSummaryOut)


@router.get("/stats")
def incident_stats(include_demo: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = _visible(select(Incident), user)
    if not include_demo:
        stmt = stmt.where(Incident.is_demo.is_(False))
    rows = db.scalars(stmt).all()
    by_status = {s: 0 for s in svc.ORDER}
    for r in rows:
        by_status[r.status] += 1

    def mean_minutes(pairs):
        vals = [(ensure_aware(b) - ensure_aware(a)).total_seconds() / 60 for a, b in pairs if a and b]
        return round(sum(vals) / len(vals), 1) if vals else None

    return {
        "total": len(rows), "by_status": by_status,
        "open_by_severity": {s: sum(1 for r in rows if r.status != "resolved" and r.severity == s)
                             for s in ("critical", "high", "medium", "low")},
        "mean_time_to_acknowledge_minutes": mean_minutes((r.detected_at, r.acknowledged_at) for r in rows),
        "mean_time_to_resolve_minutes": mean_minutes((r.detected_at, r.resolved_at) for r in rows),
    }


@router.post("", response_model=IncidentOut, status_code=status.HTTP_201_CREATED)
def create(body: IncidentCreate, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        inc = svc.create_incident(db, title=body.title, description=body.description, severity=body.severity,
                                  category=body.category, alert_ids=body.alert_ids, assignee_id=body.assignee_id, user=admin)
    except svc.IncidentError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    audit(db, "incident.created", admin.id, "incident", inc.id, {"alerts": body.alert_ids}, client_ip(request))
    return inc


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(incident_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get(db, incident_id, user)


@router.patch("/{incident_id}", response_model=IncidentOut)
def update(incident_id: int, body: IncidentUpdate, request: Request, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    inc = _get(db, incident_id, user)
    _require_responder(inc, user)
    changes = body.model_dump(exclude_unset=True)
    if not user.is_admin and ({"assignee_id", "unassign", "severity"} & changes.keys()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators can change assignment or severity")
    try:
        inc = svc.update_incident(db, inc, changes, user)
    except svc.IncidentError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    audit(db, "incident.updated", user.id, "incident", inc.id, changes, client_ip(request))
    return inc


@router.post("/{incident_id}/status", response_model=IncidentOut)
def set_status(incident_id: int, body: IncidentStatusChange, request: Request, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    inc = _get(db, incident_id, user)
    _require_responder(inc, user)
    old = inc.status
    try:
        inc = svc.change_status(db, inc, body.status, user, body.note, body.resolution_summary)
    except svc.IncidentError as e:
        raise _rule_error(e)
    audit(db, f"incident.status.{body.status}", user.id, "incident", inc.id, {"from": old}, client_ip(request))
    return inc


@router.post("/{incident_id}/notes", response_model=IncidentEventOut, status_code=status.HTTP_201_CREATED)
def add_note(incident_id: int, body: IncidentNote, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    inc = _get(db, incident_id, user)
    _require_responder(inc, user)
    return svc.add_note(db, inc, body.message, user)


@router.post("/{incident_id}/alerts", response_model=IncidentOut)
def link_alerts(incident_id: int, body: IncidentLinkAlerts, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    inc = _get(db, incident_id, admin)
    try:
        inc = svc.link_alerts(db, inc, body.alert_ids, admin)
    except svc.IncidentError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    audit(db, "incident.alerts_linked", admin.id, "incident", inc.id, {"alerts": body.alert_ids}, client_ip(request))
    return inc


@router.post("/{incident_id}/actions", response_model=IncidentActionOut, status_code=status.HTTP_201_CREATED)
def response_action(incident_id: int, body: IncidentActionRequest, request: Request,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Execute an authorised response action (admins) or record a manual one (admins or assignee).

    A failed action is still recorded (status `failed`) so the timeline reflects what was attempted.
    """
    inc = _get(db, incident_id, user)
    _require_responder(inc, user)
    if body.action_type != "manual" and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators can execute response actions")
    if inc.status == "resolved":
        raise HTTPException(status.HTTP_409_CONFLICT, "Reopen the incident before taking further actions")
    try:
        return svc.perform_action(db, inc, body.action_type, body.target, body.description, body.force, user,
                                  client_ip(request))
    except svc.IncidentError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
