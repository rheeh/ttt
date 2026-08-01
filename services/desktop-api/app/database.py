from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models import CandidateCreate, CandidateItem, CandidateUpdate, PriceZones, QuoteSnapshot, ScoreResult


SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    selected_at TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    total_score INTEGER NOT NULL,
    grade TEXT NOT NULL CHECK (grade IN ('S', 'A', 'B', 'C')),
    reasons_json TEXT NOT NULL,
    dimensions_json TEXT NOT NULL,
    score_input_json TEXT NOT NULL,
    selected_price REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('new', 'watching', 'ready', 'abandoned', 'validated')),
    note TEXT,
    price_zones_json TEXT NOT NULL,
    UNIQUE(stock_code, strategy_id, strategy_version, selected_at)
);
CREATE INDEX IF NOT EXISTS ix_candidates_selected_at ON candidate_items(selected_at DESC);
CREATE INDEX IF NOT EXISTS ix_candidates_code ON candidate_items(stock_code);
CREATE INDEX IF NOT EXISTS ix_candidates_status ON candidate_items(status);
CREATE TABLE IF NOT EXISTS quote_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    source TEXT NOT NULL,
    trade_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(stock_code, source, trade_at)
);
CREATE INDEX IF NOT EXISTS ix_quotes_code_time ON quote_snapshots(stock_code, trade_at DESC);
"""


class CandidateRepository:
    def __init__(self, database_path: Path):
        self.path = database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def create(self, request: CandidateCreate, result: ScoreResult) -> CandidateItem:
        selected_at = datetime.now(timezone.utc).isoformat()
        reasons = [reason for part in result.dimensions for reason in part.reasons]
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO candidate_items (
                    stock_code, stock_name, selected_at, source_type, source_name,
                    strategy_id, strategy_version, total_score, grade, reasons_json,
                    dimensions_json, score_input_json, selected_price, status, note,
                    price_zones_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.stock_code, result.stock_name, selected_at,
                    request.source_type, request.source_name, result.strategy_id,
                    result.strategy_version, result.total_score, result.grade,
                    json.dumps(reasons, ensure_ascii=False),
                    json.dumps([item.model_dump() for item in result.dimensions], ensure_ascii=False),
                    request.score_input.model_dump_json(), request.score_input.price,
                    request.status, request.note, request.price_zones.model_dump_json(),
                ),
            )
            candidate_id = int(cursor.lastrowid)
        return self.get(candidate_id)

    def list(self, status: str | None = None, limit: int = 100) -> list[CandidateItem]:
        query = "SELECT * FROM candidate_items"
        params: list[object] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY selected_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._to_model(row) for row in rows]

    def get(self, candidate_id: int) -> CandidateItem:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM candidate_items WHERE id = ?", (candidate_id,)).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return self._to_model(row)

    def update(self, candidate_id: int, request: CandidateUpdate) -> CandidateItem:
        current = self.get(candidate_id)
        status = request.status if request.status is not None else current.status
        note = request.note if request.note is not None else current.note
        with self._connect() as connection:
            connection.execute(
                "UPDATE candidate_items SET status = ?, note = ? WHERE id = ?",
                (status, note, candidate_id),
            )
        return self.get(candidate_id)

    def save_quotes(self, quotes: list[QuoteSnapshot]) -> int:
        saved = 0
        with self._connect() as connection:
            for quote in quotes:
                trade_at = quote.trade_at or quote.fetched_at
                cursor = connection.execute(
                    """INSERT INTO quote_snapshots
                    (stock_code, source, trade_at, fetched_at, status, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(stock_code, source, trade_at) DO UPDATE SET
                      fetched_at=excluded.fetched_at,
                      status=excluded.status,
                      payload_json=excluded.payload_json""",
                    (
                        quote.stock_code, quote.source, trade_at.isoformat(),
                        quote.fetched_at.isoformat(), quote.status, quote.model_dump_json(),
                    ),
                )
                saved += max(cursor.rowcount, 0)
        return saved

    def list_quote_snapshots(self, limit: int = 100) -> list[QuoteSnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM quote_snapshots ORDER BY trade_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [QuoteSnapshot.model_validate_json(row["payload_json"]) for row in rows]

    @staticmethod
    def _to_model(row: sqlite3.Row) -> CandidateItem:
        return CandidateItem(
            id=row["id"], stock_code=row["stock_code"], stock_name=row["stock_name"],
            selected_at=datetime.fromisoformat(row["selected_at"]), source_type=row["source_type"],
            source_name=row["source_name"], strategy_id=row["strategy_id"],
            strategy_version=row["strategy_version"], total_score=row["total_score"], grade=row["grade"],
            reasons=json.loads(row["reasons_json"]), dimensions=json.loads(row["dimensions_json"]),
            score_input=json.loads(row["score_input_json"]), selected_price=row["selected_price"],
            status=row["status"], note=row["note"], price_zones=PriceZones.model_validate_json(row["price_zones_json"]),
        )
