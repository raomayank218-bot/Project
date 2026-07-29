"""Order endpoints — FR-A-01 to FR-A-17."""
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User, UserRole
from app.models.account import Account
from app.models.order import Order, OrderSide, OrderType, TimeInForce, OrderSource, OrderState
from app.services.order_service import OrderService, OrderRequest, CommandParser

router = APIRouter()


class PlaceOrderRequest(BaseModel):
    account_id: str
    instrument_id: str = Field(..., examples=["AAPL"])
    side: OrderSide
    quantity: Decimal = Field(..., gt=0, examples=[100])
    order_type: OrderType = OrderType.MARKET
    price: Optional[Decimal] = Field(None, description="Required for LIMIT orders")
    stop_price: Optional[Decimal] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    client_order_id: Optional[str] = Field(None, description="Idempotency key")
    is_paper: bool = False


class CommandOrderRequest(BaseModel):
    account_id: str
    command: str = Field(..., examples=["BUY 100 AAPL @MKT"])
    is_paper: bool = False
    confirm: bool = Field(True, description="Set false to parse without submitting")


def _order_dict(o: Order) -> dict:
    def val(x):
        return x.value if hasattr(x, "value") else (str(x) if x is not None else None)
    return {
        "id": o.id,
        "instrument_id": o.instrument_id,
        "side": val(o.side),
        "order_type": val(o.order_type),
        "quantity": str(o.quantity),
        "price": str(o.price) if o.price is not None else None,
        "filled_quantity": str(o.filled_quantity),
        "avg_fill_price": str(o.avg_fill_price) if o.avg_fill_price is not None else None,
        "state": val(o.state),
        "time_in_force": val(o.time_in_force),
        "source": val(o.source),
        "is_paper": o.is_paper,
        "reject_reason": o.reject_reason,
        "net_consideration": str(o.net_consideration) if o.net_consideration is not None else None,
        "received_at": o.received_at.isoformat() if o.received_at else None,
    }


async def _assert_account_access(db: AsyncSession, user: User, account_id: str) -> Account:
    """FR-M-02 / FR-M-04: verify the user is entitled to trade on this account."""
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(404, "Account not found")

    internal = {UserRole.TRADER, UserRole.ADMIN, UserRole.OPERATIONS}
    if user.role in internal:
        return account
    if user.client_id and account.client_id == user.client_id:
        return account
    raise HTTPException(403, "You are not entitled to trade on this account")


