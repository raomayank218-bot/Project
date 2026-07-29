"""Portfolio endpoints — FR-G-01 to FR-G-16."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User, UserRole
from app.models.account import Account
from app.models.trade import Trade, CashMovement
from app.services.portfolio_engine import PortfolioEngine

router = APIRouter()


async def _get_account(db: AsyncSession, user: User, account_id: str) -> Account:
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(404, "Account not found")

    internal = {UserRole.TRADER, UserRole.ADMIN, UserRole.OPERATIONS,
                UserRole.RISK, UserRole.COMPLIANCE, UserRole.READ_ONLY}
    if user.role in internal or (user.client_id and account.client_id == user.client_id):
        return account
    raise HTTPException(403, "You are not entitled to view this account")


@router.get("/accounts", summary="List accounts you can access")
async def list_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    internal = {UserRole.TRADER, UserRole.ADMIN, UserRole.OPERATIONS,
                UserRole.RISK, UserRole.COMPLIANCE, UserRole.READ_ONLY}
    stmt = select(Account)
    if current_user.role not in internal:
        stmt = stmt.where(Account.client_id == current_user.client_id)

    result = await db.execute(stmt.order_by(Account.account_name))
    accounts = list(result.scalars().all())
    return {
        "count": len(accounts),
        "accounts": [
            {
                "id": a.id,
                "account_name": a.account_name,
                "account_type": a.account_type,
                "base_currency": a.base_currency,
                "status": str(a.status),
                "is_paper": a.is_paper,
                "cash_settled": str(a.cash_settled),
                "cash_unsettled": str(a.cash_unsettled),
                "daily_notional_limit": str(a.daily_notional_limit),
                "max_position_pct": str(a.max_position_pct),
            }
            for a in accounts
        ],
    }


@router.get("/{account_id}/summary", summary="Portfolio dashboard data")
async def portfolio_summary(
    account_id: str,
    is_paper: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    FR-G-16: everything the dashboard needs on one call — total value,
    P&L, allocation and positions.
    """
    account = await _get_account(db, current_user, account_id)
    summary = await PortfolioEngine(db).get_summary(account, is_paper)

    # Allocation by instrument — FR-G-08
    allocation = []
    if summary.total_value > 0:
        for p in summary.positions:
            allocation.append({
                "instrument_id": p.instrument_id,
                "market_value": str(p.market_value),
                "pct_of_portfolio": str(
                    round((p.market_value / summary.total_value) * 100, 2)
                ),
            })
        cash_pct = round((summary.total_cash / summary.total_value) * 100, 2)
        allocation.append({"instrument_id": "CASH",
                           "market_value": str(summary.total_cash),
                           "pct_of_portfolio": str(cash_pct)})

    return {
        "account_id": summary.account_id,
        "account_name": account.account_name,
        "is_paper": summary.is_paper,
        "cash": {
            "settled": str(summary.cash_settled),
            "unsettled": str(summary.cash_unsettled),
            "total": str(summary.total_cash),
            "buying_power": str(summary.cash_settled),
        },
        "valuation": {
            "positions_value": str(summary.positions_value),
            "total_value": str(summary.total_value),
            "total_cost_basis": str(summary.total_cost_basis),
        },
        "pnl": {
            "unrealised": str(summary.unrealised_pnl),
            "unrealised_pct": str(summary.unrealised_pnl_pct),
            "realised": str(summary.realised_pnl),
            "total": str(summary.unrealised_pnl + summary.realised_pnl),
        },
        "position_count": summary.position_count,
        "positions": [
            {
                "instrument_id": p.instrument_id,
                "quantity": str(p.quantity),
                "avg_cost": str(p.avg_cost),
                "total_cost_basis": str(p.total_cost_basis),
                "last_price": str(p.last_price) if p.last_price else None,
                "market_value": str(p.market_value),
                "unrealised_pnl": str(p.unrealised_pnl),
                "unrealised_pnl_pct": str(p.unrealised_pnl_pct),
                "realised_pnl": str(p.realised_pnl),
            }
            for p in summary.positions
        ],
        "allocation": allocation,
    }


@router.get("/{account_id}/positions", summary="Positions with live valuation")
async def get_positions(
    account_id: str,
    is_paper: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_account(db, current_user, account_id)
    positions = await PortfolioEngine(db).get_positions(account_id, is_paper)
    return {
        "count": len(positions),
        "positions": [
            {
                "instrument_id": p.instrument_id,
                "quantity": str(p.quantity),
                "avg_cost": str(p.avg_cost),
                "last_price": str(p.last_price) if p.last_price else None,
                "market_value": str(p.market_value),
                "unrealised_pnl": str(p.unrealised_pnl),
                "unrealised_pnl_pct": str(p.unrealised_pnl_pct),
                "realised_pnl": str(p.realised_pnl),
            }
            for p in positions
        ],
    }


@router.get("/{account_id}/transactions", summary="Transaction history")
async def get_transactions(
    account_id: str,
    is_paper: bool = False,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FR-G-11: complete, immutable transaction history."""
    await _get_account(db, current_user, account_id)

    trades_result = await db.execute(
        select(Trade)
        .where(Trade.account_id == account_id)
        .where(Trade.is_paper.is_(is_paper))
        .order_by(desc(Trade.trade_date)).limit(limit)
    )
    trades = list(trades_result.scalars().all())

    cash_result = await db.execute(
        select(CashMovement)
        .where(CashMovement.account_id == account_id)
        .where(CashMovement.is_paper.is_(is_paper))
        .order_by(desc(CashMovement.created_at)).limit(limit)
    )
    movements = list(cash_result.scalars().all())

    return {
        "trades": [
            {
                "id": t.id,
                "order_id": t.order_id,
                "instrument_id": t.instrument_id,
                "side": t.side,
                "quantity": str(t.quantity),
                "price": str(t.price),
                "gross_consideration": str(t.gross_consideration),
                "commission": str(t.commission),
                "exchange_fee": str(t.exchange_fee),
                "tax": str(t.tax),
                "net_consideration": str(t.net_consideration),
                "settlement_date": t.settlement_date,
                "settlement_status": str(t.settlement_status),
                "trade_date": t.trade_date.isoformat() if t.trade_date else None,
            }
            for t in trades
        ],
        "cash_movements": [
            {
                "id": m.id,
                "type": m.movement_type,
                "amount": str(m.amount),
                "is_settled": m.is_settled,
                "value_date": m.value_date,
                "description": m.description,
            }
            for m in movements
        ],
    }
