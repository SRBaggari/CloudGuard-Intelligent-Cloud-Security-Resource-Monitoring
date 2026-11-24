from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.deps import can_manage, client_ip, get_current_user, require_admin
from app.models import User, VirtualMachine
from app.schemas import OwnerAssign, VMOut
from app.virtualization.service import mark_expected_stop, sync_vms
from app.virtualization.vbox import VBoxError, VBoxUnavailable, get_vbox_adapter, validate_uuid

router = APIRouter(prefix="/api/vms", tags=["Virtual Machines"])


def _get_row(db: Session, vm_id: str, user: User) -> VirtualMachine:
    try:
        vm_uuid = validate_uuid(vm_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    row = db.scalar(select(VirtualMachine).where(VirtualMachine.uuid == vm_uuid, VirtualMachine.is_demo.is_(False)))
    if row is None or not can_manage(user, row.owner_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Virtual machine not found")
    return row


@router.get("")
def list_vms(refresh: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    st = get_vbox_adapter().status()
    if refresh and st.get("available"):
        sync_vms(db)
    stmt = select(VirtualMachine).where(VirtualMachine.is_demo.is_(False)).order_by(VirtualMachine.name)
    if not user.is_admin:
        stmt = stmt.where(VirtualMachine.owner_id == user.id)
    # Only report VMs as monitored when VirtualBox is actually connected
    rows = db.scalars(stmt).all() if st.get("available") else []
    items = [VMOut.model_validate(r) for r in rows]
    return {
        "virtualbox": st,
        "items": items,
        "summary": {"total": len(items), "running": sum(i.state == "running" for i in items)},
    }


@router.get("/{vm_id}")
def vm_detail(vm_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _get_row(db, vm_id, user)
    try:
        info = get_vbox_adapter().info(row.uuid)
    except VBoxUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except VBoxError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return {"vm": VMOut.model_validate(row), "details": info}


def _act(vm_id: str, action: str, force: bool, request: Request, user: User, db: Session):
    row = _get_row(db, vm_id, user)
    adapter = get_vbox_adapter()
    try:
        if action == "start":
            adapter.start(row.uuid)
        else:
            mark_expected_stop(row.uuid)
            adapter.stop(row.uuid, force=force)
    except VBoxUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except VBoxError as e:
        audit(db, f"vm.{action}_failed", user.id, "vm", row.uuid, {"error": str(e)[:300]}, client_ip(request))
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    audit(db, f"vm.{action}", user.id, "vm", row.uuid, {"name": row.name, "force": force}, client_ip(request))
    sync_vms(db)
    db.refresh(row)
    return {"detail": f"VM {action} requested", "vm": VMOut.model_validate(row)}


@router.post("/{vm_id}/start")
def start_vm(vm_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _act(vm_id, "start", False, request, user, db)


@router.post("/{vm_id}/stop")
def stop_vm(vm_id: str, request: Request, force: bool = Query(False, description="Hard power-off instead of ACPI"),
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _act(vm_id, "stop", force, request, user, db)


@router.put("/{vm_id}/owner", response_model=VMOut)
def assign_owner(vm_id: str, body: OwnerAssign, request: Request, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    row = _get_row(db, vm_id, admin)
    if body.owner_id is not None and not db.get(User, body.owner_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    row.owner_id = body.owner_id
    db.commit()
    audit(db, "vm.owner_assigned", admin.id, "vm", row.uuid, {"owner_id": body.owner_id}, client_ip(request))
    return row
