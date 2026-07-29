"""
Ingests the simulation dataset into Postgres.

Loads:
  - 7 daily historical CSVs   → prices (interval_type='daily')
  - 7 intraday 1-min CSVs     → prices (interval_type='1min')
  - 2 news JSON files         → sentiment_scores (pre-aggregated per ticker/day)
  - Derives market_calendar   from the distinct dates in the intraday data

Data quality notes (from profiling):
  - IBM and UL have missing 1-min bars — quarantined, not silently skipped
  - Historical and live datasets overlap on ~5 dates with small divergence:
    use daily for dates < 2026-06-30, intraday for >= 2026-06-30
  - WMT has a 3-for-1 split on 2026-02-26 (split_coefficient=3)
  - 11 dividend events across 6 instruments
  - No real ETFs in the dataset — instruments are all US large-cap equities

Run with:  python -m app.scripts.ingest_data
"""
import os
import sys
import uuid
import json
import glob
import logging
from datetime import datetime, timezone, date
from decimal import Decimal

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest")


def get_conn():
    from app.config import get_settings
    s = get_settings()
    return psycopg2.connect(s.database_url_sync)


# ── Ticker → metadata mapping ────────────────────────────────────────────────
INSTRUMENT_META = {
    "AAPL": {"name": "Apple Inc.", "sector": "Technology", "isin": "US0378331005"},
    "GOOG": {"name": "Alphabet Inc.", "sector": "Technology", "isin": "US02079K3059"},
    "IBM":  {"name": "IBM Corp.", "sector": "Technology", "isin": "US4592001014"},
    "MSFT": {"name": "Microsoft Corp.", "sector": "Technology", "isin": "US5949181045"},
    "TSLA": {"name": "Tesla Inc.", "sector": "Consumer Discretionary", "isin": "US88160R1014"},
    "UL":   {"name": "Unilever PLC", "sector": "Consumer Staples", "isin": "GB00B10RZP78"},
    "WMT":  {"name": "Walmart Inc.", "sector": "Consumer Staples", "isin": "US9311421039"},
}


def ingest_prices(conn) -> dict:
    """Load all price CSVs. Returns quarantine summary."""
    cur = conn.cursor()
    quarantine = {}

    data_dir = os.environ.get("DATA_DIR", "/app/data")
    hist_dir = os.path.join(data_dir, "simulation_historical_data")
    live_dir = os.path.join(data_dir, "simulation_price_data_July_1-Aug_30")

    # Check if already loaded
    cur.execute("SELECT COUNT(*) FROM prices")
    if cur.fetchone()[0] > 0:
        log.info("Prices already loaded — skipping")
        return {}

    rows_daily = []
    rows_intraday = []
    all_trading_dates = set()

    # ── Daily historical ──────────────────────────────────────────────────
    log.info("Loading daily historical data...")
    for fpath in sorted(glob.glob(os.path.join(hist_dir, "*.csv"))):
        fname = os.path.basename(fpath)
        ticker = fname.replace("_2026_historical.csv", "").replace("simulated_", "").upper()

        df = pd.read_csv(fpath, parse_dates=["timestamp"])
        nulls = df.isna().sum().sum()
        if nulls > 0:
            log.warning(f"{ticker} daily: {nulls} nulls — quarantining affected rows")
            quarantine[f"{ticker}_daily"] = f"{nulls} nulls"
            df = df.dropna(subset=["open", "high", "low", "close", "volume"])

        # Use daily for dates BEFORE the intraday window starts (< 2026-06-30)
        df_pre = df[df["timestamp"] < pd.Timestamp("2026-06-30")]

        for _, row in df_pre.iterrows():
            rows_daily.append((
                str(uuid.uuid4()), ticker,
                row["timestamp"].replace(tzinfo=timezone.utc).isoformat(),
                "daily",
                float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]),
                int(row["volume"]),
                float(row.get("adjusted_close", row["close"])) if pd.notna(row.get("adjusted_close")) else None,
                float(row["dividend_amount"]) if pd.notna(row.get("dividend_amount")) else None,
                float(row["split_coefficient"]) if pd.notna(row.get("split_coefficient")) else None,
                "simulation_daily"
            ))

        log.info(f"  {ticker}: {len(df_pre)} daily bars loaded")

    # ── Intraday 1-minute ─────────────────────────────────────────────────
    log.info("Loading intraday 1-minute data...")
    expected_bars_per_day = 390  # 09:30 to 15:59

    for fpath in sorted(glob.glob(os.path.join(live_dir, "*.csv"))):
        fname = os.path.basename(fpath)
        ticker = fname.replace("simulated_", "").replace("_live.csv", "").upper()

        df = pd.read_csv(fpath, parse_dates=["timestamp"])
        nulls = df.isna().sum().sum()
        vol_zeros = int((df["volume"] <= 0).sum())

        # Collect trading dates from AAPL (cleanest dataset)
        if ticker == "AAPL":
            all_trading_dates.update(df["timestamp"].dt.date.unique())

        # Check for short days (missing bars) — log as quarantine entries
        byday = df.groupby(df["timestamp"].dt.date).size()
        short_days = byday[byday < expected_bars_per_day]
        if len(short_days) > 0:
            quarantine[f"{ticker}_intraday"] = (
                f"{len(short_days)} short days, "
                f"{expected_bars_per_day * len(byday) - len(df)} missing bars"
            )
            log.warning(
                f"{ticker} intraday: {len(short_days)} short days "
                f"({expected_bars_per_day * len(byday) - len(df)} missing bars) — logged"
            )

        if nulls > 0 or vol_zeros > 0:
            log.warning(f"{ticker} intraday: {nulls} nulls, {vol_zeros} zero-volume rows")

        for _, row in df.iterrows():
            rows_intraday.append((
                str(uuid.uuid4()), ticker,
                row["timestamp"].replace(tzinfo=timezone.utc).isoformat(),
                "1min",
                float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]),
                int(row["volume"]),
                None, None, None,   # no adjusted_close / dividend / split on intraday
                "simulation_live"
            ))

        log.info(f"  {ticker}: {len(df)} 1-min bars loaded")

    # Bulk insert
    insert_sql = """
        INSERT INTO prices
          (id, instrument_id, timestamp, interval_type, open, high, low, close,
           volume, adjusted_close, dividend_amount, split_coefficient, source)
        VALUES %s
        ON CONFLICT DO NOTHING
    """
    log.info(f"Inserting {len(rows_daily)} daily rows...")
    execute_values(cur, insert_sql, rows_daily, page_size=1000)

    log.info(f"Inserting {len(rows_intraday)} intraday rows...")
    execute_values(cur, insert_sql, rows_intraday, page_size=1000)

    conn.commit()
    log.info(f"Price ingestion complete. Daily: {len(rows_daily)}, Intraday: {len(rows_intraday)}")
    return {"quarantine": quarantine, "trading_dates": sorted(all_trading_dates)}


