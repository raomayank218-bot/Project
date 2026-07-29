"""
Matching engine unit tests — FR-D-01 to FR-D-07.
NFR-M-02: mandatory coverage on every matching rule.
"""
import pytest
from decimal import Decimal

from app.services.matching_engine import MatchingEngine, OrderBook, BookLevel
from app.models.order import OrderSide, OrderType, TimeInForce


@pytest.fixture
def engine():
    return MatchingEngine()


def fixed_book() -> OrderBook:
    """
    Deterministic book for exact-value assertions.
      asks: 100.10 (100) · 100.20 (200) · 100.30 (300)
      bids:  99.90 (100) ·  99.80 (200) ·  99.70 (300)
    """
    return OrderBook(
        instrument_id="TEST",
        reference_price=Decimal("100.00"),
        asks=[
            BookLevel(Decimal("100.10"), Decimal("100")),
            BookLevel(Decimal("100.20"), Decimal("200")),
            BookLevel(Decimal("100.30"), Decimal("300")),
        ],
        bids=[
            BookLevel(Decimal("99.90"), Decimal("100")),
            BookLevel(Decimal("99.80"), Decimal("200")),
            BookLevel(Decimal("99.70"), Decimal("300")),
        ],
    )


class TestBookConstruction:

    def test_book_has_both_sides(self, engine):
        book = engine.build_book("AAPL", Decimal("200.00"))
        assert len(book.bids) > 0
        assert len(book.asks) > 0

    def test_best_bid_below_best_ask(self, engine):
        book = engine.build_book("AAPL", Decimal("200.00"))
        assert book.best_bid < book.best_ask

    def test_spread_is_positive(self, engine):
        book = engine.build_book("AAPL", Decimal("200.00"))
        assert book.spread > 0

    def test_bids_descending(self, engine):
        book = engine.build_book("AAPL", Decimal("200.00"))
        prices = [b.price for b in book.bids]
        assert prices == sorted(prices, reverse=True)

    def test_asks_ascending(self, engine):
        book = engine.build_book("AAPL", Decimal("200.00"))
        prices = [a.price for a in book.asks]
        assert prices == sorted(prices)

    def test_deterministic(self, engine):
        """Same inputs must produce the same book — NFR-M-03."""
        a = engine.build_book("AAPL", Decimal("200.00"), Decimal("201"), Decimal("199"), Decimal("50000"))
        b = engine.build_book("AAPL", Decimal("200.00"), Decimal("201"), Decimal("199"), Decimal("50000"))
        assert [l.price for l in a.asks] == [l.price for l in b.asks]
        assert [l.quantity for l in a.asks] == [l.quantity for l in b.asks]

    def test_wider_range_gives_wider_spread(self, engine):
        tight = engine.build_book("X", Decimal("100"), Decimal("100.1"), Decimal("99.9"), Decimal("10000"))
        wide = engine.build_book("X", Decimal("100"), Decimal("105"), Decimal("95"), Decimal("10000"))
        assert wide.spread > tight.spread

    def test_zero_price_gives_empty_book(self, engine):
        book = engine.build_book("X", Decimal("0"))
        assert book.bids == [] and book.asks == []


class TestPriceTimePriority:

    def test_buy_takes_best_ask_first(self, engine):
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("50"), OrderType.MARKET)
        assert result.fills[0].price == Decimal("100.10")

    def test_sell_takes_best_bid_first(self, engine):
        result = engine.match(fixed_book(), OrderSide.SELL, Decimal("50"), OrderType.MARKET)
        assert result.fills[0].price == Decimal("99.90")

    def test_walks_book_in_price_order(self, engine):
        """A 250-share buy consumes 100@100.10 then 150@100.20."""
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("250"), OrderType.MARKET)
        assert len(result.fills) == 2
        assert result.fills[0].price == Decimal("100.10")
        assert result.fills[0].quantity == Decimal("100")
        assert result.fills[1].price == Decimal("100.20")
        assert result.fills[1].quantity == Decimal("150")


class TestFillAccounting:

    def test_full_fill(self, engine):
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("100"), OrderType.MARKET)
        assert result.fully_filled
        assert result.filled_quantity == Decimal("100")
        assert result.remaining_quantity == Decimal("0")

    def test_vwap_across_levels(self, engine):
        """250 shares: (100 x 100.10 + 150 x 100.20) / 250 = 100.16"""
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("250"), OrderType.MARKET)
        assert result.avg_price == Decimal("100.16")

    def test_single_level_avg_equals_level_price(self, engine):
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("50"), OrderType.MARKET)
        assert result.avg_price == Decimal("100.10")

    def test_fill_quantities_sum_to_filled(self, engine):
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("450"), OrderType.MARKET)
        assert sum(f.quantity for f in result.fills) == result.filled_quantity

    def test_partial_fill_when_book_exhausted(self, engine):
        """Book has 600 on the ask side; a 1000 order fills 600."""
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("1000"), OrderType.MARKET)
        assert result.filled_quantity == Decimal("600")
        assert result.remaining_quantity == Decimal("400")
        assert not result.fully_filled


