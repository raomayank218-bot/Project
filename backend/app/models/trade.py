"""Trade lifecycle models — Fill through Settlement — FR-E-01 to FR-E-12."""
import enum
from sqlalchemy import Column, String, Numeric, DateTime, Enum as SAEnum, Text, Boolean, Integer
from sqlalchemy.sql import func
from app.database import Base


class SettlementStatus(str, enum.Enum):
    PENDING               = "PENDING"
    INSTRUCTED            = "INSTRUCTED"
    MATCHED               = "MATCHED"
    SETTLED               = "SETTLED"
    FAILED                = "FAILED"


class Fill(Base):
    """Individual execution against an order. One order can have many fills."""
    __tablename__ = "fills"

    id          = Column(String(36), primary_key=True)
    order_id    = Column(String(36), nullable=False, index=True)
    account_id  = Column(String(36), nullable=False, index=True)
    instrument_id = Column(String(20), nullable=False)
    side        = Column(String(4), nullable=False)
    quantity    = Column(Numeric(18, 4), nullable=False)
    price       = Column(Numeric(18, 4), nullable=False)
    venue       = Column(String(50), nullable=False, default="SIM_EXCHANGE")
    is_paper    = Column(Boolean, nullable=False, default=False)
    executed_at = Column(DateTime(timezone=True), nullable=False)
    commission  = Column(Numeric(18, 4), nullable=False, default=0)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


class Trade(Base):
    """Completed trade record — aggregation of fills for one order execution."""
    __tablename__ = "trades"

    id              = Column(String(36), primary_key=True)
    order_id        = Column(String(36), nullable=False, index=True)
    account_id      = Column(String(36), nullable=False, index=True)
    instrument_id   = Column(String(20), nullable=False, index=True)
    side            = Column(String(4), nullable=False)
    quantity        = Column(Numeric(18, 4), nullable=False)
    price           = Column(Numeric(18, 4), nullable=False)   # VWAP fill price
    currency        = Column(String(3), nullable=False, default="USD")
    gross_consideration = Column(Numeric(18, 4), nullable=False)
    commission      = Column(Numeric(18, 4), nullable=False, default=0)
    exchange_fee    = Column(Numeric(18, 4), nullable=False, default=0)
    tax             = Column(Numeric(18, 4), nullable=False, default=0)
    net_consideration = Column(Numeric(18, 4), nullable=False)
    settlement_date = Column(String(10), nullable=False)       # ISO date string
    settlement_status = Column(SAEnum(SettlementStatus), nullable=False,
                               default=SettlementStatus.PENDING)
    entering_user_id = Column(String(36), nullable=False)
    beneficiary_account_id = Column(String(36), nullable=True)
    source_channel  = Column(String(20), nullable=True)
    is_paper        = Column(Boolean, nullable=False, default=False)
    trade_date      = Column(DateTime(timezone=True), nullable=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class Position(Base):
    """Real-time position per account per instrument — FR-G-01 to FR-G-04."""
    __tablename__ = "positions"

    id            = Column(String(36), primary_key=True)
    account_id    = Column(String(36), nullable=False, index=True)
    instrument_id = Column(String(20), nullable=False, index=True)
    is_paper      = Column(Boolean, nullable=False, default=False)

    # Quantities
    quantity         = Column(Numeric(18, 4), nullable=False, default=0)  # settled + unsettled
    settled_quantity = Column(Numeric(18, 4), nullable=False, default=0)

    # Cost basis — FIFO method (FR-G-02)
    avg_cost         = Column(Numeric(18, 4), nullable=False, default=0)
    total_cost_basis = Column(Numeric(18, 4), nullable=False, default=0)

    # Realised P&L
    realised_pnl     = Column(Numeric(18, 4), nullable=False, default=0)

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CashMovement(Base):
    """Every cash debit/credit — FR-G-06."""
    __tablename__ = "cash_movements"

    id          = Column(String(36), primary_key=True)
    account_id  = Column(String(36), nullable=False, index=True)
    movement_type = Column(String(50), nullable=False)  # TRADE_BUY, TRADE_SELL, FEE, DIVIDEND
    amount      = Column(Numeric(18, 4), nullable=False)  # positive = credit, negative = debit
    currency    = Column(String(3), nullable=False, default="USD")
    trade_id    = Column(String(36), nullable=True)
    order_id    = Column(String(36), nullable=True)
    is_settled  = Column(Boolean, nullable=False, default=False)
    is_paper    = Column(Boolean, nullable=False, default=False)
    value_date  = Column(String(10), nullable=True)   # ISO date
    description = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


class SettlementInstruction(Base):
    """Settlement instruction — FR-E-03 to FR-E-07."""
    __tablename__ = "settlement_instructions"

    id              = Column(String(36), primary_key=True)
    trade_id        = Column(String(36), nullable=False, index=True)
    account_id      = Column(String(36), nullable=False)
    instrument_id   = Column(String(20), nullable=False)
    side            = Column(String(4), nullable=False)
    quantity        = Column(Numeric(18, 4), nullable=False)
    net_consideration = Column(Numeric(18, 4), nullable=False)
    currency        = Column(String(3), nullable=False, default="USD")
    settlement_date = Column(String(10), nullable=False)
    status          = Column(SAEnum(SettlementStatus), nullable=False,
                             default=SettlementStatus.PENDING)
    counterparty    = Column(String(100), nullable=False, default="SIM_CUSTODIAN")
    fail_reason     = Column(Text, nullable=True)
    ageing_days     = Column(Integer, nullable=False, default=0)
    instructed_at   = Column(DateTime(timezone=True), nullable=True)
    matched_at      = Column(DateTime(timezone=True), nullable=True)
    settled_at      = Column(DateTime(timezone=True), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
