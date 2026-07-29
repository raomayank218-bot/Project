"""Exception and Audit models — FR-F-01 to FR-F-09, NFR-AU-01."""
import enum
from sqlalchemy import Column, String, DateTime, Enum as SAEnum, Text, Integer, JSON
from sqlalchemy.sql import func
from app.database import Base


class ExceptionCode(str, enum.Enum):
    EX_REF = "EX-REF"   # Reference data missing/stale
    EX_VAL = "EX-VAL"   # Validation failure
    EX_RSK = "EX-RSK"   # Risk breach
    EX_CMP = "EX-CMP"   # Compliance flag
    EX_EXE = "EX-EXE"   # Execution failure
    EX_FIL = "EX-FIL"   # Fill mismatch / orphan
    EX_ALC = "EX-ALC"   # Allocation failure
    EX_SET = "EX-SET"   # Settlement failure
    EX_REC = "EX-REC"   # Reconciliation break
    EX_SYS = "EX-SYS"   # System error
    EX_AI  = "EX-AI"    # GenAI service error


class ExceptionSeverity(str, enum.Enum):
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


class ExceptionStatus(str, enum.Enum):
    OPEN       = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED   = "RESOLVED"
    CLOSED     = "CLOSED"


class TradingException(Base):
    """Every failed automated step lands here — FR-F-01."""
    __tablename__ = "trading_exceptions"

    id              = Column(String(36), primary_key=True)
    code            = Column(SAEnum(ExceptionCode), nullable=False, index=True)
    severity        = Column(SAEnum(ExceptionSeverity), nullable=False)
    status          = Column(SAEnum(ExceptionStatus), nullable=False,
                             default=ExceptionStatus.OPEN, index=True)

    # What this exception is about
    entity_type     = Column(String(50), nullable=True)   # ORDER, TRADE, FILL, etc.
    entity_id       = Column(String(36), nullable=True, index=True)
    account_id      = Column(String(36), nullable=True)
    instrument_id   = Column(String(20), nullable=True)

    description     = Column(Text, nullable=False)
    detail          = Column(JSON, nullable=True)           # raw context for triage

    # SLA tracking — FR-F-03
    sla_hours       = Column(Integer, nullable=False, default=24)
    sla_due_at      = Column(DateTime(timezone=True), nullable=True)

    # Resolution
    owner_user_id   = Column(String(36), nullable=True)
    resolution_action = Column(Text, nullable=True)
    resolution_reason = Column(Text, nullable=True)
    resolved_by     = Column(String(36), nullable=True)
    resolved_at     = Column(DateTime(timezone=True), nullable=True)

    raised_at       = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())


class AuditLog(Base):
    """
    Immutable, append-only audit trail — NFR-AU-01.
    No UPDATE or DELETE is ever issued against this table.
    The application enforces this; the DB role should also deny UPDATE/DELETE.
    """
    __tablename__ = "audit_log"

    id              = Column(String(36), primary_key=True)
    sequence_num    = Column(Integer, nullable=False, autoincrement=True, unique=True)
    correlation_id  = Column(String(36), nullable=True, index=True)

    # Actor
    actor_type      = Column(String(20), nullable=False)   # USER, SERVICE, SYSTEM
    actor_id        = Column(String(100), nullable=False)
    source_ip       = Column(String(45), nullable=True)

    # What happened
    action          = Column(String(100), nullable=False, index=True)
    entity_type     = Column(String(50), nullable=True)
    entity_id       = Column(String(36), nullable=True, index=True)
    before_state    = Column(JSON, nullable=True)
    after_state     = Column(JSON, nullable=True)
    reason_code     = Column(String(50), nullable=True)
    detail          = Column(JSON, nullable=True)

    occurred_at     = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