class TestSlippage:

    def test_large_order_worse_than_touch(self, engine):
        """FR-D-07: large orders consuming multiple levels get a worse average."""
        small = engine.match(fixed_book(), OrderSide.BUY, Decimal("50"), OrderType.MARKET)
        large = engine.match(fixed_book(), OrderSide.BUY, Decimal("500"), OrderType.MARKET)
        assert large.avg_price > small.avg_price

    def test_sell_slippage_is_downward(self, engine):
        small = engine.match(fixed_book(), OrderSide.SELL, Decimal("50"), OrderType.MARKET)
        large = engine.match(fixed_book(), OrderSide.SELL, Decimal("500"), OrderType.MARKET)
        assert large.avg_price < small.avg_price


class TestLimitOrders:

    def test_buy_limit_below_market_does_not_fill(self, engine):
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("100"),
                              OrderType.LIMIT, limit_price=Decimal("99.00"))
        assert not result.has_fills

    def test_buy_limit_at_ask_fills(self, engine):
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("100"),
                              OrderType.LIMIT, limit_price=Decimal("100.10"))
        assert result.fully_filled

    def test_buy_limit_stops_at_limit_price(self, engine):
        """Limit 100.20 fills the 100.10 and 100.20 levels only, not 100.30."""
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("600"),
                              OrderType.LIMIT, limit_price=Decimal("100.20"))
        assert result.filled_quantity == Decimal("300")   # 100 + 200
        assert all(f.price <= Decimal("100.20") for f in result.fills)

    def test_sell_limit_above_market_does_not_fill(self, engine):
        result = engine.match(fixed_book(), OrderSide.SELL, Decimal("100"),
                              OrderType.LIMIT, limit_price=Decimal("101.00"))
        assert not result.has_fills

    def test_sell_limit_stops_at_limit_price(self, engine):
        result = engine.match(fixed_book(), OrderSide.SELL, Decimal("600"),
                              OrderType.LIMIT, limit_price=Decimal("99.80"))
        assert result.filled_quantity == Decimal("300")
        assert all(f.price >= Decimal("99.80") for f in result.fills)


class TestTimeInForce:

    def test_ioc_cancels_remainder(self, engine):
        """FR-A-08: IOC fills what it can and cancels the rest."""
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("1000"),
                              OrderType.MARKET, time_in_force=TimeInForce.IOC)
        assert result.filled_quantity == Decimal("600")
        assert result.remaining_quantity == Decimal("400")

    def test_fok_rejects_when_insufficient(self, engine):
        """FR-A-08: FOK cancels entirely unless fully fillable."""
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("1000"),
                              OrderType.MARKET, time_in_force=TimeInForce.FOK)
        assert result.rejected
        assert result.reject_reason == "FOK_INSUFFICIENT_LIQUIDITY"
        assert result.filled_quantity == Decimal("0")

    def test_fok_fills_when_sufficient(self, engine):
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("300"),
                              OrderType.MARKET, time_in_force=TimeInForce.FOK)
        assert result.fully_filled

    def test_day_order_reports_remaining(self, engine):
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("1000"),
                              OrderType.MARKET, time_in_force=TimeInForce.DAY)
        assert result.remaining_quantity == Decimal("400")


class TestRejections:

    def test_zero_quantity_rejected(self, engine):
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("0"), OrderType.MARKET)
        assert result.rejected
        assert result.reject_reason == "INVALID_QUANTITY"

    def test_negative_quantity_rejected(self, engine):
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("-100"), OrderType.MARKET)
        assert result.rejected

    def test_empty_book_rejected(self, engine):
        empty = OrderBook(instrument_id="X", reference_price=Decimal("100"))
        result = engine.match(empty, OrderSide.BUY, Decimal("100"), OrderType.MARKET)
        assert result.rejected
        assert result.reject_reason == "NO_LIQUIDITY"

    def test_limit_order_without_price_does_not_fill(self, engine):
        result = engine.match(fixed_book(), OrderSide.BUY, Decimal("100"),
                              OrderType.LIMIT, limit_price=None)
        assert not result.has_fills
