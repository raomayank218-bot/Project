"""
Fee calculation and command parser tests — FR-E-01, FR-A-13.
"""
import pytest
from decimal import Decimal

from app.services.settlement_engine import calculate_fees, COMMISSION_MIN
from app.services.order_service import CommandParser
from app.models.order import OrderSide, OrderType, TimeInForce


class TestFeeCalculation:
    """FR-E-01: gross plus charges must reconcile exactly to net consideration."""

    def test_buy_net_is_gross_plus_fees(self):
        f = calculate_fees(OrderSide.BUY, Decimal("100"), Decimal("200.00"))
        assert f.gross == Decimal("20000.00")
        assert f.net == f.gross + f.total_fees

    def test_sell_net_is_gross_minus_fees(self):
        f = calculate_fees(OrderSide.SELL, Decimal("100"), Decimal("200.00"))
        assert f.net == f.gross - f.total_fees

    def test_total_fees_sum_correctly(self):
        f = calculate_fees(OrderSide.BUY, Decimal("100"), Decimal("200.00"))
        assert f.total_fees == f.commission + f.exchange_fee + f.tax

    def test_commission_is_ten_bps(self):
        f = calculate_fees(OrderSide.BUY, Decimal("100"), Decimal("200.00"))
        # 20000 * 0.001 = 20.00
        assert f.commission == Decimal("20.00")

    def test_commission_minimum_applies(self):
        """A tiny trade still pays the minimum commission."""
        f = calculate_fees(OrderSide.BUY, Decimal("1"), Decimal("10.00"))
        assert f.commission == COMMISSION_MIN

    def test_no_tax_on_buy(self):
        f = calculate_fees(OrderSide.BUY, Decimal("100"), Decimal("200.00"))
        assert f.tax == Decimal("0.00")

    def test_tax_charged_on_sell(self):
        f = calculate_fees(OrderSide.SELL, Decimal("100"), Decimal("200.00"))
        assert f.tax > Decimal("0")

    def test_exchange_fee_charged_both_sides(self):
        buy = calculate_fees(OrderSide.BUY, Decimal("100"), Decimal("200.00"))
        sell = calculate_fees(OrderSide.SELL, Decimal("100"), Decimal("200.00"))
        assert buy.exchange_fee > 0 and sell.exchange_fee > 0
        assert buy.exchange_fee == sell.exchange_fee

    def test_all_values_two_decimal_places(self):
        """NFR-I-04: monetary values are fixed-point decimal, never float."""
        f = calculate_fees(OrderSide.SELL, Decimal("137"), Decimal("183.4567"))
        for v in [f.gross, f.commission, f.exchange_fee, f.tax, f.total_fees, f.net]:
            assert v.as_tuple().exponent >= -2, f"{v} has more than 2 decimal places"

    def test_sell_yields_less_than_gross(self):
        f = calculate_fees(OrderSide.SELL, Decimal("500"), Decimal("50.00"))
        assert f.net < f.gross

    def test_buy_costs_more_than_gross(self):
        f = calculate_fees(OrderSide.BUY, Decimal("500"), Decimal("50.00"))
        assert f.net > f.gross


class TestCommandParser:
    """FR-A-13: command syntax preserving what clients already know."""

    def test_simple_market_buy(self):
        req, err = CommandParser.parse("BUY 100 AAPL @MKT")
        assert err is None
        assert req.side == OrderSide.BUY
        assert req.quantity == Decimal("100")
        assert req.instrument_id == "AAPL"
        assert req.order_type == OrderType.MARKET

    def test_simple_market_sell(self):
        req, err = CommandParser.parse("SELL 50 MSFT @MKT")
        assert err is None
        assert req.side == OrderSide.SELL
        assert req.quantity == Decimal("50")

    def test_limit_order(self):
        req, err = CommandParser.parse("BUY 100 AAPL @185.50")
        assert err is None
        assert req.order_type == OrderType.LIMIT
        assert req.price == Decimal("185.50")

    def test_time_in_force_parsed(self):
        req, err = CommandParser.parse("BUY 100 AAPL @MKT IOC")
        assert err is None
        assert req.time_in_force == TimeInForce.IOC

    def test_default_time_in_force_is_day(self):
        req, err = CommandParser.parse("BUY 100 AAPL @MKT")
        assert req.time_in_force == TimeInForce.DAY

    def test_price_omitted_defaults_to_market(self):
        req, err = CommandParser.parse("BUY 100 AAPL")
        assert err is None
        assert req.order_type == OrderType.MARKET

    def test_case_insensitive(self):
        req, err = CommandParser.parse("buy 100 aapl @mkt")
        assert err is None
        assert req.side == OrderSide.BUY
        assert req.instrument_id == "AAPL"

    def test_comma_in_quantity(self):
        req, err = CommandParser.parse("BUY 1,000 AAPL @MKT")
        assert err is None
        assert req.quantity == Decimal("1000")

    def test_extra_whitespace_tolerated(self):
        req, err = CommandParser.parse("  BUY   100   AAPL   @MKT  ")
        assert err is None
        assert req.quantity == Decimal("100")

    # ── Error cases: messages must be specific and actionable ────────────

    def test_empty_command_error(self):
        req, err = CommandParser.parse("")
        assert req is None and err is not None

    def test_garbage_gives_helpful_error(self):
        req, err = CommandParser.parse("do the thing")
        assert req is None
        assert "Expected format" in err

    def test_missing_quantity_error(self):
        req, err = CommandParser.parse("BUY AAPL @MKT")
        assert req is None and err is not None

    def test_zero_quantity_rejected(self):
        req, err = CommandParser.parse("BUY 0 AAPL @MKT")
        assert req is None
        assert "greater than zero" in err

    def test_invalid_side_rejected(self):
        req, err = CommandParser.parse("HOLD 100 AAPL @MKT")
        assert req is None

    def test_invalid_tif_rejected(self):
        req, err = CommandParser.parse("BUY 100 AAPL @MKT FOREVER")
        assert req is None

    def test_negative_price_rejected(self):
        req, err = CommandParser.parse("BUY 100 AAPL @-5")
        assert req is None
