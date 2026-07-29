"""Exception queue endpoints — FR-F-01 to FR-F-09."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User, UserRole
from app.models.exception import ExceptionCode, ExceptionSeverity, ExceptionStatus
from app.services.exception_manager import ExceptionManager

router = APIRouter()

OPS_ROLES = {UserRole.OPERATIONS, UserRole.ADMIN, UserRole.RISK, UserRole.COMPLIANCE}


class ResolveRequest(BaseModel):
    action: str = Field(..., examples=["Reference data corrected; order resubmitted"])
    reason: str = Field(..., min_length=1,
                        description="Mandatory — no closure without a reason")


@router.get("/", summary="Exception queue")
async def list_exceptions(
    status: Optional[ExceptionStatus] = None,
    code: Optional[ExceptionCode] = None,
    severity: Optional[ExceptionSeverity] = None,
    account_id: Optional[str] = None,
    limit: int = Query(100, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FR-F-06: the operations exception dashboard."""
    exceptions = await ExceptionManager(db).list_exceptions(
        status=status, code=code, severity=severity,
        account_id=account_id, limit=limit,
    )
    return {
        "count": len(exceptions),
        "exceptions": [
            {
                "id": e.id,
                "code": str(e.code),
                "severity": str(e.severity),
                "status": str(e.status),
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "account_id": e.account_id,
                "instrument_id": e.instrument_id,
                "description": e.description,
                "detail": e.detail,
                "sla_hours": e.sla_hours,
                "sla_due_at": e.sla_due_at.isoformat() if e.sla_due_at else None,
                "raised_at": e.raised_at.isoformat() if e.raised_at else None,
                "owner_user_id": e.owner_user_id,
                "resolution_action": e.resolution_action,
                "resolution_reason": e.resolution_reason,
                "resolved_by": e.resolved_by,
                "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
            }
            for e in exceptions
        ],
    }


@router.get("/stats", summary="Exception dashboard statistics")
async def exception_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FR-F-03: counts by type and severity, with SLA breach flagging."""
    return await ExceptionManager(db).get_dashboard_stats()


@router.post("/{exception_id}/resolve", summary="Resolve an exception")
async def resolve_exception(
    exception_id: str,
    body: ResolveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    FR-F-04: resolve an exception.
    A reason is mandatory — closure without one is not possible.
    """
    if current_user.role not in OPS_ROLES:
        raise HTTPException(403, "Your role is not permitted to resolve exceptions")

    try:
        exc = await ExceptionManager(db).resolve(
            exception_id, current_user.id, body.action, body.reason
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    if exc is None:
        raise HTTPException(404, "Exception not found")

    return {
        "success": True,
        "message": "Exception resolved and audited.",
        "exception": {
            "id": exc.id,
            "status": str(exc.status),
            "resolution_action": exc.resolution_action,
            "resolution_reason": exc.resolution_reason,
            "resolved_by": exc.resolved_by,
            "resolved_at": exc.resolved_at.isoformat() if exc.resolved_at else None,
        },
    }


@router.post("/{exception_id}/assign", summary="Take ownership of an exception")
async def assign_exception(
    exception_id: str,
    owner_user_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in OPS_ROLES:
        raise HTTPException(403, "Your role is not permitted to assign exceptions")

    exc = await ExceptionManager(db).assign(
        exception_id, owner_user_id or current_user.id, current_user.id
    )
    if exc is None:
        raise HTTPException(404, "Exception not found")
    return {"success": True, "owner_user_id": exc.owner_user_id, "status": str(exc.status)}
