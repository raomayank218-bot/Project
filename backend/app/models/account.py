"""Client account model — FR-M-06."""
import enum
from sqlalchemy import Column, String, Boolean, Numeric, DateTime, Enum as SAEnum, Text
from sqlalchemy.sql import func
from app.database import Base


class AccountStatus(str, enum.Enum):
    ACTIVE    = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED    = "CLOSED"


class Account(Base):
    __tablename__ = "accounts"

    id              = Column(String(36), primary_key=True)
    client_id       = Column(String(36), nullable=False, index=True)
    account_name    = Column(String(200), nullable=False)
    account_type    = Column(String(50), nullable=False, default="CASH")
    base_currency   = Column(String(3), nullable=False, default="USD")
    status          = Column(String(20), nullable=False, default=AccountStatus.ACTIVE)
    is_paper        = Column(Boolean, nullable=False, default=False)  # paper trading account

    # Financial limits
    credit_limit        = Column(Numeric(18, 2), nullable=False, default=0)
    daily_notional_limit = Column(Numeric(18, 2), nullable=False, default=5_000_000)
    max_position_pct    = Column(Numeric(5, 2), nullable=False, default=25.0)  # concentration %

    # Cash balances (updated by portfolio engine)
    cash_settled     = Column(Numeric(18, 2), nullable=False, default=100_000)
    cash_unsettled   = Column(Numeric(18, 2), nullable=False, default=0)

    notes       = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    @property
    def buying_power(self) -> float:
        """Available to trade = settled cash only (conservative)."""
        return float(self.cash_settled)

    @property
    def total_cash(self) -> float:
        return float(self.cash_settled) + float(self.cash_unsettled)
