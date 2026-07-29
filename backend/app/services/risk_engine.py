"""
Pre-trade risk engine — FR-B-01 to FR-B-12.

Every check here runs automatically inside the order path, not as a manual
approval gate. Speed and control are not traded off — FR-B-09 / NFR-P-01.

Check order matters: cheapest and most likely to fail first.
"""
from dataclasses import dataclass
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountStatus
from app.models.instrument import Instrument
from app.models.order import Order, OrderSide, OrderType, OrderState
from app.models.trade import Position
from app.models.market import RiskLimit, LimitScope, LimitType
from app.services.market_data import MarketDataService


@dataclass
class RiskCheckResult:
    """Outcome of the full pre-trade check set."""
    passed: bool
    reason_code: Optional[str] = None
    message: Optional[str] = None
    detail: Optional[dict] = None

    @staticmethod
    def ok() -> "RiskCheckResult":
        return RiskCheckResult(passed=True)

    @staticmethod
    def fail(code: str, message: str, detail: dict = None) -> "RiskCheckResult":
        return RiskCheckResult(passed=False, reason_code=code,
                               message=message, detail=detail or {})


# Global kill switch state — FR-B-08
# In production this would live in Redis or the database; for the MVP an
# in-process flag plus a database-backed check is sufficient.
class KillSwitch:
    _active: bool = False
    _activated_by: Optional[str] = None
    _activated_at: Optional[datetime] = None

    @classmethod
    def activate(cls, user_id: str):
        cls._active = True
        cls._activated_by = user_id
        cls._activated_at = datetime.now(timezone.utc)

    @classmethod
    def deactivate(cls, user_id: str):
        cls._active = False
        cls._activated_by = None
        cls._activated_at = None

    @classmethod
    def is_active(cls) -> bool:
        return cls._active

    @classmethod
    def status(cls) -> dict:
        return {
            "active": cls._active,
            "activated_by": cls._activated_by,
            "activated_at": cls._activated_at.isoformat() if cls._activated_at else None,
        }


