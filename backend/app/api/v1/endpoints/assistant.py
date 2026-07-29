"""Assistant endpoints — FR-K-01 to FR-K-14."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User, UserRole
from app.models.account import Account
from app.services.genai.assistant import Assistant
from app.services.genai.client import build_client

router = APIRouter()


class ParseRequest(BaseModel):
    text: str = Field(..., examples=["buy me a hundred apple shares at market"])


class AskRequest(BaseModel):
    account_id: str
    question: str = Field(..., examples=["what were my biggest losers?"])
    is_paper: bool = False


async def _account(db: AsyncSession, user: User, account_id: str) -> Account:
    r = await db.execute(select(Account).where(Account.id == account_id))
    a = r.scalar_one_or_none()
    if a is None:
        raise HTTPException(404, "Account not found")
    internal = {UserRole.TRADER, UserRole.ADMIN, UserRole.OPERATIONS,
                UserRole.RISK, UserRole.COMPLIANCE, UserRole.READ_ONLY}
    if user.role in internal or (user.client_id and a.client_id == user.client_id):
        return a
    raise HTTPException(403, "You are not entitled to view this account")


@router.get("/status", summary="Which model is connected")
async def status(current_user: User = Depends(get_current_user)):
    """
    FR-K-10: shows whether a model is connected. When it is not, every
    feature below still works using deterministic fallbacks.
    """
    return build_client().status()


@router.post("/parse-order", summary="Read a plain-English order")
async def parse_order(
    body: ParseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    FR-K-01: turns plain English into a structured order.

    FR-K-02: the order is returned for confirmation and is NOT submitted.
    There is no path from this endpoint to execution. To trade, the caller
    sends the confirmed order through POST /orders/ like any other.
    """
    return await Assistant(db).parse_order(body.text, current_user.id)


@router.post("/ask", summary="Ask about your account")
async def ask(
    body: AskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FR-K-03: answers from figures the platform already computed."""
    account = await _account(db, current_user, body.account_id)
    return await Assistant(db).ask(
        body.question, account, current_user.id, body.is_paper
    )


@router.get("/commentary/{account_id}", summary="Performance note")
async def commentary(
    account_id: str,
    is_paper: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FR-K-05: plain-language note on what drove performance."""
    account = await _account(db, current_user, account_id)
    return await Assistant(db).commentary(account, current_user.id, is_paper)


@router.get("/triage/{exception_id}", summary="Triage a break")
async def triage(
    exception_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    FR-K-08: suggests a probable cause and checks to make.
    Advisory only — the analyst confirms and records any action taken.
    """
    ops = {UserRole.OPERATIONS, UserRole.ADMIN, UserRole.RISK, UserRole.COMPLIANCE}
    if current_user.role not in ops:
        raise HTTPException(403, "Your role is not permitted to triage exceptions")
    return await Assistant(db).triage(exception_id, current_user.id)


@router.get("/interactions", summary="AI interaction log")
async def interactions(
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    FR-K-09: every prompt, response, model and provenance, queryable.
    This is the evidence Compliance asks for.
    """
    compliance = {UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.RISK}
    if current_user.role not in compliance:
        raise HTTPException(403, "Your role is not permitted to view the interaction log")

    from app.models.exception import AuditLog
    from sqlalchemy import desc

    r = await db.execute(
        select(AuditLog)
        .where(AuditLog.action == "GENAI_INTERACTION")
        .order_by(desc(AuditLog.occurred_at)).limit(limit)
    )
    rows = list(r.scalars().all())
    return {
        "count": len(rows),
        "interactions": [
            {
                "at": e.occurred_at.isoformat() if e.occurred_at else None,
                "user_id": e.actor_id,
                "feature": (e.detail or {}).get("feature"),
                "prompt": (e.detail or {}).get("prompt"),
                "response": (e.detail or {}).get("response"),
                "provider": (e.detail or {}).get("provider"),
                "model": (e.detail or {}).get("model"),
                "degraded": (e.detail or {}).get("degraded"),
                "latency_ms": (e.detail or {}).get("latency_ms"),
                "guardrail": e.reason_code,
            }
            for e in rows
        ],
    }
