"""System and operations endpoints — FR-E-12, FR-H-13, NFR-A-02."""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User
from app.models.order import Order, OrderState
from app.models.trade import Trade, SettlementInstruction, SettlementStatus
from app.models.market import Price, MarketCalendar
from app.models.exception import TradingException, ExceptionStatus, AuditLog
from app.services.settlement_engine import SettlementEngine
from app.services.exception_manager import ExceptionManager
from app.services.risk_engine import KillSwitch

router = APIRouter()


@router.get("/dashboard", summary="Operations dashboard")
async def ops_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FR-H-13: STP rate, exception counts, settlement status, system state."""
    stp = await SettlementEngine(db).calculate_stp_rate()
    exc_stats = await ExceptionManager(db).get_dashboard_stats()

    # Order state distribution
    state_result = await db.execute(
        select(Order.state, func.count(Order.id)).group_by(Order.state)
    )
    order_states = {str(s): c for s, c in state_result.all()}

    # Settlement status distribution
    settle_result = await db.execute(
        select(SettlementInstruction.status, func.count(SettlementInstruction.id))
        .group_by(SettlementInstruction.status)
    )
    settlement_states = {str(s): c for s, c in settle_result.all()}

    audit_count = await db.execute(select(func.count(AuditLog.id)))
    price_count = await db.execute(select(func.count(Price.id)))
    trade_count = await db.execute(select(func.count(Trade.id)))

    return {
        "stp": stp,
        "exceptions": exc_stats,
        "orders_by_state": order_states,
        "settlements_by_status": settlement_states,
        "kill_switch": KillSwitch.status(),
        "data": {
            "price_bars": audit_count.scalar_one() and price_count.scalar_one(),
            "audit_entries": audit_count.scalar_one(),
            "trades": trade_count.scalar_one(),
        },
    }


@router.get("/settlements", summary="Settlement pipeline")
async def list_settlements(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FR-E-04: settlement status per trade, in aggregate."""
    engine = SettlementEngine(db)
    pending = await engine.get_pending_settlements()
    failed = await engine.get_failed_settlements()

    def fmt(i):
        return {
            "id": i.id,
            "trade_id": i.trade_id,
            "instrument_id": i.instrument_id,
            "side": i.side,
            "quantity": str(i.quantity),
            "net_consideration": str(i.net_consideration),
            "settlement_date": i.settlement_date,
            "status": str(i.status),
            "counterparty": i.counterparty,
            "fail_reason": i.fail_reason,
            "ageing_days": i.ageing_days,
        }

    return {
        "pending_count": len(pending),
        "failed_count": len(failed),
        "pending": [fmt(i) for i in pending],
        "failed": [fmt(i) for i in failed],
    }


@router.get("/stp-rate", summary="STP rate")
async def stp_rate(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FR-E-12: percentage of trades completing without manual intervention."""
    return await SettlementEngine(db).calculate_stp_rate()
