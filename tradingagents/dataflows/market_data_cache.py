"""Persistent SQLite cache for historical market bars."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from typing import Iterable

import pandas as pd

from .config import get_config


_BAR_COLUMNS = ("open", "high", "low", "close", "volume", "trade_count", "vwap")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    feed TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    trade_count REAL,
    vwap REAL,
    PRIMARY KEY (symbol, timeframe, feed, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_bars_range
    ON bars (symbol, timeframe, feed, timestamp);
CREATE TABLE IF NOT EXISTS bar_coverage (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    feed TEXT NOT NULL,
    start_ts TEXT NOT NULL,
    end_ts TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (symbol, timeframe, feed, start_ts, end_ts)
);
CREATE INDEX IF NOT EXISTS idx_bar_coverage_range
    ON bar_coverage (symbol, timeframe, feed, start_ts, end_ts);
"""


def _database_path() -> Path:
    config = get_config()
    cache_dir = Path(config["data_cache_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "market_data.sqlite3"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_database_path()), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(_SCHEMA)
    return conn


@contextmanager
def _connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def normalize_timestamp(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _timestamp_text(value) -> str:
    return normalize_timestamp(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _normalise_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _normalise_feed(feed) -> str:
    return str(getattr(feed, "value", feed) or "IEX").upper()


def _coverage_rows(symbol: str, timeframe: str, feed: str):
    with _connection() as conn:
        return conn.execute(
            """SELECT start_ts, end_ts, fetched_at FROM bar_coverage
               WHERE symbol = ? AND timeframe = ? AND feed = ?
               ORDER BY start_ts, end_ts""",
            (_normalise_symbol(symbol), str(timeframe), _normalise_feed(feed)),
        ).fetchall()


def _uncovered_ranges(start: pd.Timestamp, end: pd.Timestamp, intervals: Iterable[tuple[str, str]]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    cursor = start
    gaps = []
    sorted_intervals = sorted(
        (normalize_timestamp(left), normalize_timestamp(right))
        for left, right in intervals
        if normalize_timestamp(right) > start and normalize_timestamp(left) < end
    )
    for interval_start, interval_end in sorted_intervals:
        interval_start = max(interval_start, start)
        interval_end = min(interval_end, end)
        if interval_start > cursor:
            gaps.append((cursor, interval_start))
        if interval_end > cursor:
            cursor = interval_end
        if cursor >= end:
            break
    if cursor < end:
        gaps.append((cursor, end))
    return [(left, right) for left, right in gaps if right > left]


def ranges_to_fetch(
    symbol: str,
    timeframe: str,
    feed,
    start,
    end,
    *,
    now: datetime | None = None,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return missing history plus a stale recent tail that should be refreshed."""
    start_ts = normalize_timestamp(start)
    end_ts = normalize_timestamp(end)
    if end_ts <= start_ts:
        return []

    rows = _coverage_rows(symbol, timeframe, _normalise_feed(feed))
    covered = [(row[0], row[1]) for row in rows]
    ranges = _uncovered_ranges(start_ts, end_ts, covered)

    current = normalize_timestamp(now or datetime.now(timezone.utc))
    try:
        ttl_seconds = max(0, int(os.getenv("MARKET_DATA_CACHE_TTL_SECONDS", "300")))
    except ValueError:
        ttl_seconds = 300

    # Keep historical ranges immutable after their first successful fetch. For
    # requests reaching the recent two-day window, refresh only that tail when
    # its cached coverage is older than the configured TTL.
    if ttl_seconds and end_ts >= current - pd.Timedelta(days=2):
        tail_start = max(start_ts, end_ts - pd.Timedelta(days=2))
        cutoff = current - pd.Timedelta(seconds=ttl_seconds)
        fresh_coverage = [
            (row[0], row[1])
            for row in rows
            if normalize_timestamp(row[2]) >= cutoff
        ]
        ranges.extend(_uncovered_ranges(tail_start, end_ts, fresh_coverage))

    if not ranges:
        return []

    # Merge overlapping gaps and refresh windows so each missing segment is
    # requested from Alpaca once.
    merged = []
    for left, right in sorted(ranges, key=lambda item: item[0]):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return merged


def _frame_for_storage(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=("timestamp", *_BAR_COLUMNS))
    data = frame.copy()
    aliases = {
        "Date": "timestamp",
        "Datetime": "timestamp",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "VWAP": "vwap",
        "TradeCount": "trade_count",
        "tradeCount": "trade_count",
    }
    data = data.rename(columns={key: value for key, value in aliases.items() if key in data.columns})
    if "timestamp" not in data.columns and isinstance(data.index, pd.DatetimeIndex):
        data = data.reset_index().rename(columns={data.index.name or "index": "timestamp"})
    if "timestamp" not in data.columns:
        return pd.DataFrame(columns=("timestamp", *_BAR_COLUMNS))
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True, errors="coerce")
    for column in _BAR_COLUMNS:
        if column not in data.columns:
            data[column] = None
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data[["timestamp", *_BAR_COLUMNS]].dropna(subset=["timestamp"])


def store_bars(
    symbol: str,
    timeframe: str,
    feed,
    start,
    end,
    frame: pd.DataFrame,
    *,
    fetched_at: datetime | float | None = None,
    overwrite: bool = True,
) -> None:
    """Upsert bars and record successful coverage, including no-trade periods."""
    symbol_key = _normalise_symbol(symbol)
    timeframe_key = str(timeframe)
    feed_key = _normalise_feed(feed)
    start_text = _timestamp_text(start)
    end_text = _timestamp_text(end)
    if isinstance(fetched_at, (int, float)):
        fetched = datetime.fromtimestamp(fetched_at, tz=timezone.utc)
    else:
        fetched = fetched_at or datetime.now(timezone.utc)
    fetched_text = _timestamp_text(fetched)
    data = _frame_for_storage(frame)
    rows = []
    for row in data.itertuples(index=False, name=None):
        timestamp = _timestamp_text(row[0])
        values = [None if pd.isna(value) else float(value) for value in row[1:]]
        rows.append((symbol_key, timeframe_key, feed_key, timestamp, *values))

    with _connection() as conn:
        if rows:
            if overwrite:
                sql = """INSERT INTO bars
                   (symbol, timeframe, feed, timestamp, open, high, low, close, volume, trade_count, vwap)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(symbol, timeframe, feed, timestamp) DO UPDATE SET
                     open=excluded.open, high=excluded.high, low=excluded.low,
                     close=excluded.close, volume=excluded.volume,
                     trade_count=excluded.trade_count, vwap=excluded.vwap"""
            else:
                sql = """INSERT OR IGNORE INTO bars
                   (symbol, timeframe, feed, timestamp, open, high, low, close, volume, trade_count, vwap)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            conn.executemany(sql, rows)
        conn.execute(
            """INSERT INTO bar_coverage
               (symbol, timeframe, feed, start_ts, end_ts, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol, timeframe, feed, start_ts, end_ts)
               DO UPDATE SET fetched_at=excluded.fetched_at""",
            (symbol_key, timeframe_key, feed_key, start_text, end_text, fetched_text),
        )


def load_bars(symbol: str, timeframe: str, feed, start, end) -> pd.DataFrame:
    """Read cached bars in the half-open UTC range [start, end)."""
    with _connection() as conn:
        rows = conn.execute(
            """SELECT timestamp, open, high, low, close, volume, trade_count, vwap
               FROM bars
               WHERE symbol = ? AND timeframe = ? AND feed = ?
                 AND timestamp >= ? AND timestamp < ?
               ORDER BY timestamp""",
            (
                _normalise_symbol(symbol),
                str(timeframe),
                _normalise_feed(feed),
                _timestamp_text(start),
                _timestamp_text(end),
            ),
        ).fetchall()
    columns = ("timestamp", *_BAR_COLUMNS)
    data = pd.DataFrame.from_records(rows, columns=columns)
    if not data.empty:
        data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    return data
