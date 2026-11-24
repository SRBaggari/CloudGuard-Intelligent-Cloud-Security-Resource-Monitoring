from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db, utcnow
from app.core.deps import can_manage, client_ip, get_current_user, require_admin
from app.docker_integration.adapter import (
    DockerOperationError, DockerUnavailable, get_docker_adapter, validate_container_ref,
)
from app.docker_integration.service import sync_containers
from app.models import Container, User
from app.schemas import ContainerOut, OwnerAssign

router = APIRouter(prefix="/api/containers", tags=["Docker Containers"])


def _visible(stmt, user: User):
    return stmt if user.is_admin else stmt.where(Container.owner_id == user.id)


def _get_row(db: Session, ref: str, user: User) -> Container:
    try:
        validate_container_ref(ref)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    conds = [Container.container_id == ref, Container.name == ref]
    if len(ref) >= 12:
        conds.append(Container.container_id.startswith(ref))
    row = db.scalar(select(Container).where(or_(*conds)))
    if row is None or not can_manage(user, row.owner_id):
        # do not reveal existence of resources the user is not authorised for
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Container not found")
    return row


@router.get("")
def list_containers(
    state: str | None = Query(None, pattern="^(running|exited|paused|created|restarting|dead|removed)$"),
    refresh: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    adapter = get_docker_adapter()
    st = adapter.status()
    if refresh and st.get("available"):
        sync_containers(db)
    stmt = _visible(select(Container), user).order_by(Container.name)
    if state:
        stmt = stmt.where(Container.status == state)
    rows = db.scalars(stmt).all()
    items = [ContainerOut.model_validate(r) for r in rows]
    return {
        "docker": st,
        "items": items,
        "summary": {
            "total": len(items),
            "running": sum(i.status == "running" for i in items),
            "stopped": sum(i.status in ("exited", "dead") for i in items),
            "unhealthy": sum(i.health == "unhealthy" for i in items),
        },
    }


@router.get("/{ref}")
def inspect_container(ref: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _get_row(db, ref, user)
    try:
        details = get_docker_adapter().inspect(row.container_id)
    except DockerUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except DockerOperationError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return {"container": ContainerOut.model_validate(row), "details": details}


def _do_action(ref: str, action: str, request: Request, user: User, db: Session):
    row = _get_row(db, ref, user)
    adapter = get_docker_adapter()
    if action in ("stop", "restart"):
        row.expected_stop_at = utcnow()
        db.commit()
    try:
        adapter.action(row.container_id, action)
    except DockerUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except DockerOperationError as e:
        audit(db, f"container.{action}_failed", user.id, "container", row.name, {"error": str(e)[:300]},
              client_ip(request))
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    audit(db, f"container.{action}", user.id, "container", row.name, {"container_id": row.container_id[:12]},
          client_ip(request))
    sync_containers(db, with_stats=False)
    db.refresh(row)
    return {"detail": f"Container {action} requested", "container": ContainerOut.model_validate(row)}


@router.post("/{ref}/start")
def start(ref: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _do_action(ref, "start", request, user, db)


@router.post("/{ref}/stop")
def stop(ref: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _do_action(ref, "stop", request, user, db)


@router.post("/{ref}/restart")
def restart(ref: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _do_action(ref, "restart", request, user, db)


@router.get("/{ref}/logs")
def logs(ref: str, request: Request, tail: int = Query(200, ge=1, le=5000), user: User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    row = _get_row(db, ref, user)
    try:
        text = get_docker_adapter().logs(row.container_id, tail)
    except DockerUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except Exception as e:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Unable to read logs: {e}")
    audit(db, "container.logs_viewed", user.id, "container", row.name, ip=client_ip(request))
    return {"container": row.name, "tail": tail, "logs": text}


@router.put("/{ref}/owner", response_model=ContainerOut)
def assign_owner(ref: str, body: OwnerAssign, request: Request, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    row = _get_row(db, ref, admin)
    if body.owner_id is not None and not db.get(User, body.owner_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    row.owner_id = body.owner_id
    db.commit()
    audit(db, "container.owner_assigned", admin.id, "container", row.name, {"owner_id": body.owner_id},
          client_ip(request))
    return row
