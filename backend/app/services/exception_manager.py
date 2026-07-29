"""
Exception manager — FR-F-01 to FR-F-09.

Every failed automated step lands here rather than failing silently.
This is what makes "zero manual intervention" an operational claim rather
than a fragile assumption.
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exception import (
    TradingException, ExceptionCode, ExceptionSeverity, ExceptionStatus, AuditLog
)


# SLA hours per exception type — FR-F-03
SLA_HOURS = {
    ExceptionCode.EX_VAL: 1,
    ExceptionCode.EX_REF: 8,
    ExceptionCode.EX_RSK: 1,
    ExceptionCode.EX_CMP: 1,
    ExceptionCode.EX_EXE: 1,
    ExceptionCode.EX_FIL: 1,
    ExceptionCode.EX_ALC: 8,
    ExceptionCode.EX_SET: 24,
    ExceptionCode.EX_REC: 24,
    ExceptionCode.EX_SYS: 1,
    ExceptionCode.EX_AI: 8,
}

SEVERITY = {
    ExceptionCode.EX_VAL: ExceptionSeverity.LOW,
    ExceptionCode.EX_REF: ExceptionSeverity.MEDIUM,
    ExceptionCode.EX_RSK: ExceptionSeverity.HIGH,
    ExceptionCode.EX_CMP: ExceptionSeverity.HIGH,
    ExceptionCode.EX_EXE: ExceptionSeverity.HIGH,
    ExceptionCode.EX_FIL: ExceptionSeverity.CRITICAL,
    ExceptionCode.EX_ALC: ExceptionSeverity.MEDIUM,
    ExceptionCode.EX_SET: ExceptionSeverity.HIGH,
    ExceptionCode.EX_REC: ExceptionSeverity.HIGH,
    ExceptionCode.EX_SYS: ExceptionSeverity.CRITICAL,
    ExceptionCode.EX_AI: ExceptionSeverity.LOW,
}


class ExceptionManager:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def raise_exception(
        self,
        code: ExceptionCode,
        description: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        account_id: Optional[str] = None,
        instrument_id: Optional[str] = None,
        detail: Optional[dict] = None,
        correlation_id: Optional[str] = None,
    ) -> TradingException:
        """
        FR-F-01: route a failure to the exception queue.
        Nothing fails silently.
        """
        sla_hours = SLA_HOURS.get(code, 24)
        severity = SEVERITY.get(code, ExceptionSeverity.MEDIUM)
        now = datetime.now(timezone.utc)

        exc = TradingException(
            id=str(uuid.uuid4()),
            code=code,
            severity=severity,
            status=ExceptionStatus.OPEN,
            entity_type=entity_type,
            entity_id=entity_id,
            account_id=account_id,
            instrument_id=instrument_id,
            description=description,
            detail=detail,
            sla_hours=sla_hours,
            sla_due_at=now + timedelta(hours=sla_hours),
            raised_at=now,
        )
        self.db.add(exc)

        # Audit the exception being raised
        self.db.add(AuditLog(
            id=str(uuid.uuid4()),
            correlation_id=correlation_id,
            actor_type="SERVICE",
            actor_id="svc:exception_manager",
            action="EXCEPTION_RAISED",
            entity_type=entity_type,
            entity_id=entity_id,
            reason_code=code.value,
            detail={"description": description, "severity": severity.value, **(detail or {})},
        ))

        return exc

    async def list_exceptions(
        self,
        status: Optional[ExceptionStatus] = None,
        code: Optional[ExceptionCode] = None,
        severity: Optional[ExceptionSeverity] = None,
        account_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[TradingException]:
        """FR-F-06: the exception dashboard query."""
        stmt = select(TradingException)
        if status:
            stmt = stmt.where(TradingException.status == status)
        if code:
            stmt = stmt.where(TradingException.code == code)
        if severity:
            stmt = stmt.where(TradingException.severity == severity)
        if account_id:
            stmt = stmt.where(TradingException.account_id == account_id)

        stmt = stmt.order_by(TradingException.raised_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def resolve(
        self,
        exception_id: str,
        user_id: str,
        action: str,
        reason: str,
        correlation_id: Optional[str] = None,
    ) -> Optional[TradingException]:
        """
        FR-F-04: resolve an exception. Reason is mandatory — no closure
        without one is possible.
        """
        if not reason or not reason.strip():
            raise ValueError("Resolution reason is mandatory")

        result = await self.db.execute(
            select(TradingException).where(TradingException.id == exception_id)
        )
        exc = result.scalar_one_or_none()
        if exc is None:
            return None

        before = {"status": str(exc.status)}

        exc.status = ExceptionStatus.RESOLVED
        exc.resolution_action = action
        exc.resolution_reason = reason
        exc.resolved_by = user_id
        exc.resolved_at = datetime.now(timezone.utc)
        self.db.add(exc)

        self.db.add(AuditLog(
            id=str(uuid.uuid4()),
            correlation_id=correlation_id,
            actor_type="USER",
            actor_id=user_id,
            action="EXCEPTION_RESOLVED",
            entity_type="EXCEPTION",
            entity_id=exception_id,
            before_state=before,
            after_state={"status": "RESOLVED"},
            reason_code=exc.code.value if hasattr(exc.code, "value") else str(exc.code),
            detail={"action": action, "reason": reason},
        ))

        return exc

    async def assign(self, exception_id: str, owner_user_id: str,
                     actor_id: str) -> Optional[TradingException]:
        """Take ownership of an exception."""
        result = await self.db.execute(
            select(TradingException).where(TradingException.id == exception_id)
        )
        exc = result.scalar_one_or_none()
        if exc is None:
            return None

        exc.owner_user_id = owner_user_id
        exc.status = ExceptionStatus.IN_PROGRESS
        self.db.add(exc)

        self.db.add(AuditLog(
            id=str(uuid.uuid4()),
            actor_type="USER",
            actor_id=actor_id,
            action="EXCEPTION_ASSIGNED",
            entity_type="EXCEPTION",
            entity_id=exception_id,
            detail={"owner": owner_user_id},
        ))
        return exc

    async def get_dashboard_stats(self) -> dict:
        """FR-F-03: counts by type and severity, with SLA breach flagging."""
        now = datetime.now(timezone.utc)

        result = await self.db.execute(
            select(TradingException).where(
                TradingException.status.in_([ExceptionStatus.OPEN, ExceptionStatus.IN_PROGRESS])
            )
        )
        open_exceptions = list(result.scalars().all())

        by_code: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        sla_breached = 0

        for exc in open_exceptions:
            code = exc.code.value if hasattr(exc.code, "value") else str(exc.code)
            sev = exc.severity.value if hasattr(exc.severity, "value") else str(exc.severity)
            by_code[code] = by_code.get(code, 0) + 1
            by_severity[sev] = by_severity.get(sev, 0) + 1
            if exc.sla_due_at and exc.sla_due_at < now:
                sla_breached += 1

        return {
            "open_count": len(open_exceptions),
            "by_code": by_code,
            "by_severity": by_severity,
            "sla_breached": sla_breached,
        }
