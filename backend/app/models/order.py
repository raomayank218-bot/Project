"""Order model — Section 4 state machine + FR-A-01 to FR-A-17."""
import enum
from sqlalchemy import Column, String, Numeric, DateTime, Enum as SAEnum, Integer, Text, Boolean
from sqlalchemy.sql import func
from app.database import Base


class OrderState(str, enum.Enum):
    """Complete state list from spec Section 4. Every state has defined exits."""
    RECEIVED              = "RECEIVED"
    VALIDATED             = "VALIDATED"
    RISK_APPROVED         = "RISK_APPROVED"
    WORKING               = "WORKING"
    PARTIALLY_FILLED      = "PARTIALLY_FILLED"
    FILLED                = "FILLED"
    AMENDED               = "AMENDED"
    CLEARED               = "CLEARED"
    SETTLEMENT_INSTRUCTED = "SETTLEMENT_INSTRUCTED"
    MATCHED               = "MATCHED"
    SETTLED               = "SETTLED"
    # Failure / terminal
    REJECTED              = "REJECTED"
    CANCELLED             = "CANCELLED"
    EXPIRED               = "EXPIRED"
    SUSPENDED             = "SUSPENDED"
    EXCEPTION             = "EXCEPTION"
    SETTLEMENT_FAILED     = "SETTLEMENT_FAILED"


class OrderSide(str, enum.Enum):
    BUY  = "BUY"
    SELL = "SELL"


class OrderType(str, enum.Enum):
    MARKET     = "MARKET"
    LIMIT      = "LIMIT"
    STOP       = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, enum.Enum):
    DAY = "DAY"
    GTC = "GTC"   # Good-Till-Cancelled
    IOC = "IOC"   # Immediate-Or-Cancel
    FOK = "FOK"   # Fill-Or-Kill


class OrderSource(str, enum.Enum):
    GUI         = "GUI"
    COMMAND     = "COMMAND"
    ONE_CLICK   = "ONE_CLICK"
    NATURAL_LANG = "NATURAL_LANG"
    API         = "API"
    PAPER       = "PAPER"


class Order(Base):
    __tablename__ = "orders"

    id              = Column(String(36), primary_key=True)
    client_order_id = Column(String(100), nullable=True, index=True)  # client-supplied idempotency key
    version         = Column(Integer, nullable=False, default=1)
    parent_order_id = Column(String(36), nullable=True)               # for amendments

    # Who / where
    account_id      = Column(String(36), nullable=False, index=True)
    entering_user_id = Column(String(36), nullable=False)
    beneficiary_account_id = Column(String(36), nullable=True)        # delegated trading
    source          = Column(SAEnum(OrderSource), nullable=False, default=OrderSource.GUI)
    is_paper        = Column(Boolean, nullable=False, default=False)

    # What
    instrument_id   = Column(String(20), nullable=False, index=True)
    side            = Column(SAEnum(OrderSide), nullable=False)
    order_type      = Column(SAEnum(OrderType), nullable=False)
    quantity        = Column(Numeric(18, 4), nullable=False)
    price           = Column(Numeric(18, 4), nullable=True)           # null for market orders
    stop_price      = Column(Numeric(18, 4), nullable=True)
    time_in_force   = Column(SAEnum(TimeInForce), nullable=False, default=TimeInForce.DAY)

    # Execution progress
    filled_quantity = Column(Numeric(18, 4), nullable=False, default=0)
    avg_fill_price  = Column(Numeric(18, 4), nullable=True)
    remaining_qty   = Column(Numeric(18, 4), nullable=True)

    # State
    state           = Column(SAEnum(OrderState), nullable=False, default=OrderState.RECEIVED, index=True)
    reject_reason   = Column(Text, nullable=True)
    cancel_reason   = Column(Text, nullable=True)

    # Timestamps for each state transition
    received_at     = Column(DateTime(timezone=True), server_default=func.now())
    validated_at    = Column(DateTime(timezone=True), nullable=True)
    risk_approved_at = Column(DateTime(timezone=True), nullable=True)
    working_at      = Column(DateTime(timezone=True), nullable=True)
    filled_at       = Column(DateTime(timezone=True), nullable=True)
    settled_at      = Column(DateTime(timezone=True), nullable=True)
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())

    # Fees (computed after execution)
    commission      = Column(Numeric(18, 4), nullable=True)
    exchange_fee    = Column(Numeric(18, 4), nullable=True)
    tax             = Column(Numeric(18, 4), nullable=True)
    net_consideration = Column(Numeric(18, 4), nullable=True)
