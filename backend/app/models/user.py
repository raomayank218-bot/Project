"""User model — FR-M-01, FR-M-02."""
import enum
from sqlalchemy import Column, String, Boolean, DateTime, Enum as SAEnum
from sqlalchemy.sql import func
from app.database import Base


class UserRole(str, enum.Enum):
    CLIENT           = "CLIENT"
    AUTHORISED_REP   = "AUTHORISED_REP"
    TRADER           = "TRADER"
    OPERATIONS       = "OPERATIONS"
    RISK             = "RISK"
    COMPLIANCE       = "COMPLIANCE"
    ADMIN            = "ADMIN"
    READ_ONLY        = "READ_ONLY"


class UserStatus(str, enum.Enum):
    ACTIVE    = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LOCKED    = "LOCKED"


class User(Base):
    __tablename__ = "users"

    id              = Column(String(36), primary_key=True)
    username        = Column(String(100), unique=True, nullable=False)
    email           = Column(String(200), unique=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    full_name       = Column(String(200), nullable=False)
    role            = Column(SAEnum(UserRole), nullable=False)
    status          = Column(SAEnum(UserStatus), nullable=False, default=UserStatus.ACTIVE)
    mfa_enabled     = Column(Boolean, nullable=False, default=False)
    # Which client account this user belongs to (null for internal staff)
    client_id       = Column(String(36), nullable=True)
    failed_logins   = Column(String(5), nullable=False, default="0")
    last_login      = Column(DateTime(timezone=True), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())
