"""Trade endpoints — FR-H-04."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User, UserRole
from app.models.account import Account
from app.models.trade import Trade, Fill

router = APIRouter()


@router.get("/", summary="Trade list")
async def list_trades(
    account_id: Optional[str] = None,
    instrument_id: Optional[str] = None,
    is_paper: bool = False,
    limit: int = Query(100, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Trade).where(Trade.is_paper.is_(is_paper))

    internal = {UserRole.TRADER, UserRole.ADMIN, UserRole.OPERATIONS,
                UserRole.RISK, UserRole.COMPLIANCE, UserRole.READ_ONLY}
    if current_user.role not in internal:
        acc = await db.execute(
            select(Account.id).where(Account.client_id == current_user.client_id)
        )
        stmt = stmt.where(Trade.account_id.in_(list(acc.scalars().all())))

    if account_id:
        stmt = stmt.where(Trade.account_id == account_id)
    if instrument_id:
        stmt = stmt.where(Trade.instrument_id == instrument_id.upper())

    result = await db.execute(stmt.order_by(desc(Trade.trade_date)).limit(limit))
    trades = list(result.scalars().all())

    return {
        "count": len(trades),
        "trades": [
            {
                "id": t.id, "order_id": t.order_id,
                "instrument_id": t.instrument_id, "side": t.side,
                "quantity": str(t.quantity), "price": str(t.price),
                "gross_consideration": str(t.gross_consideration),
                "commission": str(t.commission),
                "exchange_fee": str(t.exchange_fee),
                "tax": str(t.tax),
                "net_consideration": str(t.net_consideration),
                "settlement_date": t.settlement_date,
                "settlement_status": str(t.settlement_status),
                "source_channel": t.source_channel,
                "trade_date": t.trade_date.isoformat() if t.trade_date else None,
            }
            for t in trades
        ],
    }


@router.get("/{trade_id}/confirmation", summary="Trade confirmation")
async def get_confirmation(
    trade_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FR-H-04: electronic trade confirmation with full economics."""
    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    t = result.scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "Trade not found")

    fills_result = await db.execute(select(Fill).where(Fill.order_id == t.order_id))
    fills = list(fills_result.scalars().all())

    return {
        "confirmation_id": t.id,
        "trade_date": t.trade_date.isoformat() if t.trade_date else None,
        "settlement_date": t.settlement_date,
        "settlement_status": str(t.settlement_status),
        "account_id": t.account_id,
        "instrument_id": t.instrument_id,
        "side": t.side,
        "quantity": str(t.quantity),
        "price": str(t.price),
        "currency": t.currency,
        "economics": {
            "gross_consideration": str(t.gross_consideration),
            "commission": str(t.commission),
            "exchange_fee": str(t.exchange_fee),
            "tax": str(t.tax),
            "total_charges": str(t.commission + t.exchange_fee + t.tax),
            "net_consideration": str(t.net_consideration),
        },
        "execution_detail": {
            "fill_count": len(fills),
            "fills": [
                {"quantity": str(f.quantity), "price": str(f.price),
                 "venue": f.venue,
                 "executed_at": f.executed_at.isoformat() if f.executed_at else None}
                for f in fills
            ],
        },
        "entering_user_id": t.entering_user_id,
        "source_channel": t.source_channel,
    }
