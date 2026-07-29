from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth, orders, trades, portfolio,
    instruments, risk, exceptions,
    assistant, paper, reports, health, websocket
)

router = APIRouter()

router.include_router(auth.router,        prefix="/auth",        tags=["auth"])
router.include_router(orders.router,      prefix="/orders",      tags=["orders"])
router.include_router(trades.router,      prefix="/trades",      tags=["trades"])
router.include_router(portfolio.router,   prefix="/portfolio",   tags=["portfolio"])
router.include_router(instruments.router, prefix="/instruments", tags=["instruments"])
router.include_router(risk.router,        prefix="/risk",        tags=["risk"])
router.include_router(exceptions.router,  prefix="/exceptions",  tags=["exceptions"])
router.include_router(assistant.router,  prefix="/assistant",  tags=["assistant"])
router.include_router(paper.router,       prefix="/paper",       tags=["paper"])
router.include_router(reports.router,     prefix="/reports",     tags=["reports"])
router.include_router(health.router,      prefix="/system",      tags=["system"])
router.include_router(websocket.router,   prefix="/ws",          tags=["websocket"])
