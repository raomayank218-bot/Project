"""
STP Trading Platform — FastAPI entry point.
FR-A-01: accepts orders via REST and WebSocket.
"""
import logging
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine, Base
from app.api.v1 import router as api_router

settings = get_settings()

logging.basicConfig(level=getattr(logging, settings.log_level))
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("STP Trading Platform starting", environment=settings.environment)
    yield
    log.info("STP Trading Platform shutting down")
    await engine.dispose()


app = FastAPI(
    title="STP Trading Platform",
    description="Straight-Through Processing trading platform — Nomura Tech Graduate Program 2026",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# All API routes under /api/v1
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
async def health():
    """Health check — used by Docker Compose and the operations dashboard."""
    return {"status": "ok", "service": "stp-backend", "version": "1.0.0"}
