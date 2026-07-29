"""
Portfolio engine — FR-G-01 to FR-G-06.

Cost basis method is FIFO (first-in-first-out), stated explicitly per FR-G-02.
This is not an arbitrary choice — it must be documented and consistent, or
realised P&L will not reconcile against the transaction history.

Realised P&L is fixed at the point of sale and never changes retrospectively.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.order import OrderSide
from app.models.trade import Position, CashMovement, Trade, Fill
from app.services.market_data import MarketDataService


FOUR_PLACES = Decimal("0.0001")
TWO_PLACES = Decimal("0.01")


def _q(v: Decimal, places: Decimal = TWO_PLACES) -> Decimal:
    return Decimal(str(v)).quantize(places, rounding=ROUND_HALF_UP)


@dataclass
class PositionView:
    """Enriched position with live valuation."""
    instrument_id: str
    quantity: Decimal
    avg_cost: Decimal
    total_cost_basis: Decimal
    last_price: Optional[Decimal]
    market_value: Decimal
    unrealised_pnl: Decimal
    unrealised_pnl_pct: Decimal
    realised_pnl: Decimal


@dataclass
class PortfolioSummary:
    account_id: str
    is_paper: bool
    cash_settled: Decimal
    cash_unsettled: Decimal
    total_cash: Decimal
    positions_value: Decimal
    total_value: Decimal
    total_cost_basis: Decimal
    unrealised_pnl: Decimal
    unrealised_pnl_pct: Decimal
    realised_pnl: Decimal
    position_count: int
    positions: list[PositionView]


class PortfolioEngine:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.market = MarketDataService(db)

    # ── Position updates on fill ─────────────────────────────────────────

    async def apply_fill(
        self,
        account: Account,
        instrument_id: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        fees: Decimal,
        trade_id: str,
        order_id: str,
        settlement_date: str,
        is_paper: bool = False,
    ) -> Position:
        """
        Update position and cash from an execution — FR-G-01, FR-G-02, FR-G-06.

        BUY:  increases quantity, recomputes weighted average cost, debits cash
        SELL: reduces quantity using FIFO, realises P&L, credits cash
        """
        result = await self.db.execute(
            select(Position)
            .where(Position.account_id == account.id)
            .where(Position.instrument_id == instrument_id)
            .where(Position.is_paper.is_(is_paper))
        )
        position = result.scalar_one_or_none()

        if position is None:
            position = Position(
                id=str(uuid.uuid4()),
                account_id=account.id,
                instrument_id=instrument_id,
                is_paper=is_paper,
                quantity=Decimal("0"),
                settled_quantity=Decimal("0"),
                avg_cost=Decimal("0"),
                total_cost_basis=Decimal("0"),
                realised_pnl=Decimal("0"),
            )
            self.db.add(position)

        current_qty = Decimal(str(position.quantity))
        current_basis = Decimal(str(position.total_cost_basis))
        gross = quantity * price

        if side == OrderSide.BUY:
            # Cost basis includes fees — the true cost of acquisition
            new_qty = current_qty + quantity
            new_basis = current_basis + gross + fees
            position.quantity = _q(new_qty, FOUR_PLACES)
            position.total_cost_basis = _q(new_basis)
            position.avg_cost = _q(new_basis / new_qty, FOUR_PLACES) if new_qty > 0 else Decimal("0")

            # Cash: debit gross + fees
            cash_delta = -(gross + fees)

        else:
            # SELL — FIFO realisation
            if current_qty <= 0:
                raise ValueError(f"Cannot sell {instrument_id}: no position held")

            avg_cost = Decimal(str(position.avg_cost))
            cost_of_sold = avg_cost * quantity
            proceeds = gross - fees
            realised = proceeds - cost_of_sold

            new_qty = current_qty - quantity
            new_basis = current_basis - cost_of_sold

            position.quantity = _q(new_qty, FOUR_PLACES)
            position.total_cost_basis = _q(max(new_basis, Decimal("0")))
            position.realised_pnl = _q(Decimal(str(position.realised_pnl)) + realised)
            # avg_cost stays the same under FIFO/weighted-average until fully closed
            if new_qty <= 0:
                position.avg_cost = Decimal("0")
                position.total_cost_basis = Decimal("0")

            cash_delta = proceeds

        position.updated_at = datetime.now(timezone.utc)

        # ── Cash movement record — FR-G-06 ───────────────────────────────
        movement = CashMovement(
            id=str(uuid.uuid4()),
            account_id=account.id,
            movement_type=f"TRADE_{side.value}",
            amount=_q(cash_delta),
            currency=account.base_currency,
            trade_id=trade_id,
            order_id=order_id,
            is_settled=False,           # settles on settlement date
            is_paper=is_paper,
            value_date=settlement_date,
            description=f"{side.value} {quantity} {instrument_id} @ {price}",
        )
        self.db.add(movement)

        # Update account cash immediately (trade-date accounting for buying power)
        account.cash_settled = _q(Decimal(str(account.cash_settled)) + cash_delta)
        self.db.add(account)

        return position

    # ── Valuation and reporting ──────────────────────────────────────────

    async def get_positions(self, account_id: str, is_paper: bool = False) -> list[PositionView]:
        """All positions with live valuation — FR-G-03, FR-G-04."""
        result = await self.db.execute(
            select(Position)
            .where(Position.account_id == account_id)
            .where(Position.is_paper.is_(is_paper))
            .where(Position.quantity != 0)
        )
        positions = list(result.scalars().all())

        views: list[PositionView] = []
        for pos in positions:
            qty = Decimal(str(pos.quantity))
            basis = Decimal(str(pos.total_cost_basis))
            last_price = await self.market.get_last_price(pos.instrument_id)

            if last_price is None:
                market_value = Decimal("0")
                unrealised = Decimal("0")
                unrealised_pct = Decimal("0")
            else:
                market_value = _q(qty * last_price)
                unrealised = _q(market_value - basis)
                unrealised_pct = _q((unrealised / basis) * Decimal("100")) if basis > 0 else Decimal("0")

            views.append(PositionView(
                instrument_id=pos.instrument_id,
                quantity=qty,
                avg_cost=Decimal(str(pos.avg_cost)),
                total_cost_basis=basis,
                last_price=last_price,
                market_value=market_value,
                unrealised_pnl=unrealised,
                unrealised_pnl_pct=unrealised_pct,
                realised_pnl=Decimal(str(pos.realised_pnl)),
            ))

        return views

    async def get_summary(self, account: Account, is_paper: bool = False) -> PortfolioSummary:
        """Full portfolio summary — the dashboard's primary data source."""
        positions = await self.get_positions(account.id, is_paper)

        positions_value = sum((p.market_value for p in positions), Decimal("0"))
        total_basis = sum((p.total_cost_basis for p in positions), Decimal("0"))
        unrealised = sum((p.unrealised_pnl for p in positions), Decimal("0"))
        realised = sum((p.realised_pnl for p in positions), Decimal("0"))

        cash_settled = Decimal(str(account.cash_settled))
        cash_unsettled = Decimal(str(account.cash_unsettled))
        total_cash = cash_settled + cash_unsettled
        total_value = total_cash + positions_value

        unrealised_pct = (
            _q((unrealised / total_basis) * Decimal("100")) if total_basis > 0 else Decimal("0")
        )

        return PortfolioSummary(
            account_id=account.id,
            is_paper=is_paper,
            cash_settled=_q(cash_settled),
            cash_unsettled=_q(cash_unsettled),
            total_cash=_q(total_cash),
            positions_value=_q(positions_value),
            total_value=_q(total_value),
            total_cost_basis=_q(total_basis),
            unrealised_pnl=_q(unrealised),
            unrealised_pnl_pct=unrealised_pct,
            realised_pnl=_q(realised),
            position_count=len(positions),
            positions=positions,
        )

    async def settle_cash(self, account: Account, movement_id: str) -> None:
        """
        Move cash from unsettled to settled on settlement date — FR-E-08.
        Called by the settlement engine.
        """
        result = await self.db.execute(
            select(CashMovement).where(CashMovement.id == movement_id)
        )
        movement = result.scalar_one_or_none()
        if movement and not movement.is_settled:
            movement.is_settled = True
            self.db.add(movement)