def build_market_calendar(conn, trading_dates: list):
    """
    Derive market calendar from actual data dates — NOT from weekday rules.
    The simulation dataset contains Saturdays and no Mondays, so we cannot
    use standard business-day logic. FR-E-02 compliance: derive from data.
    """
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM market_calendar")
    if cur.fetchone()[0] > 0:
        log.info("Market calendar already built — skipping")
        return

    if not trading_dates:
        # Pull from DB if not passed in
        cur.execute("SELECT DISTINCT DATE(timestamp) FROM prices WHERE interval_type='1min' ORDER BY 1")
        trading_dates = [r[0] for r in cur.fetchall()]

    rows = [(str(d), True, "09:30", "15:59", None) for d in sorted(trading_dates)]
    execute_values(
        cur,
        "INSERT INTO market_calendar (trading_date, is_trading_day, session_open, session_close, notes) VALUES %s ON CONFLICT DO NOTHING",
        rows
    )
    conn.commit()
    log.info(f"Market calendar built: {len(rows)} trading days ({rows[0][0]} to {rows[-1][0]})")


def ingest_sentiment(conn):
    """
    Aggregate news sentiment scores per instrument per day.
    The JSON already contains pre-computed ticker_sentiment_score values.
    We aggregate to a weighted daily score per ticker.
    Note: coverage is thin for IBM (99 mentions) and UL (138 mentions).
    """
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM sentiment_scores")
    if cur.fetchone()[0] > 0:
        log.info("Sentiment already loaded — skipping")
        return

    data_dir = os.environ.get("DATA_DIR", "/app/data")
    news_dir = os.path.join(data_dir, "simulation_news_data_July_1-Aug_30")

    # Collect all ticker-day sentiment records
    records: dict[tuple, list] = {}   # (ticker, date) -> [score * relevance, ...]

    for fpath in sorted(glob.glob(os.path.join(news_dir, "*.json"))):
        data = json.load(open(fpath))
        for day_str, articles in data.items():
            date_iso = f"{day_str[:4]}-{day_str[4:6]}-{day_str[6:8]}"
            for article in articles:
                for ts in article.get("ticker_sentiment", []):
                    ticker = ts.get("ticker", "")
                    score = float(ts.get("ticker_sentiment_score", 0))
                    rel = float(ts.get("relevance_score", 1))
                    label = ts.get("ticker_sentiment_label", "Neutral")
                    key = (ticker, date_iso)
                    if key not in records:
                        records[key] = []
                    records[key].append((score, rel, label))

    # Aggregate: relevance-weighted average score
    rows = []
    for (ticker, date_iso), entries in records.items():
        total_rel = sum(e[1] for e in entries)
        if total_rel == 0:
            continue
        avg_score = sum(e[0] * e[1] for e in entries) / total_rel
        # Majority label
        from collections import Counter
        label = Counter(e[2] for e in entries).most_common(1)[0][0]
        rows.append((str(uuid.uuid4()), ticker, date_iso,
                     round(avg_score, 4), len(entries), label))

    execute_values(
        cur,
        """INSERT INTO sentiment_scores
             (id, instrument_id, score_date, avg_score, article_count, label)
           VALUES %s
           ON CONFLICT (instrument_id, score_date) DO NOTHING""",
        rows, page_size=500
    )
    conn.commit()
    log.info(f"Sentiment loaded: {len(rows)} ticker-day records")


def main():
    log.info("=== Data ingestion starting ===")
    conn = get_conn()
    try:
        result = ingest_prices(conn)
        trading_dates = result.get("trading_dates", [])
        build_market_calendar(conn, trading_dates)
        ingest_sentiment(conn)

        if result.get("quarantine"):
            log.warning("Quarantine summary:")
            for k, v in result["quarantine"].items():
                log.warning(f"  {k}: {v}")

        log.info("=== Data ingestion complete ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