class RiskEngine:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.market = MarketDataService(db)

    async def check_order(
        self,
        account: Account,
        instrument: Instrument,
        side: OrderSide,
        quantity: Decimal,
        order_type: OrderType,
        limit_price: Optional[Decimal] = None,
        is_paper: bool = False,
    ) -> RiskCheckResult:
        """
        Run the complete pre-trade check set.
        Returns on the first failure — fail fast.
        """
        # ── FR-B-08: kill switch (cheapest check, highest priority) ──────
        if KillSwitch.is_active() and not is_paper:
            return RiskCheckResult.fail(
                "KILL_SWITCH_ACTIVE",
                "Trading is halted. All order submission is suspended.",
                KillSwitch.status(),
            )

        # ── Account status ───────────────────────────────────────────────
        if account.status != AccountStatus.ACTIVE:
            return RiskCheckResult.fail(
                "ACCOUNT_NOT_ACTIVE",
                f"Account status is {account.status}. Trading is not permitted.",
                {"account_status": str(account.status)},
            )

        # ── FR-B-07: restricted instrument screening ─────────────────────
        if instrument.is_restricted:
            return RiskCheckResult.fail(
                "INSTRUMENT_RESTRICTED",
                f"{instrument.id} is on the restricted list.",
                {"reason": instrument.restrict_reason},
            )

        if not instrument.is_tradable:
            return RiskCheckResult.fail(
                "INSTRUMENT_NOT_TRADABLE",
                f"{instrument.id} is not currently tradable.",
            )

        # ── FR-B-12: market state ────────────────────────────────────────
        is_open, market_reason = await self.market.is_market_open()
        if not is_open:
            return RiskCheckResult.fail(
                "MARKET_CLOSED",
                "The market is closed for this instrument.",
                {"reason": market_reason},
            )

        # ── Reference price (needed for all value-based checks) ──────────
        last_price = await self.market.get_last_price(instrument.id)
        if last_price is None:
            return RiskCheckResult.fail(
                "NO_PRICE_DATA",
                f"No price data available for {instrument.id}.",
            )

        # Effective price for notional calculations
        effective_price = limit_price if (order_type == OrderType.LIMIT and limit_price) else last_price
        notional = quantity * effective_price

        # ── FR-B-05: fat-finger checks ───────────────────────────────────
        fat_finger = await self._check_fat_finger(
            instrument, quantity, effective_price, last_price, notional
        )
        if not fat_finger.passed:
            return fat_finger

        # ── FR-B-04: notional limits ─────────────────────────────────────
        notional_check = await self._check_notional_limits(account, notional, is_paper)
        if not notional_check.passed:
            return notional_check

        # ── FR-B-02: buying power / holdings ─────────────────────────────
        funds_check = await self._check_funds_and_holdings(
            account, instrument, side, quantity, notional, is_paper
        )
        if not funds_check.passed:
            return funds_check

        # ── FR-B-03: position limits ─────────────────────────────────────
        position_check = await self._check_position_limit(
            account, instrument, side, quantity, is_paper
        )
        if not position_check.passed:
            return position_check

        # ── FR-B-06: concentration limits ────────────────────────────────
        concentration = await self._check_concentration(
            account, instrument, side, quantity, effective_price, is_paper
        )
        if not concentration.passed:
            return concentration

        return RiskCheckResult.ok()

    # ── Individual checks ────────────────────────────────────────────────

    async def _check_fat_finger(
        self, instrument: Instrument, quantity: Decimal,
        effective_price: Decimal, last_price: Decimal, notional: Decimal,
    ) -> RiskCheckResult:
        """FR-B-05: block orders implausibly far from market, or implausibly large."""

        # Price deviation check
        price_limit = await self._get_limit(LimitType.FAT_FINGER_PRICE, default=Decimal("10"))
        if last_price > 0:
            deviation_pct = abs((effective_price - last_price) / last_price) * Decimal("100")
            if deviation_pct > price_limit:
                return RiskCheckResult.fail(
                    "FAT_FINGER_PRICE",
                    f"Order price {effective_price} deviates {deviation_pct:.1f}% from "
                    f"last traded price {last_price}. Limit is {price_limit}%.",
                    {"deviation_pct": float(deviation_pct), "limit_pct": float(price_limit),
                     "last_price": float(last_price)},
                )

        # Notional size check
        notional_limit = await self._get_limit(
            LimitType.FAT_FINGER_NOTIONAL, default=Decimal("1000000")
        )
        if notional > notional_limit:
            return RiskCheckResult.fail(
                "FAT_FINGER_NOTIONAL",
                f"Order notional {notional:,.2f} exceeds the single-order limit "
                f"of {notional_limit:,.2f}.",
                {"notional": float(notional), "limit": float(notional_limit)},
            )

        # Volume sanity — order shouldn't exceed a share of average daily volume
        adv = await self.market.get_avg_daily_volume(instrument.id)
        if adv and adv > 0 and quantity > adv:
            return RiskCheckResult.fail(
                "FAT_FINGER_VOLUME",
                f"Order quantity {quantity:,.0f} exceeds average daily volume "
                f"{adv:,.0f} for {instrument.id}.",
                {"quantity": float(quantity), "avg_daily_volume": float(adv)},
            )

        return RiskCheckResult.ok()

    async def _check_notional_limits(
        self, account: Account, notional: Decimal, is_paper: bool
    ) -> RiskCheckResult:
        """FR-B-04: per-order and cumulative daily notional caps."""
        daily_limit = Decimal(str(account.daily_notional_limit))

        # Cumulative traded notional today
        today = datetime.now(timezone.utc).date()
        result = await self.db.execute(
            select(func.coalesce(func.sum(Order.quantity * Order.avg_fill_price), 0))
            .where(Order.account_id == account.id)
            .where(Order.is_paper.is_(is_paper))
            .where(Order.state.in_([
                OrderState.FILLED, OrderState.CLEARED,
                OrderState.SETTLEMENT_INSTRUCTED, OrderState.MATCHED, OrderState.SETTLED,
            ]))
            .where(func.date(Order.received_at) == today)
        )
        used_today = Decimal(str(result.scalar_one() or 0))

        if used_today + notional > daily_limit:
            return RiskCheckResult.fail(
                "DAILY_NOTIONAL_EXCEEDED",
                f"Order would breach the daily notional limit. "
                f"Used {used_today:,.2f} of {daily_limit:,.2f}; "
                f"this order adds {notional:,.2f}.",
                {"used_today": float(used_today), "limit": float(daily_limit),
                 "order_notional": float(notional)},
            )

        return RiskCheckResult.ok()

    async def _check_funds_and_holdings(
        self, account: Account, instrument: Instrument, side: OrderSide,
        quantity: Decimal, notional: Decimal, is_paper: bool,
    ) -> RiskCheckResult:
        """FR-B-02: buying power for buys, sufficient holdings for sells."""

        if side == OrderSide.BUY:
            buying_power = Decimal(str(account.cash_settled))
            if notional > buying_power:
                return RiskCheckResult.fail(
                    "INSUFFICIENT_BUYING_POWER",
                    f"Order requires {notional:,.2f} but only {buying_power:,.2f} "
                    f"in settled cash is available.",
                    {"required": float(notional), "available": float(buying_power)},
                )
        else:
            # SELL — must hold enough (no short selling in the MVP)
            result = await self.db.execute(
                select(Position)
                .where(Position.account_id == account.id)
                .where(Position.instrument_id == instrument.id)
                .where(Position.is_paper.is_(is_paper))
            )
            position = result.scalar_one_or_none()
            held = Decimal(str(position.quantity)) if position else Decimal("0")

            if quantity > held:
                return RiskCheckResult.fail(
                    "INSUFFICIENT_HOLDINGS",
                    f"Cannot sell {quantity:,.0f} {instrument.id} — "
                    f"position is {held:,.0f}. Short selling is not permitted.",
                    {"requested": float(quantity), "held": float(held)},
                )

        return RiskCheckResult.ok()

    async def _check_position_limit(
        self, account: Account, instrument: Instrument, side: OrderSide,
        quantity: Decimal, is_paper: bool,
    ) -> RiskCheckResult:
        """FR-B-03: maximum position size per instrument."""
        if side == OrderSide.SELL:
            return RiskCheckResult.ok()  # selling reduces position

        limit = await self._get_limit(LimitType.POSITION_SIZE, default=Decimal("10000"))

        result = await self.db.execute(
            select(Position)
            .where(Position.account_id == account.id)
            .where(Position.instrument_id == instrument.id)
            .where(Position.is_paper.is_(is_paper))
        )
        position = result.scalar_one_or_none()
        current = Decimal(str(position.quantity)) if position else Decimal("0")

        if current + quantity > limit:
            return RiskCheckResult.fail(
                "POSITION_LIMIT_EXCEEDED",
                f"Order would take the {instrument.id} position to "
                f"{current + quantity:,.0f}, exceeding the limit of {limit:,.0f}.",
                {"current": float(current), "requested": float(quantity),
                 "limit": float(limit)},
            )

        return RiskCheckResult.ok()

    async def _check_concentration(
        self, account: Account, instrument: Instrument, side: OrderSide,
        quantity: Decimal, price: Decimal, is_paper: bool,
    ) -> RiskCheckResult:
        """FR-B-06: no single holding above a configured % of portfolio value."""
        if side == OrderSide.SELL:
            return RiskCheckResult.ok()

        max_pct = Decimal(str(account.max_position_pct))

        # Current portfolio value = cash + all position market values
        result = await self.db.execute(
            select(Position)
            .where(Position.account_id == account.id)
            .where(Position.is_paper.is_(is_paper))
        )
        positions = list(result.scalars().all())

        portfolio_value = Decimal(str(account.cash_settled)) + Decimal(str(account.cash_unsettled))
        instrument_value = Decimal("0")

        for pos in positions:
            pos_price = await self.market.get_last_price(pos.instrument_id)
            if pos_price is None:
                continue
            value = Decimal(str(pos.quantity)) * pos_price
            portfolio_value += value
            if pos.instrument_id == instrument.id:
                instrument_value = value

        order_value = quantity * price
        new_instrument_value = instrument_value + order_value
        new_portfolio_value = portfolio_value  # cash converts to stock; total unchanged

        if new_portfolio_value <= 0:
            return RiskCheckResult.ok()

        concentration_pct = (new_instrument_value / new_portfolio_value) * Decimal("100")

        if concentration_pct > max_pct:
            return RiskCheckResult.fail(
                "CONCENTRATION_LIMIT_EXCEEDED",
                f"Order would take {instrument.id} to {concentration_pct:.1f}% "
                f"of portfolio value, exceeding the {max_pct}% limit.",
                {"resulting_pct": float(concentration_pct), "limit_pct": float(max_pct)},
            )

        return RiskCheckResult.ok()

    async def _get_limit(self, limit_type: LimitType, default: Decimal) -> Decimal:
        """Fetch an approved, active global limit — falls back to the default."""
        result = await self.db.execute(
            select(RiskLimit.value)
            .where(RiskLimit.limit_type == limit_type)
            .where(RiskLimit.scope == LimitScope.GLOBAL)
            .where(RiskLimit.is_active.is_(True))
            .where(RiskLimit.is_approved.is_(True))
            .limit(1)
        )
        value = result.scalar_one_or_none()
        return Decimal(str(value)) if value is not None else default
