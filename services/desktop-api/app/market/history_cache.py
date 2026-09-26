"""Validated whole-window history cache and per-symbol fetch receipts.

Tencent qfq windows are replaced as a whole: appending values from different
vendor anchors would mix price scales after a corporate action.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from app.analysis.models import DailyBar
from app.market.daily_contract import BarSeries, CONTRACT_VERSION, daily_metadata
from app.market.trading_calendar import market_now


class HistoryCache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS constituent_history_cache (
                code TEXT PRIMARY KEY, contract_version TEXT NOT NULL, fetched_at TEXT NOT NULL,
                latest_trade_date TEXT NOT NULL, bar_count INTEGER NOT NULL, digest TEXT NOT NULL,
                bars_json TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS constituent_fetch_receipts (
                code TEXT PRIMARY KEY, attempted_at TEXT NOT NULL, status TEXT NOT NULL,
                error TEXT, attempts INTEGER NOT NULL DEFAULT 1)""")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def get(self, code: str, expected: date | None, minimum_bars: int) -> BarSeries | None:
        if expected is None:
            return None
        with self._connect() as db:
            row = db.execute("""SELECT bars_json, fetched_at, digest FROM constituent_history_cache
                WHERE code=? AND contract_version=? AND latest_trade_date=? AND bar_count>=?""",
                (code, CONTRACT_VERSION, expected.isoformat(), minimum_bars)).fetchone()
        if row is None:
            return None
        try:
            bars = BarSeries([DailyBar.model_validate(bar) for bar in json.loads(row[0])])
            if daily_metadata(bars)["content_sha256"] != row[2]:
                return None
            bars.fetched_at = row[1]
            return bars
        except (ValueError, TypeError):
            return None

    def save(self, code: str, bars: list[DailyBar]) -> None:
        meta = daily_metadata(bars)
        with self._connect() as db:
            db.execute("""INSERT OR REPLACE INTO constituent_history_cache
                VALUES (?, ?, ?, ?, ?, ?, ?)""", (code, CONTRACT_VERSION, market_now().isoformat(),
                meta["coverage_end"], len(bars), meta["content_sha256"],
                json.dumps([bar.model_dump(mode="json") for bar in bars])))
        self.record(code, None)

    def record(self, code: str, error: str | None) -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO constituent_fetch_receipts(code, attempted_at, status, error)
                VALUES (?, ?, ?, ?) ON CONFLICT(code) DO UPDATE SET attempted_at=excluded.attempted_at,
                status=excluded.status, error=excluded.error, attempts=constituent_fetch_receipts.attempts+1""",
                (code, market_now().isoformat(), "error" if error else "ok", error))


class HistoryBatch(dict):
    def __init__(self):
        super().__init__()
        self.failures: dict[str, str] = {}
        self.cache_hits: list[str] = []
