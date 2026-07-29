"""
Order state machine — spec Section 4.
FR-A-05: every transition is enforced; undefined transitions are rejected and audited.
Rule: write the audit entry BEFORE committing the state change.
"""
from datetime import datetime, timezone
from typing import Optional
import uuid

from app.models.order import OrderState


# ── Transition table ──────────────────────────────────────────────────────────
# Maps (from_state, to_state) -> list of allowed transitions.
# Any pair not in this table is ILLEGAL.

TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.RECEIVED: {
        OrderState.VALIDATED,
        OrderState.REJECTED,
    },
    OrderState.VALIDATED: {
        OrderState.RISK_APPROVED,
        OrderState.REJECTED,
        OrderState.SUSPENDED,
    },
    OrderState.RISK_APPROVED: {
        OrderState.WORKING,
        OrderState.REJECTED,
    },
    OrderState.WORKING: {
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
        OrderState.AMENDED,
        OrderState.SUSPENDED,
    },
    OrderState.PARTIALLY_FILLED: {
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
    },
    OrderState.FILLED: {
        OrderState.CLEARED,
    },
    OrderState.AMENDED: {
        OrderState.WORKING,   # new version enters WORKING
    },
    OrderState.CLEARED: {
        OrderState.SETTLEMENT_INSTRUCTED,
        OrderState.EXCEPTION,
    },
    OrderState.SETTLEMENT_INSTRUCTED: {
        OrderState.MATCHED,
        OrderState.EXCEPTION,
    },
    OrderState.MATCHED: {
        OrderState.SETTLED,
        OrderState.SETTLEMENT_FAILED,
    },
    OrderState.SUSPENDED: {
        OrderState.WORKING,
        OrderState.CANCELLED,
    },
    OrderState.EXCEPTION: {
        # Re-enters previous stage on resolution, or closed
        OrderState.CLEARED,
        OrderState.SETTLEMENT_INSTRUCTED,
        OrderState.CANCELLED,
    },
    OrderState.SETTLEMENT_FAILED: {
        OrderState.SETTLED,   # on resolution
        OrderState.EXCEPTION,
    },
    # Terminal states — no exits
    OrderState.SETTLED:   set(),
    OrderState.REJECTED:  set(),
    OrderState.CANCELLED: set(),
    OrderState.EXPIRED:   set(),
}

TERMINAL_STATES = {
    OrderState.SETTLED,
    OrderState.REJECTED,
    OrderState.CANCELLED,
    OrderState.EXPIRED,
}


class StateMachineError(Exception):
    """Raised when an illegal state transition is attempted."""
    pass


class OrderStateMachine:
    """
    Validates and executes order state transitions.

    Usage:
        sm = OrderStateMachine(order, db_session, correlation_id)
        await sm.transition(OrderState.VALIDATED, actor_id="svc:validator")
    """

    def __init__(self, order, db, correlation_id: Optional[str] = None):
        self.order = order
        self.db = db
        self.correlation_id = correlation_id or str(uuid.uuid4())

    def can_transition(self, to_state: OrderState) -> bool:
        from_state = OrderState(self.order.state)
        return to_state in TRANSITIONS.get(from_state, set())

    async def transition(
        self,
        to_state: OrderState,
        actor_id: str,
        reason_code: Optional[str] = None,
        detail: Optional[dict] = None,
    ) -> None:
        """
        Validate and execute a state transition.
        Audit entry is written BEFORE the state change is committed — NFR-AU-01.
        If the audit write fails, the transition does not happen.
        """
        from_state = OrderState(self.order.state)

        # Reject undefined transitions
        if not self.can_transition(to_state):
            # Audit the illegal attempt
            self._write_audit(
                from_state=from_state,
                to_state=to_state,
                actor_id=actor_id,
                action="ORDER_STATE_TRANSITION_ILLEGAL",
                reason_code="ILLEGAL_TRANSITION",
                detail={"attempted": to_state, "current": from_state},
            )
            raise StateMachineError(
                f"Illegal transition: {from_state} → {to_state} for order {self.order.id}"
            )

        # Write audit BEFORE mutating state — NFR-AU-01
        self._write_audit(
            from_state=from_state,
            to_state=to_state,
            actor_id=actor_id,
            action="ORDER_STATE_TRANSITION",
            reason_code=reason_code,
            detail=detail,
        )

        # Now mutate the order
        self.order.state = to_state
        now = datetime.now(timezone.utc)

        # Update relevant timestamp field
        ts_map = {
            OrderState.VALIDATED:             "validated_at",
            OrderState.RISK_APPROVED:         "risk_approved_at",
            OrderState.WORKING:               "working_at",
            OrderState.FILLED:                "filled_at",
            OrderState.SETTLED:               "settled_at",
        }
        if to_state in ts_map:
            setattr(self.order, ts_map[to_state], now)

        # Propagate reject/cancel reasons
        if to_state == OrderState.REJECTED and reason_code:
            self.order.reject_reason = reason_code
        if to_state == OrderState.CANCELLED and reason_code:
            self.order.cancel_reason = reason_code

        self.db.add(self.order)

    def _write_audit(
        self,
        from_state: OrderState,
        to_state: OrderState,
        actor_id: str,
        action: str,
        reason_code: Optional[str] = None,
        detail: Optional[dict] = None,
    ):
        from app.models.exception import AuditLog

        entry = AuditLog(
            id=str(uuid.uuid4()),
            correlation_id=self.correlation_id,
            actor_type="SERVICE" if actor_id.startswith("svc:") else "USER",
            actor_id=actor_id,
            action=action,
            entity_type="ORDER",
            entity_id=self.order.id,
            before_state={"state": from_state.value},
            after_state={"state": to_state.value},
            reason_code=reason_code,
            detail=detail,
        )
        self.db.add(entry)
