"""
Unit tests for the order state machine.
FR-A-05: illegal transitions are rejected and audited.
NFR-M-02: mandatory coverage on state machine logic.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.state_machine import OrderStateMachine, StateMachineError, TRANSITIONS, TERMINAL_STATES
from app.models.order import OrderState


def make_order(state: OrderState):
    order = MagicMock()
    order.id = "test-order-001"
    order.state = state.value
    return order


def make_db():
    db = AsyncMock()
    db.add = MagicMock()
    return db


class TestLegalTransitions:
    """Every legal forward transition must succeed."""

    @pytest.mark.asyncio
    async def test_received_to_validated(self):
        order = make_order(OrderState.RECEIVED)
        sm = OrderStateMachine(order, make_db(), "corr-001")
        await sm.transition(OrderState.VALIDATED, actor_id="svc:validator")
        assert order.state == OrderState.VALIDATED

    @pytest.mark.asyncio
    async def test_validated_to_risk_approved(self):
        order = make_order(OrderState.VALIDATED)
        sm = OrderStateMachine(order, make_db())
        await sm.transition(OrderState.RISK_APPROVED, actor_id="svc:risk")
        assert order.state == OrderState.RISK_APPROVED

    @pytest.mark.asyncio
    async def test_risk_approved_to_working(self):
        order = make_order(OrderState.RISK_APPROVED)
        sm = OrderStateMachine(order, make_db())
        await sm.transition(OrderState.WORKING, actor_id="svc:matching")
        assert order.state == OrderState.WORKING

    @pytest.mark.asyncio
    async def test_working_to_partially_filled(self):
        order = make_order(OrderState.WORKING)
        sm = OrderStateMachine(order, make_db())
        await sm.transition(OrderState.PARTIALLY_FILLED, actor_id="svc:matching")
        assert order.state == OrderState.PARTIALLY_FILLED

    @pytest.mark.asyncio
    async def test_partially_filled_to_filled(self):
        order = make_order(OrderState.PARTIALLY_FILLED)
        sm = OrderStateMachine(order, make_db())
        await sm.transition(OrderState.FILLED, actor_id="svc:matching")
        assert order.state == OrderState.FILLED

    @pytest.mark.asyncio
    async def test_filled_to_cleared(self):
        order = make_order(OrderState.FILLED)
        sm = OrderStateMachine(order, make_db())
        await sm.transition(OrderState.CLEARED, actor_id="svc:clearing")
        assert order.state == OrderState.CLEARED

    @pytest.mark.asyncio
    async def test_cleared_to_settlement_instructed(self):
        order = make_order(OrderState.CLEARED)
        sm = OrderStateMachine(order, make_db())
        await sm.transition(OrderState.SETTLEMENT_INSTRUCTED, actor_id="svc:settlement")
        assert order.state == OrderState.SETTLEMENT_INSTRUCTED

    @pytest.mark.asyncio
    async def test_settlement_instructed_to_matched(self):
        order = make_order(OrderState.SETTLEMENT_INSTRUCTED)
        sm = OrderStateMachine(order, make_db())
        await sm.transition(OrderState.MATCHED, actor_id="svc:settlement")
        assert order.state == OrderState.MATCHED

    @pytest.mark.asyncio
    async def test_matched_to_settled(self):
        order = make_order(OrderState.MATCHED)
        sm = OrderStateMachine(order, make_db())
        await sm.transition(OrderState.SETTLED, actor_id="svc:settlement")
        assert order.state == OrderState.SETTLED

    @pytest.mark.asyncio
    async def test_working_to_cancelled(self):
        order = make_order(OrderState.WORKING)
        sm = OrderStateMachine(order, make_db())
        await sm.transition(OrderState.CANCELLED, actor_id="user-123",
                            reason_code="USER_CANCELLED")
        assert order.state == OrderState.CANCELLED
        assert order.cancel_reason == "USER_CANCELLED"

    @pytest.mark.asyncio
    async def test_received_to_rejected(self):
        order = make_order(OrderState.RECEIVED)
        sm = OrderStateMachine(order, make_db())
        await sm.transition(OrderState.REJECTED, actor_id="svc:validator",
                            reason_code="INVALID_INSTRUMENT")
        assert order.state == OrderState.REJECTED
        assert order.reject_reason == "INVALID_INSTRUMENT"

    @pytest.mark.asyncio
    async def test_working_to_expired(self):
        order = make_order(OrderState.WORKING)
        sm = OrderStateMachine(order, make_db())
        await sm.transition(OrderState.EXPIRED, actor_id="svc:tif_monitor")
        assert order.state == OrderState.EXPIRED

    @pytest.mark.asyncio
    async def test_matched_to_settlement_failed(self):
        order = make_order(OrderState.MATCHED)
        sm = OrderStateMachine(order, make_db())
        await sm.transition(OrderState.SETTLEMENT_FAILED, actor_id="svc:settlement")
        assert order.state == OrderState.SETTLEMENT_FAILED


class TestIllegalTransitions:
    """Illegal transitions must raise StateMachineError and be audited."""

    @pytest.mark.asyncio
    async def test_cannot_skip_validation(self):
        order = make_order(OrderState.RECEIVED)
        sm = OrderStateMachine(order, make_db())
        with pytest.raises(StateMachineError):
            await sm.transition(OrderState.WORKING, actor_id="svc:matching")

    @pytest.mark.asyncio
    async def test_cannot_transition_from_terminal_settled(self):
        order = make_order(OrderState.SETTLED)
        sm = OrderStateMachine(order, make_db())
        with pytest.raises(StateMachineError):
            await sm.transition(OrderState.WORKING, actor_id="user")

    @pytest.mark.asyncio
    async def test_cannot_transition_from_terminal_rejected(self):
        order = make_order(OrderState.REJECTED)
        sm = OrderStateMachine(order, make_db())
        with pytest.raises(StateMachineError):
            await sm.transition(OrderState.VALIDATED, actor_id="user")

    @pytest.mark.asyncio
    async def test_cannot_transition_from_terminal_cancelled(self):
        order = make_order(OrderState.CANCELLED)
        sm = OrderStateMachine(order, make_db())
        with pytest.raises(StateMachineError):
            await sm.transition(OrderState.WORKING, actor_id="user")

    @pytest.mark.asyncio
    async def test_cannot_go_backwards_filled_to_received(self):
        order = make_order(OrderState.FILLED)
        sm = OrderStateMachine(order, make_db())
        with pytest.raises(StateMachineError):
            await sm.transition(OrderState.RECEIVED, actor_id="user")

    @pytest.mark.asyncio
    async def test_cannot_go_settled_to_working(self):
        order = make_order(OrderState.SETTLED)
        sm = OrderStateMachine(order, make_db())
        with pytest.raises(StateMachineError):
            await sm.transition(OrderState.WORKING, actor_id="user")

    @pytest.mark.asyncio
    async def test_illegal_transition_audited(self):
        """An illegal transition must still write an audit entry."""
        order = make_order(OrderState.RECEIVED)
        db = make_db()
        sm = OrderStateMachine(order, db)
        try:
            await sm.transition(OrderState.SETTLED, actor_id="user")
        except StateMachineError:
            pass
        # db.add must have been called for the audit entry
        db.add.assert_called()


class TestTerminalStates:
    """All terminal states have no valid exits."""

    def test_all_terminal_states_have_empty_transitions(self):
        for state in TERMINAL_STATES:
            exits = TRANSITIONS.get(state, set())
            assert exits == set(), f"Terminal state {state} should have no exits, found: {exits}"


class TestTransitionTableCompleteness:
    """Every defined state has an entry in the transition table."""

    def test_all_states_in_transition_table(self):
        for state in OrderState:
            assert state in TRANSITIONS, f"State {state} missing from TRANSITIONS table"

    def test_all_transition_targets_are_valid_states(self):
        valid = set(OrderState)
        for from_state, to_states in TRANSITIONS.items():
            for to_state in to_states:
                assert to_state in valid, f"Transition target {to_state} is not a valid OrderState"


class TestAuditBeforeState:
    """Audit entry is always written before state is mutated."""

    @pytest.mark.asyncio
    async def test_audit_written_before_state_change(self):
        """
        Audit entry (AuditLog object) is added to the session BEFORE the order
        state is mutated. We verify ordering by tracking what db.add receives.
        db.add is synchronous in SQLAlchemy — MagicMock (not AsyncMock).
        """
        from app.models.exception import AuditLog

        order = make_order(OrderState.RECEIVED)
        db = MagicMock()   # synchronous mock — db.add is not awaited

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(type(obj).__name__)

        sm = OrderStateMachine(order, db)
        await sm.transition(OrderState.VALIDATED, actor_id="svc:validator")

        # First call to db.add should be the AuditLog, second the order (MagicMock)
        assert len(added_objects) == 2, f"Expected 2 db.add calls, got {len(added_objects)}"
        assert added_objects[0] == "AuditLog", (
            f"Expected AuditLog to be added first, got {added_objects[0]}"
        )
        # The order is our MagicMock — confirm it was added after the audit entry
        assert added_objects[1] == "MagicMock", (
            f"Expected order (MagicMock) to be added second, got {added_objects[1]}"
        )
