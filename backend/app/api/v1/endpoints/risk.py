"""Risk endpoints — FR-B-08, FR-B-10, FR-B-11."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User, UserRole
from app.models.market import RiskLimit
from app.services.risk_engine import KillSwitch

router = APIRouter()

RISK_ROLES = {UserRole.RISK, UserRole.ADMIN, UserRole.COMPLIANCE}
KILL_ROLES = {UserRole.RISK, UserRole.ADMIN, UserRole.TRADER}


@router.get("/limits", summary="Configured risk limits")
async def get_limits(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(RiskLimit).where(RiskLimit.is_active.is_(True)))
    limits = list(result.scalars().all())
    return {
        "count": len(limits),
        "limits": [
            {
                "id": l.id,
                "scope": str(l.scope),
                "limit_type": str(l.limit_type),
                "scope_id": l.scope_id,
                "value": str(l.value),
                "currency": l.currency,
                "is_approved": l.is_approved,
                "created_by": l.created_by,
                "approved_by": l.approved_by,
            }
            for l in limits
        ],
    }


@router.get("/kill-switch", summary="Kill switch status")
async def kill_switch_status(current_user: User = Depends(get_current_user)):
    return KillSwitch.status()


@router.post("/kill-switch/activate", summary="Halt all trading immediately")
async def activate_kill_switch(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    FR-B-08: halt all order submission instantly.
    Restricted to Risk, Admin and Trader roles.
    """
    if current_user.role not in KILL_ROLES:
        raise HTTPException(403, "Your role is not permitted to operate the kill switch")

    import uuid
    from app.models.exception import AuditLog

    KillSwitch.activate(current_user.id)
    db.add(AuditLog(
        id=str(uuid.uuid4()),
        actor_type="USER", actor_id=current_user.id,
        action="KILL_SWITCH_ACTIVATED",
        reason_code="MANUAL_ACTIVATION",
        detail={"role": str(current_user.role)},
    ))

    return {"activated": True, "message": "Trading halted. All new orders will be rejected.",
            "status": KillSwitch.status()}


@router.post("/kill-switch/deactivate", summary="Resume trading")
async def deactivate_kill_switch(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in KILL_ROLES:
        raise HTTPException(403, "Your role is not permitted to operate the kill switch")

    import uuid
    from app.models.exception import AuditLog

    KillSwitch.deactivate(current_user.id)
    db.add(AuditLog(
        id=str(uuid.uuid4()),
        actor_type="USER", actor_id=current_user.id,
        action="KILL_SWITCH_DEACTIVATED",
        detail={"role": str(current_user.role)},
    ))

    return {"activated": False, "message": "Trading resumed.", "status": KillSwitch.status()}
