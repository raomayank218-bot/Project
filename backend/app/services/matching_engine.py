"""
Matching engine — FR-D-01 to FR-D-07.

The simulation dataset has no order book depth, only OHLCV bars. We therefore
synthesise a realistic book around the last traded price: a spread derived from
the bar's high/low range, and depth levels sized from the bar's volume.

This gives:
  - Realistic fills (not idealised top-of-book execution)
  - Genuine slippage for large orders that consume multiple levels — FR-D-07
  - Deterministic behaviour for the same inputs — NFR-M-03
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
import hashlib

from app.models.order import OrderSide, OrderType, TimeInForce


TWO_PLACES = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass
class BookLevel:
    """One price level in the synthetic order book."""
    price: Decimal
    quantity: Decimal


@dataclass
class OrderBook:
    """
    Synthetic two-sided book for one instrument.
    bids sorted descending (best first), asks ascending (best first).
    """
    instrument_id: str
    bids: list[BookLevel] = field(default_factory=list)
    asks: list[BookLevel] = field(default_factory=list)
    reference_price: Decimal = Decimal("0")

    @property
    def best_bid(self) -> Optional[Decimal]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[Decimal]:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Optional[Decimal]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid


@dataclass
class FillResult:
    """One execution against a book level."""
    quantity: Decimal
    price: Decimal


@dataclass
class MatchResult:
    """Outcome of matching an order against the book."""
    fills: list[FillResult]
    filled_quantity: Decimal
    remaining_quantity: Decimal
    avg_price: Optional[Decimal]
    fully_filled: bool
    rejected: bool = False
    reject_reason: Optional[str] = None

    @property
    def has_fills(self) -> bool:
        return len(self.fills) > 0


class MatchingEngine:
    """
    Price-time priority matching against a synthetic order book.

    Determinism: the book is generated from the instrument's own price data
    using a seeded hash, so the same instrument + reference price always
    produces the same book. This makes tests reproducible — NFR-M-03.
    """

    # Book construction parameters
    DEPTH_LEVELS = 5
    BASE_SPREAD_BPS = Decimal("2")       # 2 basis points minimum spread
    LEVEL_STEP_BPS = Decimal("3")        # each level 3bps further out

    def build_book(
        self,
        instrument_id: str,
        reference_price: Decimal,
        bar_high: Optional[Decimal] = None,
        bar_low: Optional[Decimal] = None,
        bar_volume: Optional[Decimal] = None,
    ) -> OrderBook:
        """
        Construct a synthetic order book around the reference price.

        Spread widens with the bar's high-low range (a proxy for volatility).
        Depth is derived from bar volume, spread across DEPTH_LEVELS.
        """
        if reference_price <= 0:
            return OrderBook(instrument_id=instrument_id, reference_price=reference_price)

        # Spread: base + volatility component
        spread_bps = self.BASE_SPREAD_BPS
        if bar_high is not None and bar_low is not None and bar_low > 0:
            range_pct = ((bar_high - bar_low) / bar_low) * Decimal("10000")  # in bps
            spread_bps = self.BASE_SPREAD_BPS + (range_pct / Decimal("20"))
            spread_bps = min(spread_bps, Decimal("50"))  # cap at 50bps

        half_spread = reference_price * spread_bps / Decimal("20000")

        # Depth per level — derived from volume, with a sane floor
        if bar_volume and bar_volume > 0:
            # Assume a 1-min bar's volume is spread across the visible book
            level_qty = (Decimal(bar_volume) / Decimal("20")).quantize(Decimal("1"))
            level_qty = max(level_qty, Decimal("100"))
        else:
            level_qty = Decimal("1000")

        bids: list[BookLevel] = []
        asks: list[BookLevel] = []

        for i in range(self.DEPTH_LEVELS):
            offset = half_spread + (reference_price * self.LEVEL_STEP_BPS
                                    * Decimal(i) / Decimal("10000"))
            bid_price = _round(reference_price - offset)
            ask_price = _round(reference_price + offset)

            # Depth thins as you move away from touch
            qty = (level_qty * (Decimal("10") - Decimal(i)) / Decimal("10")).quantize(Decimal("1"))
            qty = max(qty, Decimal("1"))

            if bid_price > 0:
                bids.append(BookLevel(price=bid_price, quantity=qty))
            asks.append(BookLevel(price=ask_price, quantity=qty))

        return OrderBook(
            instrument_id=instrument_id,
            bids=bids,
            asks=asks,
            reference_price=reference_price,
        )

    def match(
        self,
        book: OrderBook,
        side: OrderSide,
        quantity: Decimal,
        order_type: OrderType,
        limit_price: Optional[Decimal] = None,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ) -> MatchResult:
        """
        Match an order against the book using price-time priority.

        A BUY consumes asks from best (lowest) upward.
        A SELL consumes bids from best (highest) downward.

        Handles:
          - MARKET: fills at whatever the book offers
          - LIMIT: fills only at prices at or better than the limit
          - IOC: fills what it can, cancels remainder
          - FOK: fills entirely or not at all
        """
        if quantity <= 0:
            return MatchResult([], Decimal("0"), quantity, None, False,
                               rejected=True, reject_reason="INVALID_QUANTITY")

        levels = book.asks if side == OrderSide.BUY else book.bids
        if not levels:
            return MatchResult([], Decimal("0"), quantity, None, False,
                               rejected=True, reject_reason="NO_LIQUIDITY")

        # ── FOK pre-check: can we fill the whole thing? ──────────────────
        if time_in_force == TimeInForce.FOK:
            available = Decimal("0")
            for lvl in levels:
                if not self._price_acceptable(side, lvl.price, order_type, limit_price):
                    break
                available += lvl.quantity
            if available < quantity:
                return MatchResult([], Decimal("0"), quantity, None, False,
                                   rejected=True, reject_reason="FOK_INSUFFICIENT_LIQUIDITY")

        # ── Walk the book ────────────────────────────────────────────────
        fills: list[FillResult] = []
        remaining = quantity

        for lvl in levels:
            if remaining <= 0:
                break
            if not self._price_acceptable(side, lvl.price, order_type, limit_price):
                break

            take = min(remaining, lvl.quantity)
            if take > 0:
                fills.append(FillResult(quantity=take, price=lvl.price))
                remaining -= take

        filled = quantity - remaining

        # ── IOC: cancel the remainder immediately ────────────────────────
        if time_in_force == TimeInForce.IOC:
            remaining = Decimal("0") if filled > 0 else quantity

        avg_price = None
        if filled > 0:
            total_value = sum(f.quantity * f.price for f in fills)
            avg_price = _round(Decimal(total_value) / filled)

        return MatchResult(
            fills=fills,
            filled_quantity=filled,
            remaining_quantity=quantity - filled,
            avg_price=avg_price,
            fully_filled=(filled == quantity),
        )

    @staticmethod
    def _price_acceptable(
        side: OrderSide,
        level_price: Decimal,
        order_type: OrderType,
        limit_price: Optional[Decimal],
    ) -> bool:
        """A market order accepts any price. A limit order accepts only at-or-better."""
        if order_type == OrderType.MARKET:
            return True
        if limit_price is None:
            return False
        if side == OrderSide.BUY:
            return level_price <= limit_price
        return level_price >= limit_price