@router.post("/", summary="Place an order (runs the full STP lifecycle)")
async def place_order(
    body: PlaceOrderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Runs the order through every lifecycle stage: capture, enrichment,
    validation, pre-trade risk, routing, execution, fill capture, clearing,
    position update, settlement instruction, matching and settlement.

    The `lifecycle` field in the response traces each stage.
    """
    await _assert_account_access(db, current_user, body.account_id)

    request = OrderRequest(
        account_id=body.account_id,
        instrument_id=body.instrument_id.upper(),
        side=body.side,
        quantity=body.quantity,
        order_type=body.order_type,
        price=body.price,
        stop_price=body.stop_price,
        time_in_force=body.time_in_force,
        client_order_id=body.client_order_id,
        source=OrderSource.GUI,
        is_paper=body.is_paper,
    )

    result = await OrderService(db).submit_order(request, current_user)

    return {
        "success": result.success,
        "message": result.message,
        "reason_code": result.reason_code,
        "correlation_id": result.correlation_id,
        "order": _order_dict(result.order) if result.order else None,
        "trade": {
            "id": result.trade.id,
            "quantity": str(result.trade.quantity),
            "price": str(result.trade.price),
            "gross_consideration": str(result.trade.gross_consideration),
            "commission": str(result.trade.commission),
            "exchange_fee": str(result.trade.exchange_fee),
            "tax": str(result.trade.tax),
            "net_consideration": str(result.trade.net_consideration),
            "settlement_date": result.trade.settlement_date,
            "settlement_status": str(result.trade.settlement_status),
        } if result.trade else None,
        "fills": [
            {"quantity": str(f.quantity), "price": str(f.price), "venue": f.venue}
            for f in (result.fills or [])
        ],
        "lifecycle": result.lifecycle,
    }


@router.post("/command", summary="Place an order using command syntax")
async def place_command_order(
    body: CommandOrderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    FR-A-13: single-line command entry, preserving the syntax clients already use.

    Format: BUY|SELL <qty> <TICKER> [@MKT|@<price>] [DAY|GTC|IOC|FOK]

    Set confirm=false to parse without submitting — this is how the command
    bar and natural-language interfaces show the user exactly what will be
    submitted before it goes.
    """
    request, error = CommandParser.parse(body.command)
    if error:
        raise HTTPException(400, error)

    request.account_id = body.account_id
    request.is_paper = body.is_paper

    parsed = {
        "instrument_id": request.instrument_id,
        "side": request.side.value,
        "quantity": str(request.quantity),
        "order_type": request.order_type.value,
        "price": str(request.price) if request.price else "MARKET",
        "time_in_force": request.time_in_force.value,
    }

    if not body.confirm:
        return {"parsed": parsed, "submitted": False,
                "message": "Parsed only. Resubmit with confirm=true to execute."}

    await _assert_account_access(db, current_user, body.account_id)
    result = await OrderService(db).submit_order(request, current_user)

    return {
        "parsed": parsed,
        "submitted": True,
        "success": result.success,
        "message": result.message,
        "reason_code": result.reason_code,
        "order": _order_dict(result.order) if result.order else None,
        "lifecycle": result.lifecycle,
    }


@router.get("/", summary="Order blotter")
async def list_orders(
    account_id: Optional[str] = None,
    state: Optional[OrderState] = None,
    instrument_id: Optional[str] = None,
    is_paper: bool = False,
    limit: int = Query(100, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FR-A-15: order blotter, filterable by instrument, state and account."""
    stmt = select(Order).where(Order.is_paper.is_(is_paper))

    internal = {UserRole.TRADER, UserRole.ADMIN, UserRole.OPERATIONS,
                UserRole.RISK, UserRole.COMPLIANCE, UserRole.READ_ONLY}
    if current_user.role not in internal:
        acc = await db.execute(
            select(Account.id).where(Account.client_id == current_user.client_id)
        )
        stmt = stmt.where(Order.account_id.in_(list(acc.scalars().all())))

    if account_id:
        stmt = stmt.where(Order.account_id == account_id)
    if state:
        stmt = stmt.where(Order.state == state)
    if instrument_id:
        stmt = stmt.where(Order.instrument_id == instrument_id.upper())

    result = await db.execute(stmt.order_by(desc(Order.received_at)).limit(limit))
    orders = list(result.scalars().all())
    return {"count": len(orders), "orders": [_order_dict(o) for o in orders]}


@router.get("/{order_id}", summary="Order detail")
async def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(404, "Order not found")
    return _order_dict(order)


@router.get("/{order_id}/audit", summary="Full audit trail for an order")
async def get_order_audit(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """NFR-AU-02: reconstruct an order's complete decision history from the log alone."""
    from app.models.exception import AuditLog

    result = await db.execute(
        select(AuditLog).where(AuditLog.entity_id == order_id)
        .order_by(AuditLog.occurred_at)
    )
    entries = list(result.scalars().all())
    return {
        "order_id": order_id,
        "entry_count": len(entries),
        "audit_trail": [
            {
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                "actor_type": e.actor_type,
                "actor_id": e.actor_id,
                "action": e.action,
                "before_state": e.before_state,
                "after_state": e.after_state,
                "reason_code": e.reason_code,
                "correlation_id": e.correlation_id,
            }
            for e in entries
        ],
    }


@router.post("/{order_id}/cancel", summary="Cancel a working order")
async def cancel_order(
    order_id: str,
    reason: str = "USER_CANCELLED",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FR-A-10: cancel a working order. Terminal-state orders cannot be cancelled."""
    result = await OrderService(db).cancel_order(order_id, current_user, reason)
    if not result.success:
        raise HTTPException(400, result.message)
    return {"success": True, "message": result.message, "order": _order_dict(result.order)}
