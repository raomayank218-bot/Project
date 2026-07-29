"""
Settlement engine — FR-E-01 to FR-E-12.

This is the payoff of STP. Without settlement the platform is an order-entry
demo, not a straight-through platform.

Fee schedule (configurable reference data in production; constants here for MVP):
  commission   0.10% of gross, minimum 1.00
  exchange fee 0.005% of gross
  tax          0.05% on SELL only (stamp-duty analogue)
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderSide, OrderState
from app.models.trade import (
    Trade, SettlementInstruction, SettlementStatus, Position, CashMovement
)
from app.services.market_data import MarketDataService


TWO = Decimal("0.01")


def _q(v) -> Decimal:
    return Decimal(str(v)).quantize(TWO, rounding=ROUND_HALF_UP)


# ── Fee schedule ─────────────────────────────────────────────────────────
COMMISSION_RATE = Decimal("0.001")      # 0.10%
COMMISSION_MIN = Decimal("1.00")
EXCHANGE_FEE_RATE = Decimal("0.00005")  # 0.005%
SELL_TAX_RATE = Decimal("0.0005")       # 0.05% on sells only


@dataclass
class FeeBreakdown:
    gross: Decimal
    commission: Decimal
    exchange_fee: Decimal
    tax: Decimal
    total_fees: Decimal
    net: Decimal


def calculate_fees(side: OrderSide, quantity: Decimal, price: Decimal) -> FeeBreakdown:
    """
    FR-E-01: enrich a trade with fees, taxes and net consideration.
    Gross plus charges must reconcile exactly to net consideration.
    """
    gross = _q(quantity * price)

    commission = max(_q(gross * COMMISSION_RATE), COMMISSION_MIN)
    exchange_fee = _q(gross * EXCHANGE_FEE_RATE)
    tax = _q(gross * SELL_TAX_RATE) if side == OrderSide.SELL else Decimal("0.00")

    total_fees = _q(commission + exchange_fee + tax)

    # BUY: you pay gross + fees.  SELL: you receive gross - fees.
    net = _q(gross + total_fees) if side == OrderSide.BUY else _q(gross - total_fees)

    return FeeBreakdown(
        gross=gross,
        commission=commission,
        exchange_fee=exchange_fee,
        tax=tax,
        total_fees=total_fees,
        net=net,
    )


class SettlementEngine:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.market = MarketDataService(db)

    async def create_instruction(self, trade: Trade) -> SettlementInstruction:
        """
        FR-E-03: generate a settlement instruction automatically on execution.
        No manual input. Runs within seconds of the fill.
        """
        instruction = SettlementInstruction(
            id=str(uuid.uuid4()),
            trade_id=trade.id,
            account_id=trade.account_id,
            instrument_id=trade.instrument_id,
            side=trade.side,
            quantity=trade.quantity,
            net_consideration=trade.net_consideration,
            currency=trade.currency,
            settlement_date=trade.settlement_date,
            status=SettlementStatus.INSTRUCTED,
            counterparty="SIM_CUSTODIAN",
            instructed_at=datetime.now(timezone.utc),
        )
        self.db.add(instruction)

        trade.settlement_status = SettlementStatus.INSTRUCTED
        self.db.add(trade)

        return instruction

    async def match_instruction(self, instruction: SettlementInstruction) -> bool:
        """
        FR-E-05: match against the simulated counterparty record.

        In this simulation the custodian always confirms unless the instruction
        is incomplete — which is how we generate genuine EX-SET exceptions.
        """
        # Completeness check — an incomplete instruction cannot match
        if (instruction.quantity is None or Decimal(str(instruction.quantity)) <= 0
                or instruction.net_consideration is None
                or not instruction.settlement_date):
            instruction.status = SettlementStatus.FAILED
            instruction.fail_reason = "INCOMPLETE_INSTRUCTION"
            self.db.add(instruction)
            return False

        instruction.status = SettlementStatus.MATCHED
        instruction.matched_at = datetime.now(timezone.utc)
        self.db.add(instruction)
        return True

    async def settle(self, instruction: SettlementInstruction) -> bool:
        """
        FR-E-08: complete settlement — move cash and positions from unsettled
        to settled, and update books and records.
        """
        if instruction.status != SettlementStatus.MATCHED:
            return False

        # Mark the related cash movement as settled
        result = await self.db.execute(
            select(CashMovement).where(CashMovement.trade_id == instruction.trade_id)
        )
        for movement in result.scalars().all():
            movement.is_settled = True
            self.db.add(movement)

        # Move position quantity from unsettled to settled
        result = await self.db.execute(
            select(Position)
            .where(Position.account_id == instruction.account_id)
            .where(Position.instrument_id == instruction.instrument_id)
        )
        position = result.scalar_one_or_none()
        if position:
            position.settled_quantity = position.quantity
            self.db.add(position)

        instruction.status = SettlementStatus.SETTLED
        instruction.settled_at = datetime.now(timezone.utc)
        self.db.add(instruction)

        # Update the trade
        result = await self.db.execute(
            select(Trade).where(Trade.id == instruction.trade_id)
        )
        trade = result.scalar_one_or_none()
        if trade:
            trade.settlement_status = SettlementStatus.SETTLED
            self.db.add(trade)

        return True

    async def get_pending_settlements(self, account_id: Optional[str] = None
                                      ) -> list[SettlementInstruction]:
        """Instructions not yet settled — the operations view."""
        stmt = select(SettlementInstruction).where(
            SettlementInstruction.status.in_([
                SettlementStatus.PENDING,
                SettlementStatus.INSTRUCTED,
                SettlementStatus.MATCHED,
            ])
        )
        if account_id:
            stmt = stmt.where(SettlementInstruction.account_id == account_id)
        result = await self.db.execute(stmt.order_by(SettlementInstruction.settlement_date))
        return list(result.scalars().all())

    async def get_failed_settlements(self) -> list[SettlementInstruction]:
        """FR-E-07: failed settlements with ageing."""
        result = await self.db.execute(
            select(SettlementInstruction)
            .where(SettlementInstruction.status == SettlementStatus.FAILED)
            .order_by(SettlementInstruction.settlement_date)
        )
        return list(result.scalars().all())

    async def calculate_stp_rate(self) -> dict:
        """
        FR-E-12: percentage of trades completing the lifecycle without
        manual intervention.
        """
        from app.models.exception import TradingException

        total_result = await self.db.execute(
            select(Trade).where(Trade.is_paper.is_(False))
        )
        trades = list(total_result.scalars().all())
        total = len(trades)

        if total == 0:
            return {"stp_rate": None, "total_trades": 0, "manual_interventions": 0}

        # Trades that raised an exception at any lifecycle stage
        exc_result = await self.db.execute(
            select(TradingException.entity_id)
            .where(TradingException.entity_type.in_(["TRADE", "ORDER", "SETTLEMENT"]))
        )
        touched = {e for e in exc_result.scalars().all() if e}

        intervened = sum(1 for t in trades if t.id in touched or t.order_id in touched)
        clean = total - intervened

        return {
            "stp_rate": round((clean / total) * 100, 2),
            "total_trades": total,
            "straight_through": clean,
            "manual_interventions": intervened,
        }
