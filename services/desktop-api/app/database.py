from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.analysis.models import AnalysisReport
from app.models import (
    CandidateCreate, CandidateItem, CandidateUpdate, DataSourceHealth, MarketReviewResponse, MarketReviewItem, MarketReviewRun, MarketScanResponse, MarketSectorReview,
    PerformanceHorizonSummary, PerformanceOutcome, PriceZones, QuoteSnapshot, ScoreInput, ScoreResult, WatchlistCreate, WatchlistItem,
)


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
    rule_fingerprint TEXT NOT NULL DEFAULT 'legacy-unknown',
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
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    total INTEGER NOT NULL,
    succeeded INTEGER NOT NULL,
    degraded INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    scoreable INTEGER NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    rule_fingerprint TEXT NOT NULL,
    rotation_pool_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_run_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
    stock_code TEXT NOT NULL,
    rank INTEGER NOT NULL,
    preset_json TEXT NOT NULL,
    quote_json TEXT NOT NULL,
    score_json TEXT,
    score_input_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_scan_items_run_rank ON scan_run_items(run_id, rank);
CREATE TABLE IF NOT EXISTS candidate_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL REFERENCES candidate_items(id) ON DELETE CASCADE,
    horizon TEXT NOT NULL CHECK (horizon IN ('1d', '5d', '20d')),
    due_date TEXT NOT NULL,
    baseline_price REAL NOT NULL,
    realized_price REAL,
    return_pct REAL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'verified', 'unavailable')),
    measured_at TEXT,
    source TEXT,
    note TEXT,
    UNIQUE(candidate_id, horizon)
);
CREATE INDEX IF NOT EXISTS ix_performance_due ON candidate_performance(status, due_date);
CREATE TABLE IF NOT EXISTS analysis_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    sector TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_analysis_reports_code_time ON analysis_reports(stock_code, created_at DESC);
CREATE TABLE IF NOT EXISTS analysis_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES analysis_reports(id) ON DELETE CASCADE,
    fact_type TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_analysis_facts_report ON analysis_facts(report_id, fact_type);
CREATE TABLE IF NOT EXISTS analysis_source_cache (
    stock_code TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(stock_code, source)
);
CREATE INDEX IF NOT EXISTS ix_analysis_source_cache_time ON analysis_source_cache(fetched_at DESC);
CREATE TABLE IF NOT EXISTS data_source_health (
    source TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    installed INTEGER NOT NULL,
    accessible INTEGER NOT NULL,
    valid INTEGER NOT NULL,
    status TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    response_ms INTEGER,
    last_success_at TEXT,
    error TEXT,
    details TEXT
);
CREATE TABLE IF NOT EXISTS watchlist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    sector TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('stock', 'etf')),
    added_at TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_watchlist_added_at ON watchlist_items(added_at DESC);
