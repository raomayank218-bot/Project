"""Instrument and market data endpoints — FR-L-01 to FR-L-09."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User
from app.models.instrument import Instrument
from app.models.market import Price, MarketCalendar, SentimentScore
from app.services.market_data import MarketDataService
from app.services.matching_engine import MatchingEngine
from decimal import Decimal

router = APIRouter()


@router.get("/", summary="Instrument master")
async def list_instruments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Instrument).order_by(Instrument.id))
    instruments = list(result.scalars().all())
    market = MarketDataService(db)

    out = []
    for i in instruments:
        last = await market.get_last_price(i.id)
        out.append({
            "id": i.id, "isin": i.isin, "name": i.name,
            "asset_class": i.asset_class, "currency": i.currency,
            "exchange": i.exchange, "sector": i.sector, "geography": i.geography,
            "lot_size": str(i.lot_size), "tick_size": str(i.tick_size),
            "is_tradable": i.is_tradable, "is_restricted": i.is_restricted,
            "last_price": str(last) if last else None,
        })
    return {"count": len(out), "instruments": out}


@router.get("/calendar", summary="Market calendar (derived from data)")
async def get_calendar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    FR-E-02: the calendar is derived from actual data dates, not weekday rules.
    The simulation dataset contains Saturdays and no Mondays.
    """
    result = await db.execute(
        select(MarketCalendar).order_by(MarketCalendar.trading_date)
    )
    days = list(result.scalars().all())
    return {
        "trading_day_count": len(days),
        "first": days[0].trading_date if days else None,
        "last": days[-1].trading_date if days else None,
        "note": "Calendar derived from simulation data dates, not standard business-day rules.",
        "dates": [d.trading_date for d in days],
    }


@router.get("/{instrument_id}", summary="Instrument detail")
async def get_instrument(
    instrument_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Instrument).where(Instrument.id == instrument_id.upper())
    )
    i = result.scalar_one_or_none()
    if i is None:
        raise HTTPException(404, f"Instrument '{instrument_id}' not found")

    market = MarketDataService(db)
    last = await market.get_last_price(i.id)
    adv = await market.get_avg_daily_volume(i.id)

    return {
        "id": i.id, "isin": i.isin, "name": i.name,
        "asset_class": i.asset_class, "currency": i.currency,
        "exchange": i.exchange, "sector": i.sector, "geography": i.geography,
        "lot_size": str(i.lot_size), "tick_size": str(i.tick_size),
        "is_tradable": i.is_tradable, "is_restricted": i.is_restricted,
        "last_price": str(last) if last else None,
        "avg_daily_volume": str(round(adv)) if adv else None,
    }


@router.get("/{instrument_id}/prices", summary="Price history (OHLCV)")
async def get_prices(
    instrument_id: str,
    interval: str = Query("1min", pattern="^(1min|daily)$"),
    limit: int = Query(200, le=2000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FR-H-07: candlestick chart data."""
    result = await db.execute(
        select(Price)
        .where(Price.instrument_id == instrument_id.upper())
        .where(Price.interval_type == interval)
        .order_by(desc(Price.timestamp)).limit(limit)
    )
    bars = list(result.scalars().all())
    bars.reverse()

    return {
        "instrument_id": instrument_id.upper(),
        "interval": interval,
        "count": len(bars),
        "bars": [
            {
                "timestamp": b.timestamp.isoformat(),
                "open": str(b.open), "high": str(b.high),
                "low": str(b.low), "close": str(b.close),
                "volume": str(b.volume),
            }
            for b in bars
        ],
    }


@router.get("/{instrument_id}/book", summary="Synthetic order book depth")
async def get_order_book(
    instrument_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    FR-D-11: live order book depth.
    The dataset has no depth data, so the book is synthesised from OHLCV.
    """
    market = MarketDataService(db)
    last = await market.get_last_price(instrument_id.upper())
    if last is None:
        raise HTTPException(404, f"No price data for '{instrument_id}'")

    bars = await market.get_recent_bars(instrument_id.upper(), limit=1)
    bar = bars[0] if bars else None

    book = MatchingEngine().build_book(
        instrument_id=instrument_id.upper(),
        reference_price=last,
        bar_high=Decimal(str(bar.high)) if bar else None,
        bar_low=Decimal(str(bar.low)) if bar else None,
        bar_volume=Decimal(str(bar.volume)) if bar else None,
    )

    return {
        "instrument_id": book.instrument_id,
        "reference_price": str(book.reference_price),
        "best_bid": str(book.best_bid) if book.best_bid else None,
        "best_ask": str(book.best_ask) if book.best_ask else None,
        "spread": str(book.spread) if book.spread else None,
        "bids": [{"price": str(l.price), "quantity": str(l.quantity)} for l in book.bids],
        "asks": [{"price": str(l.price), "quantity": str(l.quantity)} for l in book.asks],
        "note": "Synthetic book generated from OHLCV — dataset has no depth data.",
    }


@router.get("/{instrument_id}/sentiment", summary="News sentiment scores")
async def get_sentiment(
    instrument_id: str,
    limit: int = Query(60, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    FR-K-04: sentiment from the news dataset.
    Scores are pre-computed per article; we aggregate relevance-weighted per day.
    Coverage is thin for IBM and UL — the response flags this.
    """
    result = await db.execute(
        select(SentimentScore)
        .where(SentimentScore.instrument_id == instrument_id.upper())
        .order_by(desc(SentimentScore.score_date)).limit(limit)
    )
    scores = list(result.scalars().all())
    scores.reverse()

    total_articles = sum(s.article_count for s in scores)
    coverage_note = None
    if total_articles < 200:
        coverage_note = (
            f"Thin coverage: only {total_articles} article mentions across "
            f"{len(scores)} days. Treat this signal as indicative only."
        )

    return {
        "instrument_id": instrument_id.upper(),
        "day_count": len(scores),
        "total_article_mentions": total_articles,
        "coverage_warning": coverage_note,
        "disclaimer": "Sentiment is indicative only and is not investment advice.",
        "scores": [
            {
                "date": s.score_date,
                "avg_score": str(s.avg_score),
                "article_count": s.article_count,
                "label": s.label,
            }
            for s in scores
        ],
    }
