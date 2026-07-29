"""
Market data service — FR-L-02, FR-L-04, FR-E-02.

Critical: settlement dates are derived from the market_calendar table, which was
built from the ACTUAL data dates. The simulation dataset contains Saturdays and
no Mondays, so standard business-day logic would produce settlement dates that
fall on non-existent trading days.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import Price, MarketCalendar


class MarketDataService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_last_price(self, instrument_id: str) -> Optional[Decimal]:
        """
        Latest known close price for an instrument.
        Used for market order pricing and fat-finger checks.
        """
        result = await self.db.execute(
            select(Price.close)
            .where(Price.instrument_id == instrument_id)
            .order_by(Price.timestamp.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return Decimal(str(row)) if row is not None else None

    async def get_price_at(self, instrument_id: str, at: datetime) -> Optional[Decimal]:
        """Price at or immediately before a given timestamp."""
        result = await self.db.execute(
            select(Price.close)
            .where(Price.instrument_id == instrument_id)
            .where(Price.timestamp <= at)
            .order_by(Price.timestamp.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return Decimal(str(row)) if row is not None else None

    async def get_recent_bars(self, instrument_id: str, limit: int = 100,
                              interval: str = "1min") -> list[Price]:
        """Recent OHLCV bars — used by the matching engine for liquidity modelling."""
        result = await self.db.execute(
            select(Price)
            .where(Price.instrument_id == instrument_id)
            .where(Price.interval_type == interval)
            .order_by(Price.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_avg_daily_volume(self, instrument_id: str) -> Optional[Decimal]:
        """Average daily volume — used for fat-finger size checks."""
        result = await self.db.execute(
            select(func.avg(Price.volume))
            .where(Price.instrument_id == instrument_id)
            .where(Price.interval_type == "daily")
        )
        row = result.scalar_one_or_none()
        return Decimal(str(row)) if row is not None else None

    # ── Market calendar ──────────────────────────────────────────────────

    async def get_trading_dates(self) -> list[str]:
        """All trading dates in ascending order, from the derived calendar."""
        result = await self.db.execute(
            select(MarketCalendar.trading_date)
            .where(MarketCalendar.is_trading_day.is_(True))
            .order_by(MarketCalendar.trading_date)
        )
        return [r for r in result.scalars().all()]

    async def is_trading_day(self, date_iso: str) -> bool:
        result = await self.db.execute(
            select(MarketCalendar)
            .where(MarketCalendar.trading_date == date_iso)
            .where(MarketCalendar.is_trading_day.is_(True))
        )
        return result.scalar_one_or_none() is not None

    async def get_latest_trading_date(self) -> Optional[str]:
        result = await self.db.execute(
            select(func.max(MarketCalendar.trading_date))
        )
        return result.scalar_one_or_none()

    async def calculate_settlement_date(self, trade_date_iso: str,
                                        settlement_days: int = 1) -> str:
        """
        T+N settlement using the derived market calendar — FR-E-02.

        Walks forward N trading days from the trade date. If the trade date is
        not itself a trading day, starts from the next available trading day.
        If we run off the end of the calendar, returns the last known date
        (the simulation window is finite).
        """
        dates = await self.get_trading_dates()
        if not dates:
            return trade_date_iso

        # Find the index of the trade date, or the next trading day after it
        idx = None
        for i, d in enumerate(dates):
            if d == trade_date_iso:
                idx = i
                break
            if d > trade_date_iso:
                idx = i
                break

        if idx is None:
            # Trade date is after the end of the calendar
            return dates[-1]

        target = idx + settlement_days
        if target >= len(dates):
            return dates[-1]
        return dates[target]

    async def is_market_open(self, at: Optional[datetime] = None) -> tuple[bool, str]:
        """
        Whether the market is open — FR-B-12.
        Returns (is_open, reason).

        In this simulation the 'current' date is derived from the data window,
        not the wall clock, so we treat the market as open whenever the
        simulation calendar has data.
        """
        latest = await self.get_latest_trading_date()
        if latest is None:
            return False, "NO_CALENDAR_DATA"
        return True, "OPEN"
