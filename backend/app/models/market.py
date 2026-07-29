"""Price data and risk limit models — FR-L-02, FR-B-01 to FR-B-12."""
import enum
from sqlalchemy import Column, String, Numeric, DateTime, Boolean, Integer, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.sql import func
from app.database import Base


class Price(Base):
    """
    Time-series price data — ingested from simulation dataset.
    TimescaleDB hypertable is created in migration.
    Columns: instrument_id + timestamp form the natural key.
    """
    __tablename__ = "prices"

    id            = Column(String(36), primary_key=True)
    instrument_id = Column(String(20), nullable=False, index=True)
    timestamp     = Column(DateTime(timezone=True), nullable=False, index=True)
    interval_type = Column(String(10), nullable=False, default="1min")  # 1min, daily
    open          = Column(Numeric(18, 4), nullable=False)
    high          = Column(Numeric(18, 4), nullable=False)
    low           = Column(Numeric(18, 4), nullable=False)
    close         = Column(Numeric(18, 4), nullable=False)
    volume        = Column(Numeric(18, 0), nullable=False)
    # For daily bars
    adjusted_close   = Column(Numeric(18, 4), nullable=True)
    dividend_amount  = Column(Numeric(18, 4), nullable=True)
    split_coefficient = Column(Numeric(10, 4), nullable=True)
    source        = Column(String(50), nullable=False, default="simulation")
    loaded_at     = Column(DateTime(timezone=True), server_default=func.now())


class MarketCalendar(Base):
    """
    Derived from the actual data dates — not a hard-coded weekday rule.
    Built by ingest_data.py from the distinct dates in the CSV files.
    Used by settlement engine for T+1 calculation — FR-E-02.
    """
    __tablename__ = "market_calendar"

    trading_date = Column(String(10), primary_key=True)  # ISO date YYYY-MM-DD
    is_trading_day = Column(Boolean, nullable=False, default=True)
    session_open   = Column(String(5), nullable=False, default="09:30")
    session_close  = Column(String(5), nullable=False, default="15:59")
    notes          = Column(Text, nullable=True)


class LimitScope(str, enum.Enum):
    GLOBAL     = "GLOBAL"
    ACCOUNT    = "ACCOUNT"
    INSTRUMENT = "INSTRUMENT"


class LimitType(str, enum.Enum):
    DAILY_NOTIONAL      = "DAILY_NOTIONAL"
    POSITION_SIZE       = "POSITION_SIZE"
    CREDIT              = "CREDIT"
    CONCENTRATION_PCT   = "CONCENTRATION_PCT"
    FAT_FINGER_PRICE    = "FAT_FINGER_PRICE"
    FAT_FINGER_NOTIONAL = "FAT_FINGER_NOTIONAL"


class RiskLimit(Base):
    """Configurable risk limits — FR-B-01 to FR-B-09."""

    __tablename__ = "risk_limits"

    id          = Column(String(36), primary_key=True)
    scope       = Column(SAEnum(LimitScope), nullable=False)
    limit_type  = Column(SAEnum(LimitType), nullable=False)
    scope_id    = Column(String(36), nullable=True)   # account_id or instrument_id; null = global
    value       = Column(Numeric(18, 4), nullable=False)
    currency    = Column(String(3), nullable=False, default="USD")
    is_active   = Column(Boolean, nullable=False, default=True)
    # Maker-checker — FR-B-09
    created_by  = Column(String(36), nullable=False)
    approved_by = Column(String(36), nullable=True)
    is_approved = Column(Boolean, nullable=False, default=False)
    effective_from = Column(String(10), nullable=True)
    effective_to   = Column(String(10), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


class SentimentScore(Base):
    """Pre-computed daily sentiment from news JSON — FR-K-04."""
    __tablename__ = "sentiment_scores"

    id            = Column(String(36), primary_key=True)
    instrument_id = Column(String(20), nullable=False, index=True)
    score_date    = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    avg_score     = Column(Numeric(6, 4), nullable=False)           # -1 to +1
    article_count = Column(Integer, nullable=False, default=0)
    label         = Column(String(30), nullable=True)               # Bullish/Neutral/Bearish
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
