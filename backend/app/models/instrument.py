"""Instrument master — FR-L-01."""
from sqlalchemy import Column, String, Boolean, Numeric, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base


class Instrument(Base):
    __tablename__ = "instruments"

    id          = Column(String(20), primary_key=True)   # ticker e.g. AAPL
    isin        = Column(String(12), unique=True, nullable=True)
    name        = Column(String(200), nullable=False)
    asset_class = Column(String(50), nullable=False, default="EQUITY")
    currency    = Column(String(3), nullable=False, default="USD")
    exchange    = Column(String(20), nullable=False, default="NASDAQ")
    sector      = Column(String(100), nullable=True)
    geography   = Column(String(100), nullable=True)
    lot_size    = Column(Numeric(18, 4), nullable=False, default=1)
    tick_size   = Column(Numeric(18, 4), nullable=False, default=0.01)
    is_tradable  = Column(Boolean, nullable=False, default=True)
    is_restricted = Column(Boolean, nullable=False, default=False)
    restrict_reason = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())