"""


class CandidateRepository:
    def __init__(self, database_path: Path):
        self.path = database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(candidate_items)")}
            if "rule_fingerprint" not in columns:
                connection.execute("ALTER TABLE candidate_items ADD COLUMN rule_fingerprint TEXT NOT NULL DEFAULT 'legacy-unknown'")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def create(self, request: CandidateCreate, result: ScoreResult) -> CandidateItem:
        selected_dt = datetime.now(timezone.utc)
        selected_at = selected_dt.isoformat()
        reasons = [reason for part in result.dimensions for reason in part.reasons]
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO candidate_items (
                    stock_code, stock_name, selected_at, source_type, source_name,
                    strategy_id, strategy_version, rule_fingerprint, total_score, grade, reasons_json,
                    dimensions_json, score_input_json, selected_price, status, note,
                    price_zones_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.stock_code, result.stock_name, selected_at,
                    request.source_type, request.source_name, result.strategy_id,
                    result.strategy_version, result.rule_fingerprint, result.total_score, result.grade,
                    json.dumps(reasons, ensure_ascii=False),
                    json.dumps([item.model_dump() for item in result.dimensions], ensure_ascii=False),
                    request.score_input.model_dump_json(), request.score_input.price,
                    request.status, request.note, request.price_zones.model_dump_json(),
                ),
            )
            candidate_id = int(cursor.lastrowid)
            for horizon, offset in (("1d", 1), ("5d", 5), ("20d", 20)):
                connection.execute(
                    """INSERT INTO candidate_performance
                    (candidate_id, horizon, due_date, baseline_price, status)
                    VALUES (?, ?, ?, ?, 'pending')""",
                    (candidate_id, horizon, self._business_day(selected_dt.date(), offset).isoformat(), request.score_input.price),
                )
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

    def save_scan(self, result: MarketScanResponse) -> int:
        first = result.items[0].score if result.items else None
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO scan_runs
                (started_at, completed_at, source, total, succeeded, degraded, failed, scoreable,
                 strategy_id, strategy_version, rule_fingerprint, rotation_pool_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (result.started_at.isoformat(), result.completed_at.isoformat(), result.source,
                 result.total, result.succeeded, result.degraded, result.failed, result.scoreable,
                 first.strategy_id if first else "group-original", first.strategy_version if first else "unknown",
                 result.rule_fingerprint, json.dumps(result.rotation_pool_codes)),
            )
            run_id = int(cursor.lastrowid)
            for rank, item in enumerate(result.items, start=1):
                connection.execute(
                    """INSERT INTO scan_run_items
                    (run_id, stock_code, rank, preset_json, quote_json, score_json, score_input_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, item.preset.code, rank, item.preset.model_dump_json(), item.quote.model_dump_json(),
                     item.score.model_dump_json() if item.score else None,
                     item.score_input.model_dump_json() if item.score_input else None),
                )
        return run_id

    def scan_candidates(self, run_id: int, limit: int, min_grade: str) -> list[tuple[ScoreInput, ScoreResult]]:
        order = {"S": 0, "A": 1, "B": 2, "C": 3}
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT score_json, score_input_json FROM scan_run_items WHERE run_id = ? ORDER BY rank",
                (run_id,),
            ).fetchall()
        output = []
        for row in rows:
            if not row["score_json"] or not row["score_input_json"]:
                continue
            score = ScoreResult.model_validate_json(row["score_json"])
            if order[score.grade] <= order[min_grade] and score.eligible:
                output.append((ScoreInput.model_validate_json(row["score_input_json"]), score))
            if len(output) >= limit:
                break
        return output

    def list_market_review_runs(self, limit: int = 30) -> list[MarketReviewRun]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [MarketReviewRun(
            run_id=row["id"], completed_at=datetime.fromisoformat(row["completed_at"]), source=row["source"],
            total=row["total"], scoreable=row["scoreable"], average_change_pct=self._scan_average_change(row["id"]),
        ) for row in rows]

    def market_review(self, run_id: int | None = None) -> MarketReviewResponse:
        with self._connect() as connection:
            run = connection.execute(
                "SELECT * FROM scan_runs WHERE id = ?" if run_id else "SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1",
                (run_id,) if run_id else (),
            ).fetchone()
            if run is None:
                return MarketReviewResponse()
            rows = connection.execute(
                "SELECT preset_json, quote_json, score_json FROM scan_run_items WHERE run_id = ? ORDER BY rank",
                (run["id"],),
            ).fetchall()
        items: list[MarketReviewItem] = []
        for row in rows:
            preset = json.loads(row["preset_json"])
            quote = QuoteSnapshot.model_validate_json(row["quote_json"])
            score = ScoreResult.model_validate_json(row["score_json"]) if row["score_json"] else None
            items.append(MarketReviewItem(
                stock_code=preset["code"], stock_name=quote.stock_name or preset["name"], sector=preset["sector"],
                price=quote.price, change_pct=quote.change_pct, grade=score.grade if score else None,
                score=score.total_score if score else None, status=quote.status,
            ))
        changes = [item.change_pct for item in items if item.change_pct is not None]
        up_count = sum(value > 0 for value in changes)
        down_count = sum(value < 0 for value in changes)
        score_values = [item.score for item in items if item.score is not None]
        sectors: dict[str, list[MarketReviewItem]] = {}
        for item in items:
            sectors.setdefault(item.sector, []).append(item)
        sector_rows = [MarketSectorReview(
            sector=sector, count=len(members),
            average_change_pct=round(sum(value for value in (item.change_pct for item in members) if value is not None) / len([item for item in members if item.change_pct is not None]), 2) if any(item.change_pct is not None for item in members) else None,
            up_count=sum((item.change_pct or 0) > 0 for item in members),
            scoreable=sum(item.score is not None for item in members),
            average_score=round(sum(item.score for item in members if item.score is not None) / sum(item.score is not None for item in members), 2) if any(item.score is not None for item in members) else None,
        ) for sector, members in sectors.items()]
        sector_rows.sort(key=lambda item: item.average_change_pct if item.average_change_pct is not None else -999, reverse=True)
        return MarketReviewResponse(
            run_id=run["id"], as_of=datetime.fromisoformat(run["completed_at"]), source=run["source"],
            total=run["total"], succeeded=run["succeeded"], degraded=run["degraded"], failed=run["failed"], scoreable=run["scoreable"],
            up_count=up_count, down_count=down_count, flat_count=len(changes) - up_count - down_count,
            breadth_pct=round(up_count / len(changes) * 100, 2) if changes else None,
            average_change_pct=round(sum(changes) / len(changes), 2) if changes else None,
            average_score=round(sum(score_values) / len(score_values), 2) if score_values else None,
            rotation_pool_codes=json.loads(run["rotation_pool_json"]),
            top_gainers=sorted(items, key=lambda item: item.change_pct if item.change_pct is not None else -999, reverse=True)[:10],
            top_scores=sorted((item for item in items if item.score is not None), key=lambda item: item.score or -999, reverse=True)[:10],
            sectors=sector_rows[:12],
        )

    def _scan_average_change(self, run_id: int) -> float | None:
        with self._connect() as connection:
            values = [row[0] for row in connection.execute(
                "SELECT json_extract(quote_json, '$.change_pct') FROM scan_run_items WHERE run_id = ?",
                (run_id,),
            ).fetchall() if row[0] is not None]
        return round(sum(values) / len(values), 2) if values else None

    def save_source_health(self, health: DataSourceHealth) -> DataSourceHealth:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO data_source_health
                (source, category, installed, accessible, valid, status, checked_at, response_ms, last_success_at, error, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                  category=excluded.category, installed=excluded.installed, accessible=excluded.accessible,
                  valid=excluded.valid, status=excluded.status, checked_at=excluded.checked_at,
                  response_ms=excluded.response_ms, last_success_at=COALESCE(excluded.last_success_at, data_source_health.last_success_at),
                  error=excluded.error, details=excluded.details""",
                (health.source, health.category, int(health.installed), int(health.accessible), int(health.valid), health.status,
                 health.checked_at.isoformat(), health.response_ms, health.last_success_at.isoformat() if health.last_success_at else None,
                 health.error, health.details),
            )
        return health

    def list_source_health(self) -> list[DataSourceHealth]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM data_source_health ORDER BY category, source").fetchall()
        return [DataSourceHealth(
            source=row["source"], category=row["category"], installed=bool(row["installed"]), accessible=bool(row["accessible"]),
            valid=bool(row["valid"]), status=row["status"], checked_at=datetime.fromisoformat(row["checked_at"]),
            response_ms=row["response_ms"], last_success_at=datetime.fromisoformat(row["last_success_at"]) if row["last_success_at"] else None,
            error=row["error"], details=row["details"],
        ) for row in rows]

    def verify_performance(self, as_of: date) -> list[PerformanceOutcome]:
        now = datetime.now(timezone.utc).isoformat()
        changed: list[PerformanceOutcome] = []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM candidate_performance WHERE status = 'pending' AND due_date <= ? ORDER BY due_date",
                (as_of.isoformat(),),
            ).fetchall()
            for row in rows:
                quote_row = connection.execute(
                    """SELECT payload_json FROM quote_snapshots
                    WHERE stock_code = ? AND date(trade_at) >= ? AND date(trade_at) <= ?
                    ORDER BY trade_at LIMIT 1""",
                    (connection.execute("SELECT stock_code FROM candidate_items WHERE id = ?", (row["candidate_id"],)).fetchone()[0],
                     row["due_date"], as_of.isoformat()),
                ).fetchone()
                status, realized, return_pct, source, note = "pending", None, None, None, None
                if quote_row:
                    quote = QuoteSnapshot.model_validate_json(quote_row["payload_json"])
                    if quote.price and quote.price > 0:
                        realized = quote.price
                        return_pct = round((realized - row["baseline_price"]) / row["baseline_price"] * 100, 4)
                        status, source = "verified", quote.source
                elif as_of > date.fromisoformat(row["due_date"]) + timedelta(days=10):
                    status, note = "unavailable", "目标交易日后仍无有效行情快照"
                if status != "pending":
                    connection.execute(
                        """UPDATE candidate_performance SET realized_price=?, return_pct=?, status=?, measured_at=?, source=?, note=? WHERE id=?""",
                        (realized, return_pct, status, now, source, note, row["id"]),
                    )
                changed.append(PerformanceOutcome(
                    candidate_id=row["candidate_id"], horizon=row["horizon"], due_date=date.fromisoformat(row["due_date"]),
                    baseline_price=row["baseline_price"], realized_price=realized, return_pct=return_pct,
                    status=status, measured_at=datetime.fromisoformat(now) if status != "pending" else None,
                    source=source, note=note,
                ))
        return changed

    def performance_summary(self, as_of: date) -> dict:
        with self._connect() as connection:
            counts = {row["status"]: row["count"] for row in connection.execute(
                "SELECT status, COUNT(*) AS count FROM candidate_performance GROUP BY status"
            ).fetchall()}
            horizon_rows = connection.execute(
                """SELECT horizon,
                    COUNT(*) AS samples,
                    SUM(CASE WHEN status = 'verified' THEN 1 ELSE 0 END) AS verified,
                    SUM(CASE WHEN status = 'verified' AND return_pct > 0 THEN 1 ELSE 0 END) AS wins,
                    AVG(CASE WHEN status = 'verified' THEN return_pct END) AS average_return
                FROM candidate_performance GROUP BY horizon
                ORDER BY CASE horizon WHEN '1d' THEN 1 WHEN '5d' THEN 5 ELSE 20 END"""
            ).fetchall()
        horizon_summary = [PerformanceHorizonSummary(
            horizon=row["horizon"], samples=row["samples"], verified=row["verified"] or 0, wins=row["wins"] or 0,
            win_rate_pct=round((row["wins"] or 0) / row["verified"] * 100, 2) if row["verified"] else None,
            average_return_pct=round(row["average_return"], 4) if row["average_return"] is not None else None,
        ) for row in horizon_rows]
        return {
            "processed": sum(counts.values()), "verified": counts.get("verified", 0),
            "pending": counts.get("pending", 0), "unavailable": counts.get("unavailable", 0),
            "horizon_summary": horizon_summary,
        }

    def list_performance(self, candidate_id: int) -> list[PerformanceOutcome]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM candidate_performance WHERE candidate_id = ? ORDER BY CASE horizon WHEN '1d' THEN 1 WHEN '5d' THEN 5 ELSE 20 END",
                (candidate_id,),
            ).fetchall()
        return [PerformanceOutcome(
            candidate_id=row["candidate_id"], horizon=row["horizon"], due_date=date.fromisoformat(row["due_date"]),
            baseline_price=row["baseline_price"], realized_price=row["realized_price"], return_pct=row["return_pct"],
            status=row["status"], measured_at=datetime.fromisoformat(row["measured_at"]) if row["measured_at"] else None,
            source=row["source"], note=row["note"],
        ) for row in rows]

    def save_analysis(self, report: AnalysisReport) -> AnalysisReport:
        payload = report.model_dump_json()
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO analysis_reports
                (created_at, stock_code, stock_name, sector, source, status, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (report.created_at.isoformat(), report.stock_code, report.stock_name, report.sector,
                 report.source, report.status, payload),
            )
            report_id = int(cursor.lastrowid)
            for fact_type, value in (("quote", report.quote), ("technical", report.technical.model_dump()),
                                     ("rocket", report.rocket.model_dump()), ("advice", report.advice.model_dump()),
                                     ("fund_flow", report.fund_flow), ("finance", report.finance),
                                     ("industry", report.industry), ("news", report.news),
                                     ("bars", [bar.model_dump() for bar in report.bars]),
                                     ("weekly_bars", [bar.model_dump() for bar in report.weekly_bars])):
                source = value.get("source", report.source) if isinstance(value, dict) else report.source
                fetched_at = value.get("fetched_at", report.created_at.isoformat()) if isinstance(value, dict) else report.created_at.isoformat()
                connection.execute(
                    """INSERT INTO analysis_facts
                    (report_id, fact_type, source, fetched_at, payload_json)
                    VALUES (?, ?, ?, ?, ?)""",
                    (report_id, fact_type, source, str(fetched_at),
                     json.dumps(value, ensure_ascii=False, default=str)),
                )
        return report.model_copy(update={"report_id": report_id})

    def get_analysis(self, report_id: int) -> AnalysisReport:
        with self._connect() as connection:
            row = connection.execute("SELECT payload_json FROM analysis_reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            raise KeyError(report_id)
        return AnalysisReport.model_validate_json(row["payload_json"]).model_copy(update={"report_id": report_id})

    def save_source_cache(self, stock_code: str, source: str, fetched_at: str, payload: dict) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO analysis_source_cache (stock_code, source, fetched_at, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(stock_code, source) DO UPDATE SET
                  fetched_at=excluded.fetched_at, payload_json=excluded.payload_json""",
                (stock_code, source, fetched_at, json.dumps(payload, ensure_ascii=False, default=str)),
            )

    def get_source_cache(self, stock_code: str, source: str) -> tuple[str, dict] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT fetched_at, payload_json FROM analysis_source_cache WHERE stock_code = ? AND source = ?",
                (stock_code, source),
            ).fetchone()
        if row is None:
            return None
        return str(row["fetched_at"]), json.loads(row["payload_json"])

    def list_analyses(self, stock_code: str | None = None, limit: int = 50) -> list[AnalysisReport]:
        query = "SELECT id, payload_json FROM analysis_reports"
        params: list[object] = []
        if stock_code:
            query += " WHERE stock_code = ?"
            params.append(stock_code)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [AnalysisReport.model_validate_json(row["payload_json"]).model_copy(update={"report_id": row["id"]}) for row in rows]

    def add_watchlist(self, request: WatchlistCreate, source: str = "user-search") -> WatchlistItem:
        added_at = datetime.now(timezone.utc)
        code = request.code.strip().lower()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO watchlist_items (code, name, sector, asset_type, added_at, source)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET name=excluded.name, sector=excluded.sector,
                    asset_type=excluded.asset_type, source=excluded.source""",
                (code, request.name, request.sector, request.asset_type, added_at.isoformat(), source),
            )
            row = connection.execute("SELECT * FROM watchlist_items WHERE code = ?", (code,)).fetchone()
        return self._watchlist_model(row)

    def list_watchlist(self) -> list[WatchlistItem]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM watchlist_items ORDER BY added_at DESC, id DESC").fetchall()
        return [self._watchlist_model(row) for row in rows]

    def delete_watchlist(self, code: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM watchlist_items WHERE code = ?", (code.strip().lower(),))
        return cursor.rowcount > 0

    @staticmethod
    def _watchlist_model(row: sqlite3.Row) -> WatchlistItem:
        return WatchlistItem(
            id=row["id"], code=row["code"], name=row["name"], sector=row["sector"],
            asset_type=row["asset_type"], added_at=datetime.fromisoformat(row["added_at"]), source=row["source"],
        )

    def list_quote_snapshots(self, limit: int = 100) -> list[QuoteSnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM quote_snapshots ORDER BY trade_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [QuoteSnapshot.model_validate_json(row["payload_json"]) for row in rows]

    def _to_model(self, row: sqlite3.Row) -> CandidateItem:
        return CandidateItem(
            id=row["id"], stock_code=row["stock_code"], stock_name=row["stock_name"],
            selected_at=datetime.fromisoformat(row["selected_at"]), source_type=row["source_type"],
            source_name=row["source_name"], strategy_id=row["strategy_id"],
            strategy_version=row["strategy_version"], rule_fingerprint=row["rule_fingerprint"], total_score=row["total_score"], grade=row["grade"],
            reasons=json.loads(row["reasons_json"]), dimensions=json.loads(row["dimensions_json"]),
            score_input=json.loads(row["score_input_json"]), selected_price=row["selected_price"],
            status=row["status"], note=row["note"], price_zones=PriceZones.model_validate_json(row["price_zones_json"]),
            performance=self.list_performance(row["id"]),
        )

    @staticmethod
    def _business_day(start: date, offset: int) -> date:
        current, remaining = start, offset
        while remaining:
            current += timedelta(days=1)
            if current.weekday() < 5:
                remaining -= 1
        return current
