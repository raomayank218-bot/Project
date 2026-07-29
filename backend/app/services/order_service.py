"""
Order service — the STP orchestrator.

Runs an order through the complete lifecycle from spec Section 9:
  capture → enrich → validate → risk → route → execute → fill capture →
  confirm → position update → settlement instruction → match → settle

Every stage that fails routes to the exception queue rather than halting
the flow. No stage waits on a human on the happy path.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.state_machine import OrderStateMachine, StateMachineError
from app.models.account import Account
from app.models.instrument import Instrument
from app.models.order import (
    Order, OrderState, OrderSide, OrderType, TimeInForce, OrderSource
)
from app.models.trade import Fill, Trade, SettlementStatus
from app.models.exception import ExceptionCode, AuditLog
from app.models.user import User
from app.services.market_data import MarketDataService
from app.services.matching_engine import MatchingEngine
from app.services.risk_engine import RiskEngine, RiskCheckResult
from app.services.portfolio_engine import PortfolioEngine
from app.services.settlement_engine import SettlementEngine, calculate_fees
from app.services.exception_manager import ExceptionManager


@dataclass
class OrderRequest:
    """Normalised internal order — FR-A-02. All channels produce this."""
    account_id: str
    instrument_id: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    client_order_id: Optional[str] = None
    source: OrderSource = OrderSource.GUI
    is_paper: bool = False
    beneficiary_account_id: Optional[str] = None


@dataclass
class OrderResult:
    """Outcome of submitting an order through the full lifecycle."""
    success: bool
    order: Optional[Order] = None
    trade: Optional[Trade] = None
    fills: list = None
    reason_code: Optional[str] = None
    message: Optional[str] = None
    correlation_id: Optional[str] = None
    lifecycle: list = None      # trace of each stage for demonstration


class CommandParser:
    """
    FR-A-13: single-line command entry.
    Format: BUY|SELL <qty> <TICKER> [@MKT | @<price>] [DAY|GTC|IOC|FOK]

    Examples:
        BUY 100 AAPL @MKT
        SELL 50 MSFT @420.50 GTC
        BUY 200 TSLA @MKT IOC
    """
    PATTERN = re.compile(
        r"^\s*(?P<side>BUY|SELL)\s+"
        r"(?P<qty>[\d,]+(?:\.\d+)?)\s+"
        r"(?P<ticker>[A-Z]{1,10})"
        r"(?:\s+@\s*(?P<price>MKT|[\d.]+))?"
        r"(?:\s+(?P<tif>DAY|GTC|IOC|FOK))?"
        r"\s*$",
        re.IGNORECASE,
    )

    @classmethod
    def parse(cls, command: str) -> tuple[Optional[OrderRequest], Optional[str]]:
        """Returns (request, error_message). Errors are specific and actionable."""
        if not command or not command.strip():
            return None, "Empty command. Expected: BUY 100 AAPL @MKT"

        match = cls.PATTERN.match(command.strip())
        if not match:
            return None, (
                f"Could not parse '{command.strip()}'. "
                "Expected format: BUY|SELL <quantity> <TICKER> [@MKT|@<price>] [DAY|GTC|IOC|FOK]. "
                "Example: BUY 100 AAPL @MKT"
            )

        g = match.groupdict()

        try:
            quantity = Decimal(g["qty"].replace(",", ""))
        except (InvalidOperation, AttributeError):
            return None, f"Invalid quantity '{g['qty']}'."

        if quantity <= 0:
            return None, "Quantity must be greater than zero."

        price_token = (g.get("price") or "MKT").upper()
        if price_token == "MKT":
            order_type = OrderType.MARKET
            price = None
        else:
            order_type = OrderType.LIMIT
            try:
                price = Decimal(price_token)
            except InvalidOperation:
                return None, f"Invalid price '{price_token}'. Use @MKT or a number like @185.50."
            if price <= 0:
                return None, "Limit price must be greater than zero."

        tif_token = (g.get("tif") or "DAY").upper()
        try:
            tif = TimeInForce[tif_token]
        except KeyError:
            return None, f"Invalid time-in-force '{tif_token}'. Use DAY, GTC, IOC or FOK."

        return OrderRequest(
            account_id="",   # filled by caller
            instrument_id=g["ticker"].upper(),
            side=OrderSide[g["side"].upper()],
            quantity=quantity,
            order_type=order_type,
            price=price,
            time_in_force=tif,
            source=OrderSource.COMMAND,
        ), None


class OrderService:
    """Orchestrates the full STP lifecycle."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.market = MarketDataService(db)
        self.matching = MatchingEngine()
        self.risk = RiskEngine(db)
        self.portfolio = PortfolioEngine(db)
        self.settlement = SettlementEngine(db)
        self.exceptions = ExceptionManager(db)

    async def submit_order(
        self, request: OrderRequest, user: User,
    ) -> OrderResult:
        """
        Run an order through every lifecycle stage.
        Returns a full trace so the demonstration can show each step.
        """
        correlation_id = str(uuid.uuid4())
        lifecycle: list[dict] = []

        def stage(name: str, status: str, detail: str = ""):
            lifecycle.append({
                "stage": name,
                "status": status,
                "detail": detail,
                "at": datetime.now(timezone.utc).isoformat(),
            })

        # ── Stage 1: Capture ─────────────────────────────────────────────
        # FR-A-06: idempotency — reject duplicate client order IDs
        if request.client_order_id:
            existing = await self.db.execute(
                select(Order)
                .where(Order.client_order_id == request.client_order_id)
                .where(Order.account_id == request.account_id)
            )
            dupe = existing.scalar_one_or_none()
            if dupe:
                stage("capture", "DUPLICATE", f"Client order ID already seen: {dupe.id}")
                return OrderResult(
                    success=False, order=dupe,
                    reason_code="DUPLICATE_CLIENT_ORDER_ID",
                    message=f"Order with client_order_id '{request.client_order_id}' already exists.",
                    correlation_id=correlation_id, lifecycle=lifecycle,
                )

        order = Order(
            id=str(uuid.uuid4()),
            client_order_id=request.client_order_id,
            version=1,
            account_id=request.account_id,
            entering_user_id=user.id,
            beneficiary_account_id=request.beneficiary_account_id,
            source=request.source,
            is_paper=request.is_paper,
            instrument_id=request.instrument_id,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            stop_price=request.stop_price,
            time_in_force=request.time_in_force,
            filled_quantity=Decimal("0"),
            remaining_qty=request.quantity,
            state=OrderState.RECEIVED,
            received_at=datetime.now(timezone.utc),
        )
        self.db.add(order)
        await self.db.flush()

        sm = OrderStateMachine(order, self.db, correlation_id)
        stage("capture", "OK", f"Order {order.id} received via {request.source.value}")

        # ── Stage 2: Enrichment ──────────────────────────────────────────
        instrument = await self._get_instrument(request.instrument_id)
        if instrument is None:
            await sm.transition(OrderState.REJECTED, f"user:{user.id}", "UNKNOWN_INSTRUMENT")
            await self.exceptions.raise_exception(
                ExceptionCode.EX_REF,
                f"Unknown instrument '{request.instrument_id}' on order {order.id}",
                entity_type="ORDER", entity_id=order.id,
                account_id=request.account_id, correlation_id=correlation_id,
            )
            stage("enrichment", "FAILED", f"Instrument '{request.instrument_id}' not found")
            return OrderResult(False, order, reason_code="UNKNOWN_INSTRUMENT",
                               message=f"Instrument '{request.instrument_id}' does not exist.",
                               correlation_id=correlation_id, lifecycle=lifecycle)

        account = await self._get_account(request.account_id)
        if account is None:
            await sm.transition(OrderState.REJECTED, f"user:{user.id}", "UNKNOWN_ACCOUNT")
            stage("enrichment", "FAILED", "Account not found")
            return OrderResult(False, order, reason_code="UNKNOWN_ACCOUNT",
                               message="Account does not exist.",
                               correlation_id=correlation_id, lifecycle=lifecycle)

        stage("enrichment", "OK", f"{instrument.name} · {account.account_name}")

        # ── Stage 3: Validation ──────────────────────────────────────────
        validation = self._validate(request, instrument)
        if validation is not None:
            await sm.transition(OrderState.REJECTED, f"svc:validator", validation[0])
            stage("validation", "REJECTED", validation[1])
            return OrderResult(False, order, reason_code=validation[0],
                               message=validation[1],
                               correlation_id=correlation_id, lifecycle=lifecycle)

        await sm.transition(OrderState.VALIDATED, "svc:validator")
        stage("validation", "OK", "Field and business-rule validation passed")

        # ── Stage 4: Pre-trade risk ──────────────────────────────────────
        risk_result = await self.risk.check_order(
            account=account, instrument=instrument, side=request.side,
            quantity=request.quantity, order_type=request.order_type,
            limit_price=request.price, is_paper=request.is_paper,
        )

        if not risk_result.passed:
            await sm.transition(OrderState.REJECTED, "svc:risk", risk_result.reason_code)
            await self.exceptions.raise_exception(
                ExceptionCode.EX_RSK,
                f"Risk check failed on order {order.id}: {risk_result.message}",
                entity_type="ORDER", entity_id=order.id,
                account_id=account.id, instrument_id=instrument.id,
                detail=risk_result.detail, correlation_id=correlation_id,
            )
            stage("risk", "REJECTED", risk_result.message)
            return OrderResult(False, order, reason_code=risk_result.reason_code,
                               message=risk_result.message,
                               correlation_id=correlation_id, lifecycle=lifecycle)

        await sm.transition(OrderState.RISK_APPROVED, "svc:risk")
        stage("risk", "OK", "All pre-trade checks passed")

        # ── Stage 5: Routing ─────────────────────────────────────────────
        await sm.transition(OrderState.WORKING, "svc:router")
        stage("routing", "OK", "Routed to SIM_EXCHANGE")

        # ── Stage 6: Execution ───────────────────────────────────────────
        last_price = await self.market.get_last_price(instrument.id)
        bars = await self.market.get_recent_bars(instrument.id, limit=1)
        bar = bars[0] if bars else None

        book = self.matching.build_book(
            instrument_id=instrument.id,
            reference_price=last_price,
            bar_high=Decimal(str(bar.high)) if bar else None,
            bar_low=Decimal(str(bar.low)) if bar else None,
            bar_volume=Decimal(str(bar.volume)) if bar else None,
        )

        match_result = self.matching.match(
            book=book, side=request.side, quantity=request.quantity,
            order_type=request.order_type, limit_price=request.price,
            time_in_force=request.time_in_force,
        )

        if match_result.rejected:
            await sm.transition(OrderState.REJECTED, "svc:matching", match_result.reject_reason)
            stage("execution", "REJECTED", match_result.reject_reason)
            return OrderResult(False, order, reason_code=match_result.reject_reason,
                               message=f"Order could not be executed: {match_result.reject_reason}",
                               correlation_id=correlation_id, lifecycle=lifecycle)

        if not match_result.has_fills:
            # Limit order resting — legitimate outcome, not a failure
            stage("execution", "WORKING", "No immediate fill; order rests on the book")
            return OrderResult(True, order, reason_code=None,
                               message="Order is working — no immediate fill available.",
                               correlation_id=correlation_id, lifecycle=lifecycle)

        # ── Stage 7: Fill capture ────────────────────────────────────────
        fill_records = []
        now = datetime.now(timezone.utc)

        for f in match_result.fills:
            fill = Fill(
                id=str(uuid.uuid4()),
                order_id=order.id,
                account_id=account.id,
                instrument_id=instrument.id,
                side=request.side.value,
                quantity=f.quantity,
                price=f.price,
                venue="SIM_EXCHANGE",
                is_paper=request.is_paper,
                executed_at=now,
                commission=Decimal("0"),   # applied at trade level
            )
            self.db.add(fill)
            fill_records.append(fill)

        order.filled_quantity = match_result.filled_quantity
        order.remaining_qty = match_result.remaining_quantity
        order.avg_fill_price = match_result.avg_price

        if match_result.fully_filled:
            await sm.transition(OrderState.FILLED, "svc:matching")
        else:
            await sm.transition(OrderState.PARTIALLY_FILLED, "svc:matching")
            await sm.transition(OrderState.FILLED, "svc:matching")

        stage("fill_capture", "OK",
              f"{match_result.filled_quantity} filled across {len(match_result.fills)} "
              f"level(s) @ VWAP {match_result.avg_price}")

        # ── Stage 8: Clearing (fees, consideration, settlement date) ─────
        fees = calculate_fees(request.side, match_result.filled_quantity, match_result.avg_price)

        trade_date = now.date().isoformat()
        latest_trading = await self.market.get_latest_trading_date()
        effective_trade_date = latest_trading or trade_date
        settlement_date = await self.market.calculate_settlement_date(effective_trade_date, 1)

        trade = Trade(
            id=str(uuid.uuid4()),
            order_id=order.id,
            account_id=account.id,
            instrument_id=instrument.id,
            side=request.side.value,
            quantity=match_result.filled_quantity,
            price=match_result.avg_price,
            currency=instrument.currency,
            gross_consideration=fees.gross,
            commission=fees.commission,
            exchange_fee=fees.exchange_fee,
            tax=fees.tax,
            net_consideration=fees.net,
            settlement_date=settlement_date,
            settlement_status=SettlementStatus.PENDING,
            entering_user_id=user.id,
            beneficiary_account_id=request.beneficiary_account_id,
            source_channel=request.source.value,
            is_paper=request.is_paper,
            trade_date=now,
        )
        self.db.add(trade)

        order.commission = fees.commission
        order.exchange_fee = fees.exchange_fee
        order.tax = fees.tax
        order.net_consideration = fees.net

        await sm.transition(OrderState.CLEARED, "svc:clearing")
        stage("clearing", "OK",
              f"Gross {fees.gross} · fees {fees.total_fees} · net {fees.net} · "
              f"settles {settlement_date}")

        # ── Stage 9: Position and cash update ────────────────────────────
        try:
            await self.portfolio.apply_fill(
                account=account, instrument_id=instrument.id, side=request.side,
                quantity=match_result.filled_quantity, price=match_result.avg_price,
                fees=fees.total_fees, trade_id=trade.id, order_id=order.id,
                settlement_date=settlement_date, is_paper=request.is_paper,
            )
            stage("position_update", "OK", "Positions, cash and P&L updated")
        except Exception as e:
            await self.exceptions.raise_exception(
                ExceptionCode.EX_FIL,
                f"Position update failed for trade {trade.id}: {e}",
                entity_type="TRADE", entity_id=trade.id,
                account_id=account.id, correlation_id=correlation_id,
            )
            stage("position_update", "EXCEPTION", str(e))

        # ── Stage 10: Settlement instruction ─────────────────────────────
        instruction = await self.settlement.create_instruction(trade)
        await sm.transition(OrderState.SETTLEMENT_INSTRUCTED, "svc:settlement")
        stage("settlement_instruction", "OK",
              f"Instruction {instruction.id[:8]} issued, settles {settlement_date}")

        # ── Stage 11: Matching against custodian ─────────────────────────
        matched = await self.settlement.match_instruction(instruction)
        if matched:
            await sm.transition(OrderState.MATCHED, "svc:settlement")
            stage("settlement_matching", "OK", "Matched against SIM_CUSTODIAN")
        else:
            await self.exceptions.raise_exception(
                ExceptionCode.EX_SET,
                f"Settlement instruction {instruction.id} failed to match: "
                f"{instruction.fail_reason}",
                entity_type="SETTLEMENT", entity_id=instruction.id,
                account_id=account.id, correlation_id=correlation_id,
            )
            stage("settlement_matching", "EXCEPTION", instruction.fail_reason or "UNMATCHED")
            await self.db.flush()
            return OrderResult(True, order, trade, fill_records,
                               message="Order executed; settlement raised an exception.",
                               correlation_id=correlation_id, lifecycle=lifecycle)

        # ── Stage 12: Settlement ─────────────────────────────────────────
        settled = await self.settlement.settle(instruction)
        if settled:
            await sm.transition(OrderState.SETTLED, "svc:settlement")
            stage("settlement", "OK", f"Settled · books and records updated")
        else:
            stage("settlement", "PENDING", f"Awaiting settlement date {settlement_date}")

        await self.db.flush()

        return OrderResult(
            success=True, order=order, trade=trade, fills=fill_records,
            message=f"Order executed: {match_result.filled_quantity} {instrument.id} "
                    f"@ {match_result.avg_price}",
            correlation_id=correlation_id, lifecycle=lifecycle,
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _validate(self, request: OrderRequest, instrument: Instrument
                  ) -> Optional[tuple[str, str]]:
        """FR-A-03: field and business-rule validation. Returns (code, message) on failure."""
        if request.quantity <= 0:
            return ("INVALID_QUANTITY", "Quantity must be greater than zero.")

        lot_size = Decimal(str(instrument.lot_size))
        if lot_size > 0 and request.quantity % lot_size != 0:
            return ("INVALID_LOT_SIZE",
                    f"Quantity must be a multiple of the lot size ({lot_size}).")

        if request.order_type == OrderType.LIMIT:
            if request.price is None or request.price <= 0:
                return ("MISSING_LIMIT_PRICE", "A limit order requires a positive price.")
            tick = Decimal(str(instrument.tick_size))
            if tick > 0 and (request.price % tick) != 0:
                return ("INVALID_TICK_SIZE",
                        f"Price must be a multiple of the tick size ({tick}).")

        if request.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            if request.stop_price is None or request.stop_price <= 0:
                return ("MISSING_STOP_PRICE", "A stop order requires a positive stop price.")

        return None

    async def _get_instrument(self, instrument_id: str) -> Optional[Instrument]:
        result = await self.db.execute(
            select(Instrument).where(Instrument.id == instrument_id.upper())
        )
        return result.scalar_one_or_none()

    async def _get_account(self, account_id: str) -> Optional[Account]:
        result = await self.db.execute(
            select(Account).where(Account.id == account_id)
        )
        return result.scalar_one_or_none()

    async def cancel_order(self, order_id: str, user: User,
                           reason: str = "USER_CANCELLED") -> OrderResult:
        """FR-A-10: cancel a working order."""
        result = await self.db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if order is None:
            return OrderResult(False, reason_code="ORDER_NOT_FOUND",
                               message="Order does not exist.")

        sm = OrderStateMachine(order, self.db)
        try:
            await sm.transition(OrderState.CANCELLED, f"user:{user.id}", reason)
        except StateMachineError as e:
            return OrderResult(False, order, reason_code="CANNOT_CANCEL", message=str(e))

        return OrderResult(True, order, message="Order cancelled.")
