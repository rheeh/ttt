from __future__ import annotations

import json
import hashlib
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from app.analysis.models import AnalysisReport
from app.models import (
    CandidateCreate, CandidateItem, CandidateUpdate, DataSourceHealth, MarketReviewResponse, MarketReviewItem, MarketReviewRun, MarketScanResponse, MarketSectorReview,
    IndustryAlert, IndustryConstituent, IndustryHistoryPoint, IndustryRadarDetailResponse, IndustryRadarItem, IndustryRadarResponse, IndustryWatchItem, PerformanceHorizonSummary, PerformanceOutcome, PriceZones, QuoteSnapshot, ScoreInput, ScoreResult, WatchlistCreate, WatchlistItem,
    IndustrySignalOutcome, IndustrySignalVerificationResponse,
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
    signal_context_json TEXT NOT NULL DEFAULT '{}',
    signal_fingerprint TEXT,
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
    rotation_pool_json TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'reference_pool',
    pool_name TEXT NOT NULL DEFAULT 'reference-pool',
    pool_version TEXT NOT NULL DEFAULT 'unknown',
    pool_component_count INTEGER NOT NULL DEFAULT 0,
    transaction_date TEXT,
    coverage_count INTEGER NOT NULL DEFAULT 0,
    coverage_total INTEGER NOT NULL DEFAULT 0,
    coverage_pct REAL,
    data_status TEXT NOT NULL DEFAULT 'degraded',
    degraded_reasons_json TEXT NOT NULL DEFAULT '[]'
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
    horizon TEXT NOT NULL CHECK (horizon IN ('1d', '5d', '20d', '60d')),
    due_date TEXT NOT NULL,
    baseline_price REAL NOT NULL,
    realized_price REAL,
    realized_trade_date TEXT,
    return_pct REAL,
    benchmark_code TEXT,
    benchmark_baseline_price REAL,
    benchmark_realized_price REAL,
    benchmark_return_pct REAL,
    relative_return_pct REAL,
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
    payload_json TEXT NOT NULL,
    trade_date TEXT,
    content_fingerprint TEXT,
    snapshot_reason TEXT NOT NULL DEFAULT 'legacy_run',
    snapshot_note TEXT
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
CREATE TABLE IF NOT EXISTS industry_daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    source TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    data_status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(snapshot_date, source, rule_version)
);
CREATE INDEX IF NOT EXISTS ix_industry_snapshot_date ON industry_daily_snapshots(snapshot_date DESC);
CREATE TABLE IF NOT EXISTS industry_master (
    industry_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    taxonomy TEXT NOT NULL,
    source TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS industry_constituents (
    industry_id TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    source TEXT NOT NULL,
    PRIMARY KEY(industry_id, stock_code, effective_from)
);
CREATE INDEX IF NOT EXISTS ix_industry_constituents_code ON industry_constituents(stock_code);
CREATE TABLE IF NOT EXISTS industry_daily (
    industry_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    close REAL,
    return_5d REAL,
    return_20d REAL,
    return_60d REAL,
    relative_return_20d REAL,
    breadth_ma20 REAL,
    breadth_ma60 REAL,
    advance_ratio REAL,
    new_high_ratio REAL,
    volume_ratio REAL,
    coverage_pct REAL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(industry_id, trade_date)
);
CREATE INDEX IF NOT EXISTS ix_industry_daily_date ON industry_daily(trade_date DESC);
CREATE TABLE IF NOT EXISTS industry_benchmark_daily (
    benchmark_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    close REAL NOT NULL,
    PRIMARY KEY(benchmark_code, trade_date)
);
CREATE INDEX IF NOT EXISTS ix_industry_benchmark_date ON industry_benchmark_daily(benchmark_code, trade_date DESC);
CREATE TABLE IF NOT EXISTS industry_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    industry_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    stage TEXT NOT NULL,
    score REAL,
    rule_version TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    risk_json TEXT NOT NULL,
    signal_direction TEXT NOT NULL DEFAULT 'neutral',
    execution_date TEXT,
    confirmation_days INTEGER NOT NULL DEFAULT 0,
    UNIQUE(industry_id, trade_date, rule_version)
);
CREATE TABLE IF NOT EXISTS industry_signal_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL REFERENCES industry_signals(id) ON DELETE CASCADE,
    horizon TEXT NOT NULL,
    return_pct REAL,
    benchmark_return_pct REAL,
    relative_return_pct REAL,
    mfe_pct REAL,
    mae_pct REAL,
    execution_date TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'unavailable')),
    measured_at TEXT,
    note TEXT,
    UNIQUE(signal_id, horizon)
);
CREATE TABLE IF NOT EXISTS industry_watchlist (
    industry_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
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
            candidate_migrations = {
                "signal_context_json": "TEXT NOT NULL DEFAULT '{}'",
                "signal_fingerprint": "TEXT",
            }
            for name, definition in candidate_migrations.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE candidate_items ADD COLUMN {name} {definition}")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_signal_fingerprint ON candidate_items(signal_fingerprint) WHERE signal_fingerprint IS NOT NULL")
            scan_columns = {row["name"] for row in connection.execute("PRAGMA table_info(scan_runs)")}
            migrations = {
                "scope": "TEXT NOT NULL DEFAULT 'reference_pool'",
                "pool_name": "TEXT NOT NULL DEFAULT 'reference-pool'",
                "pool_version": "TEXT NOT NULL DEFAULT 'unknown'",
                "pool_component_count": "INTEGER NOT NULL DEFAULT 0",
                "transaction_date": "TEXT",
                "coverage_count": "INTEGER NOT NULL DEFAULT 0",
                "coverage_total": "INTEGER NOT NULL DEFAULT 0",
                "coverage_pct": "REAL",
                "data_status": "TEXT NOT NULL DEFAULT 'degraded'",
                "degraded_reasons_json": "TEXT NOT NULL DEFAULT '[]'",
            }
            for name, definition in migrations.items():
                if name not in scan_columns:
                    connection.execute(f"ALTER TABLE scan_runs ADD COLUMN {name} {definition}")
            performance_sql = connection.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'candidate_performance'").fetchone()[0] or ""
            if "'60d'" not in performance_sql:
                connection.execute("DROP INDEX IF EXISTS ix_performance_due")
                connection.execute("ALTER TABLE candidate_performance RENAME TO candidate_performance_legacy")
                connection.execute("""CREATE TABLE candidate_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL REFERENCES candidate_items(id) ON DELETE CASCADE,
                    horizon TEXT NOT NULL CHECK (horizon IN ('1d', '5d', '20d', '60d')),
                    due_date TEXT NOT NULL,
                    baseline_price REAL NOT NULL,
                    realized_price REAL,
                    realized_trade_date TEXT,
                    return_pct REAL,
                    benchmark_code TEXT,
                    benchmark_baseline_price REAL,
                    benchmark_realized_price REAL,
                    benchmark_return_pct REAL,
                    relative_return_pct REAL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'verified', 'unavailable')),
                    measured_at TEXT,
                    source TEXT,
                    note TEXT,
                    UNIQUE(candidate_id, horizon)
                )""")
                legacy_columns = {row["name"] for row in connection.execute("PRAGMA table_info(candidate_performance_legacy)")}
                copy_columns = [name for name in ("id", "candidate_id", "horizon", "due_date", "baseline_price", "realized_price", "realized_trade_date", "return_pct", "benchmark_code", "benchmark_baseline_price", "benchmark_realized_price", "benchmark_return_pct", "relative_return_pct", "status", "measured_at", "source", "note") if name in legacy_columns]
                columns_sql = ", ".join(copy_columns)
                connection.execute(f"INSERT INTO candidate_performance ({columns_sql}) SELECT {columns_sql} FROM candidate_performance_legacy")
                connection.execute("DROP TABLE candidate_performance_legacy")
                connection.execute("CREATE INDEX IF NOT EXISTS ix_performance_due ON candidate_performance(status, due_date)")
            performance_columns = {row["name"] for row in connection.execute("PRAGMA table_info(candidate_performance)")}
            performance_migrations = {
                "realized_trade_date": "TEXT",
                "benchmark_code": "TEXT",
                "benchmark_baseline_price": "REAL",
                "benchmark_realized_price": "REAL",
                "benchmark_return_pct": "REAL",
                "relative_return_pct": "REAL",
            }
            for name, definition in performance_migrations.items():
                if name not in performance_columns:
                    connection.execute(f"ALTER TABLE candidate_performance ADD COLUMN {name} {definition}")
            analysis_columns = {row["name"] for row in connection.execute("PRAGMA table_info(analysis_reports)")}
            analysis_migrations = {
                "trade_date": "TEXT",
                "content_fingerprint": "TEXT",
                "snapshot_reason": "TEXT NOT NULL DEFAULT 'legacy_run'",
                "snapshot_note": "TEXT",
            }
            for name, definition in analysis_migrations.items():
                if name not in analysis_columns:
                    connection.execute(f"ALTER TABLE analysis_reports ADD COLUMN {name} {definition}")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_analysis_reports_fingerprint ON analysis_reports(content_fingerprint) WHERE content_fingerprint IS NOT NULL")
            outcome_columns = {row["name"] for row in connection.execute("PRAGMA table_info(industry_signal_outcomes)")}
            outcome_migrations = {
                "status": "TEXT NOT NULL DEFAULT 'pending'",
                "measured_at": "TEXT",
                "note": "TEXT",
                "execution_date": "TEXT",
            }
            for name, definition in outcome_migrations.items():
                if name not in outcome_columns:
                    connection.execute(f"ALTER TABLE industry_signal_outcomes ADD COLUMN {name} {definition}")
            signal_columns = {row["name"] for row in connection.execute("PRAGMA table_info(industry_signals)")}
            signal_migrations = {
                "signal_direction": "TEXT NOT NULL DEFAULT 'neutral'",
                "execution_date": "TEXT",
                "confirmation_days": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, definition in signal_migrations.items():
                if name not in signal_columns:
                    connection.execute(f"ALTER TABLE industry_signals ADD COLUMN {name} {definition}")

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
            for horizon, offset in (("1d", 1), ("5d", 5), ("20d", 20), ("60d", 60)):
                connection.execute(
                    """INSERT INTO candidate_performance
                    (candidate_id, horizon, due_date, baseline_price, status)
                    VALUES (?, ?, ?, ?, 'pending')""",
                    (candidate_id, horizon, self._business_day(selected_dt.date(), offset).isoformat(), request.score_input.price),
                )
        return self.get(candidate_id)

    def create_analysis_signal(self, report: AnalysisReport, planned_horizon: str = "20d", note: str | None = None) -> CandidateItem:
        if report.quote.get("price") is None or report.quote.get("price") <= 0:
            raise ValueError("当前分析没有可用的入选价格")
        trade_date = report.trade_date or self._analysis_trade_date(report)
        selected_dt = report.created_at
        fingerprint = self._analysis_signal_fingerprint(report, trade_date)
        action = report.advice.action
        reasons = list(dict.fromkeys(report.advice.triggered_conditions + report.advice.unmet_conditions))
        dimensions = [{"name": factor.key, "label": factor.label, "score": round(factor.score), "reasons": [factor.reason]} for factor in report.factors]
        grade = "S" if report.zhixing_index >= 80 else "A" if report.zhixing_index >= 65 else "B" if report.zhixing_index >= 50 else "C"
        context = {
            "signal_action": action,
            "trade_date": trade_date,
            "price": report.quote["price"],
            "triggered_conditions": report.advice.triggered_conditions,
            "invalidation_conditions": report.advice.invalidation_conditions,
            "data_completeness": report.data_completeness,
            "planned_horizon": planned_horizon,
            "algorithm_version": report.algorithm_version,
            "rule_fingerprint": report.rule_fingerprint,
            "asset_type": report.asset_type,
        }
        with self._connect() as connection:
            existing = connection.execute("SELECT id FROM candidate_items WHERE signal_fingerprint = ?", (fingerprint,)).fetchone()
            if existing is not None:
                return self.get(existing["id"])
            cursor = connection.execute(
                """INSERT INTO candidate_items (
                    stock_code, stock_name, selected_at, source_type, source_name,
                    strategy_id, strategy_version, rule_fingerprint, total_score, grade, reasons_json,
                    dimensions_json, score_input_json, selected_price, status, note,
                    price_zones_json, signal_context_json, signal_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report.stock_code, report.stock_name, selected_dt.isoformat(), "analysis-signal", "个股研究",
                    "analysis-signal", report.algorithm_version, report.rule_fingerprint, round(report.zhixing_index), grade,
                    json.dumps(reasons, ensure_ascii=False), json.dumps(dimensions, ensure_ascii=False), "null", report.quote["price"],
                    "new", note, PriceZones().model_dump_json(), json.dumps(context, ensure_ascii=False), fingerprint,
                ),
            )
            candidate_id = int(cursor.lastrowid)
            for horizon, offset in (("1d", 1), ("5d", 5), ("20d", 20), ("60d", 60)):
                connection.execute(
                    """INSERT INTO candidate_performance
                    (candidate_id, horizon, due_date, baseline_price, status)
                    VALUES (?, ?, ?, ?, 'pending')""",
                    (candidate_id, horizon, self._business_day(selected_dt.date(), offset).isoformat(), report.quote["price"]),
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
                 strategy_id, strategy_version, rule_fingerprint, rotation_pool_json,
                 scope, pool_name, pool_version, pool_component_count, transaction_date,
                 coverage_count, coverage_total, coverage_pct, data_status, degraded_reasons_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (result.started_at.isoformat(), result.completed_at.isoformat(), result.source,
                 result.total, result.succeeded, result.degraded, result.failed, result.scoreable,
                 first.strategy_id if first else "group-original", first.strategy_version if first else "unknown",
                 result.rule_fingerprint, json.dumps(result.rotation_pool_codes), result.scope,
                 result.pool_name, result.pool_version, result.pool_component_count,
                 result.transaction_date.isoformat() if result.transaction_date else None,
                 result.coverage_count, result.coverage_total, result.coverage_pct, result.data_status,
                 json.dumps(result.degraded_reasons, ensure_ascii=False)),
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
            scope=row["scope"], pool_name=row["pool_name"], pool_version=row["pool_version"],
            pool_component_count=row["pool_component_count"],
            transaction_date=date.fromisoformat(row["transaction_date"]) if row["transaction_date"] else None,
            coverage_pct=row["coverage_pct"], data_status=row["data_status"],
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
            sample_up_rate_pct=round(up_count / len(changes) * 100, 2) if changes else None,
            change_sample_count=len(changes),
            average_change_pct=round(sum(changes) / len(changes), 2) if changes else None,
            average_score=round(sum(score_values) / len(score_values), 2) if score_values else None,
            strategy_average_score=round(sum(score_values) / len(score_values), 2) if score_values else None,
            strategy_scoreable=len(score_values),
            rotation_pool_codes=json.loads(run["rotation_pool_json"]),
            top_gainers=sorted(items, key=lambda item: item.change_pct if item.change_pct is not None else -999, reverse=True)[:10],
            top_scores=sorted((item for item in items if item.score is not None), key=lambda item: item.score or -999, reverse=True)[:10],
            sectors=sector_rows[:12],
            scope=run["scope"], pool_name=run["pool_name"], pool_version=run["pool_version"],
            pool_component_count=run["pool_component_count"],
            transaction_date=date.fromisoformat(run["transaction_date"]) if run["transaction_date"] else None,
            scan_started_at=datetime.fromisoformat(run["started_at"]),
            scan_completed_at=datetime.fromisoformat(run["completed_at"]),
            coverage_count=run["coverage_count"], coverage_total=run["coverage_total"],
            coverage_pct=run["coverage_pct"], data_status=run["data_status"],
            degraded_reasons=json.loads(run["degraded_reasons_json"] or "[]"),
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

    def save_industry_snapshot(self, snapshot: IndustryRadarResponse) -> int:
        snapshot_date = snapshot.snapshot_at.date().isoformat()
        items = self._industry_items(snapshot)
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO industry_daily_snapshots
                (snapshot_date, snapshot_at, source, rule_version, data_status, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_date, source, rule_version) DO UPDATE SET
                  snapshot_at=excluded.snapshot_at, data_status=excluded.data_status,
                  payload_json=excluded.payload_json""",
                (snapshot_date, snapshot.snapshot_at.isoformat(), snapshot.source, snapshot.rule_version,
                 snapshot.data_status, snapshot.model_dump_json()),
            )
            for point in snapshot.benchmark_history:
                connection.execute(
                    """INSERT INTO industry_benchmark_daily(benchmark_code, trade_date, close)
                    VALUES ('sh000300', ?, ?)
                    ON CONFLICT(benchmark_code, trade_date) DO UPDATE SET close=excluded.close""",
                    (point.trade_date.isoformat(), point.close),
                )
            for item in items:
                item_date = item.trade_date.isoformat() if item.trade_date else snapshot_date
                connection.execute(
                    """INSERT INTO industry_master(industry_id, name, taxonomy, source, active, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    ON CONFLICT(industry_id) DO UPDATE SET name=excluded.name, taxonomy=excluded.taxonomy,
                      source=excluded.source, active=1, updated_at=excluded.updated_at""",
                    (item.industry_id, item.name, item.taxonomy, item.source, snapshot.snapshot_at.isoformat()),
                )
                for constituent in item.constituents:
                    connection.execute(
                        """INSERT OR REPLACE INTO industry_constituents
                        (industry_id, stock_code, stock_name, effective_from, effective_to, source)
                        VALUES (?, ?, ?, ?, NULL, ?)""",
                        (item.industry_id, constituent.code, constituent.name, item_date, item.source),
                    )
                for point in snapshot.history_series.get(item.industry_id, []):
                    connection.execute(
                        """INSERT INTO industry_daily
                        (industry_id, trade_date, close, return_5d, return_20d, return_60d,
                         relative_return_20d, breadth_ma20, breadth_ma60, advance_ratio,
                         new_high_ratio, volume_ratio, coverage_pct, payload_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(industry_id, trade_date) DO UPDATE SET
                          close=excluded.close, breadth_ma20=excluded.breadth_ma20,
                          breadth_ma60=excluded.breadth_ma60, advance_ratio=excluded.advance_ratio,
                          new_high_ratio=excluded.new_high_ratio, volume_ratio=excluded.volume_ratio,
                          coverage_pct=excluded.coverage_pct, payload_json=excluded.payload_json""",
                        (item.industry_id, point.trade_date.isoformat(), point.close, point.return_5d_pct,
                         point.return_20d_pct, point.return_60d_pct, point.relative_return_20d_pct,
                         point.breadth_ma20_pct, point.breadth_ma60_pct, point.advance_ratio_pct,
                         point.new_high_ratio_pct, point.volume_ratio, point.coverage_pct,
                         point.model_dump_json()),
                    )
                connection.execute(
                    """INSERT INTO industry_daily
                    (industry_id, trade_date, close, return_5d, return_20d, return_60d,
                     relative_return_20d, breadth_ma20, breadth_ma60, advance_ratio,
                     new_high_ratio, volume_ratio, coverage_pct, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(industry_id, trade_date) DO UPDATE SET
                      close=excluded.close, return_5d=excluded.return_5d,
                      return_20d=excluded.return_20d, return_60d=excluded.return_60d,
                      relative_return_20d=excluded.relative_return_20d,
                      breadth_ma20=excluded.breadth_ma20, breadth_ma60=excluded.breadth_ma60,
                      advance_ratio=excluded.advance_ratio, new_high_ratio=excluded.new_high_ratio,
                      volume_ratio=excluded.volume_ratio, coverage_pct=excluded.coverage_pct,
                      payload_json=excluded.payload_json""",
                    (item.industry_id, item_date, item.proxy_close, item.return_5d_pct,
                     item.return_20d_pct, item.return_60d_pct, item.relative_return_20d_pct,
                     item.breadth_ma20_pct, item.breadth_ma60_pct, item.advance_ratio_pct,
                     item.new_high_ratio_pct, item.volume_ratio, item.coverage_pct, item.model_dump_json()),
                )
                signal_date = item.stage_confirmed_at.isoformat() if item.stage_confirmed_at else None
                signal_exists = False
                if signal_date:
                    signal_exists = connection.execute(
                        "SELECT 1 FROM industry_signals WHERE industry_id=? AND trade_date=? AND rule_version=?",
                        (item.industry_id, signal_date, snapshot.rule_version),
                    ).fetchone() is not None
                if item.stage_changed or (signal_date and not signal_exists):
                    connection.execute(
                        """INSERT INTO industry_signals
                        (industry_id, trade_date, stage, score, rule_version, evidence_json, risk_json,
                         signal_direction, execution_date, confirmation_days)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(industry_id, trade_date, rule_version) DO UPDATE SET
                          stage=excluded.stage, score=excluded.score, evidence_json=excluded.evidence_json,
                          risk_json=excluded.risk_json, signal_direction=excluded.signal_direction,
                          execution_date=excluded.execution_date, confirmation_days=excluded.confirmation_days""",
                        (item.industry_id, signal_date or item_date, item.stage, item.score, snapshot.rule_version,
                         json.dumps(item.evidence, ensure_ascii=False), json.dumps(item.risks, ensure_ascii=False),
                         item.signal_direction, item.execution_date.isoformat() if item.execution_date else None,
                         item.stage_confirmation_days),
                    )
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM industry_daily_snapshots WHERE source = ? AND rule_version = ?",
                (snapshot.source, snapshot.rule_version),
            ).fetchone()
        return int(row["count"])

    @staticmethod
    def _industry_items(snapshot: IndustryRadarResponse) -> list[IndustryRadarItem]:
        seen: set[str] = set()
        items: list[IndustryRadarItem] = []
        for group in (snapshot.ranking, snapshot.building, snapshot.confirmed, snapshot.overheated, snapshot.other):
            for item in group:
                if item.industry_id not in seen:
                    seen.add(item.industry_id)
                    items.append(item)
        return items

    def latest_industry_snapshot(self, source: str = "sina-industry-radar") -> IndustryRadarResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM industry_daily_snapshots WHERE source = ? ORDER BY snapshot_date DESC LIMIT 1",
                (source,),
            ).fetchone()
        return IndustryRadarResponse.model_validate_json(row["payload_json"]) if row else None

    def list_industry_history(self, source: str = "sina-industry-radar", limit: int = 90) -> list[IndustryRadarResponse]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM industry_daily_snapshots WHERE source = ? ORDER BY snapshot_date DESC LIMIT ?",
                (source, limit),
            ).fetchall()
        return [IndustryRadarResponse.model_validate_json(row["payload_json"]) for row in reversed(rows)]

    def industry_detail(self, industry_key: str, limit: int = 120) -> IndustryRadarDetailResponse | None:
        snapshots = self.list_industry_history(limit=limit)
        current: IndustryRadarItem | None = None
        for snapshot in reversed(snapshots):
            for item in self._industry_items(snapshot):
                if item.industry_id == industry_key:
                    current = item
                    break
            if current:
                break
        if current is None:
            return None
        history: list[IndustryHistoryPoint] = []
        stage_timeline: list[dict[str, str | float | None]] = []
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT d.trade_date, d.close, d.return_5d, d.return_20d, d.return_60d,
                   d.relative_return_20d, d.breadth_ma20, d.breadth_ma60, d.advance_ratio,
                   d.new_high_ratio, d.volume_ratio, d.coverage_pct, d.payload_json, s.stage, s.score
                   FROM industry_daily d LEFT JOIN industry_signals s
                   ON s.industry_id=d.industry_id AND s.trade_date=d.trade_date
                   WHERE d.industry_id=? ORDER BY d.trade_date DESC LIMIT ?""",
                (industry_key, limit),
            ).fetchall()
        for row in reversed(rows):
            payload = json.loads(row["payload_json"] or "{}")
            history.append(IndustryHistoryPoint(
                trade_date=date.fromisoformat(row["trade_date"]), close=row["close"],
                return_5d_pct=row["return_5d"], return_20d_pct=row["return_20d"],
                return_60d_pct=row["return_60d"], relative_return_20d_pct=row["relative_return_20d"],
                breadth_ma20_pct=row["breadth_ma20"], breadth_ma60_pct=row["breadth_ma60"],
                advance_ratio_pct=row["advance_ratio"], new_high_ratio_pct=row["new_high_ratio"],
                volume_ratio=row["volume_ratio"], coverage_pct=row["coverage_pct"],
                breadth_source=payload.get("breadth_source"),
            ))
            if row["stage"]:
                stage_timeline.append({"trade_date": row["trade_date"], "stage": row["stage"], "score": row["score"]})
        return IndustryRadarDetailResponse(
            item=current, history=history, stage_timeline=stage_timeline,
            constituent_groups=self._industry_constituent_groups(current),
        )

    @staticmethod
    def _industry_constituent_groups(item: IndustryRadarItem) -> dict[str, list[IndustryConstituent]]:
        """Partition constituents using persisted, inspectable evidence fields."""
        groups: dict[str, list[IndustryConstituent]] = {
            "领涨核心": [], "低位改善": [], "突破确认": [], "内部拖累": [],
        }
        for stock in item.constituents:
            relative = stock.relative_return_20d_pct
            if stock.history_days < 60 or relative is None:
                continue
            if stock.breakout_confirmed and relative >= 0:
                groups["突破确认"].append(stock)
            elif relative >= 1 and stock.ma20_above:
                groups["领涨核心"].append(stock)
            elif (stock.return_20d_pct is not None and stock.return_20d_pct < 0 and (stock.return_5d_pct or 0) > 0):
                groups["低位改善"].append(stock)
            elif relative <= -1 or stock.ma20_above is False:
                groups["内部拖累"].append(stock)
        for values in groups.values():
            values.sort(key=lambda stock: stock.relative_return_20d_pct or -999, reverse=True)
        return groups

    def industry_context_for_stock(
        self, stock_code: str, *, stock_return_20d_pct: float | None = None,
        stock_change_pct: float | None = None, sector_name: str | None = None,
    ) -> dict[str, object]:
        """Return the latest radar context without making an upstream request."""
        snapshot = self.latest_industry_snapshot()
        unavailable: dict[str, object] = {
            "status": "unavailable", "source": "sqlite-industry-radar",
            "stock_code": stock_code, "reason": "尚无包含该股票的板块快照",
        }
        if snapshot is None:
            return unavailable
        normalized = stock_code.lower().strip()
        items = self._industry_items(snapshot)
        item = next((candidate for candidate in items if any(member.code.lower().strip() == normalized for member in candidate.constituents)), None)
        if item is None and sector_name:
            item = next((candidate for candidate in items if candidate.name == sector_name), None)
        if item is None:
            return unavailable | {"trade_date": snapshot.last_success_trade_date, "reason": "最新板块成分映射未覆盖该股票"}
        industry_items = [candidate for candidate in items if candidate.taxonomy == "industry" and candidate.return_20d_pct is not None]
        industry_items.sort(key=lambda candidate: candidate.return_20d_pct or -999, reverse=True)
        rank = next((index for index, candidate in enumerate(industry_items, start=1) if candidate.industry_id == item.industry_id), None)
        member = next((candidate for candidate in item.constituents if candidate.code.lower().strip() == normalized), None)
        member_return = stock_return_20d_pct if stock_return_20d_pct is not None else (member.return_20d_pct if member else None)
        sector_return = item.return_20d_pct
        relative = member_return - sector_return if member_return is not None and sector_return is not None else None
        if relative is None and stock_change_pct is not None and item.change_pct is not None:
            relative = stock_change_pct - item.change_pct
        role = "领涨" if relative is not None and relative >= 1 else "拖累" if relative is not None and relative <= -1 else "跟随"
        return {
            "status": "ok" if item.history_days >= 120 else "degraded", "source": "sqlite-industry-radar",
            "stock_code": stock_code, "trade_date": item.trade_date or snapshot.last_success_trade_date,
            "industry_id": item.industry_id, "industry_name": item.name, "taxonomy": item.taxonomy,
            "stage": item.stage, "stage_candidate": item.stage_candidate,
            "stage_confirmation_days": item.stage_confirmation_days, "stage_confirmed_at": item.stage_confirmed_at,
            "index_source": item.index_source, "breadth_source": item.breadth_source,
            "history_days": item.history_days, "rank": rank, "total": len(industry_items),
            "sector_return_20d_pct": sector_return, "stock_return_20d_pct": member_return,
            "relative_return_20d_pct": round(relative, 2) if relative is not None else None,
            "role": role, "evidence": item.evidence,
        }

    def add_industry_watch(self, industry_id: str) -> IndustryWatchItem:
        snapshot = self.latest_industry_snapshot()
        item = next((item for item in self._industry_items(snapshot) if item.industry_id == industry_id), None) if snapshot else None
        if item is None:
            raise KeyError(industry_id)
        created_at = datetime.now(timezone.utc)
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO industry_watchlist(industry_id, enabled, created_at) VALUES (?, 1, ?)
                ON CONFLICT(industry_id) DO UPDATE SET enabled=1""",
                (industry_id, created_at.isoformat()),
            )
            row = connection.execute("SELECT * FROM industry_watchlist WHERE industry_id=?", (industry_id,)).fetchone()
        return IndustryWatchItem(industry_id=industry_id, name=item.name, taxonomy=item.taxonomy, enabled=bool(row["enabled"]), created_at=datetime.fromisoformat(row["created_at"]))

    def list_industry_watches(self) -> list[IndustryWatchItem]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT w.industry_id, m.name, m.taxonomy, w.enabled, w.created_at
                FROM industry_watchlist w JOIN industry_master m ON m.industry_id=w.industry_id
                ORDER BY m.name""",
            ).fetchall()
        return [IndustryWatchItem(industry_id=row["industry_id"], name=row["name"], taxonomy=row["taxonomy"], enabled=bool(row["enabled"]), created_at=datetime.fromisoformat(row["created_at"])) for row in rows]

    def delete_industry_watch(self, industry_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM industry_watchlist WHERE industry_id=?", (industry_id,))
        return cursor.rowcount > 0

    def industry_alerts(self) -> list[IndustryAlert]:
        snapshot = self.latest_industry_snapshot()
        if snapshot is None:
            return []
        with self._connect() as connection:
            watched = {row["industry_id"] for row in connection.execute("SELECT industry_id FROM industry_watchlist WHERE enabled=1")}
        return [IndustryAlert(
            industry_id=item.industry_id, name=item.name, stage=item.stage,
            direction=item.signal_direction, trade_date=item.trade_date,
            evidence=item.evidence,
        ) for item in self._industry_items(snapshot) if item.industry_id in watched and item.stage_changed]

    def backup_bytes(self) -> bytes:
        with self._connect() as source:
            target = sqlite3.connect(":memory:")
            try:
                source.backup(target)
                return target.serialize()
            finally:
                target.close()

    def industry_export_rows(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT d.trade_date, d.industry_id, m.name, m.taxonomy, d.close,
                   d.return_5d, d.return_20d, d.return_60d, d.relative_return_20d,
                   d.breadth_ma20, d.breadth_ma60, d.advance_ratio, d.new_high_ratio,
                   d.volume_ratio, d.coverage_pct, s.stage, s.score, s.signal_direction,
                   s.execution_date, s.confirmation_days
                   FROM industry_daily d JOIN industry_master m ON m.industry_id=d.industry_id
                   LEFT JOIN industry_signals s ON s.industry_id=d.industry_id AND s.trade_date=d.trade_date
                   ORDER BY d.trade_date, m.name""",
            ).fetchall()
        return [dict(row) for row in rows]

    def verify_industry_signals(self, as_of: date) -> IndustrySignalVerificationResponse:
        horizons = {"1d": 1, "5d": 5, "20d": 20, "60d": 60}
        measured_at = datetime.now(timezone.utc).isoformat()
        outcomes: list[IndustrySignalOutcome] = []
        with self._connect() as connection:
            signals = connection.execute(
                """SELECT id, industry_id, trade_date, signal_direction FROM industry_signals
                WHERE stage != '数据不足' AND confirmation_days >= 2 ORDER BY trade_date, id""",
            ).fetchall()
            benchmark_rows = connection.execute(
                "SELECT trade_date, close FROM industry_benchmark_daily WHERE benchmark_code='sh000300'",
            ).fetchall()
            benchmark = {row["trade_date"]: float(row["close"]) for row in benchmark_rows if row["close"]}
            daily_cache: dict[str, list[sqlite3.Row]] = {}
            for signal in signals:
                industry_id = signal["industry_id"]
                if industry_id not in daily_cache:
                    daily_cache[industry_id] = connection.execute(
                        "SELECT trade_date, close FROM industry_daily WHERE industry_id=? ORDER BY trade_date",
                        (industry_id,),
                    ).fetchall()
                daily = daily_cache[industry_id]
                dates = [row["trade_date"] for row in daily]
                try:
                    signal_index = dates.index(signal["trade_date"])
                except ValueError:
                    continue
                execution_index = signal_index + 1
                if execution_index >= len(daily):
                    continue
                execution_date = daily[execution_index]["trade_date"]
                baseline = daily[execution_index]["close"]
                if baseline is None or baseline <= 0:
                    continue
                direction = signal["signal_direction"] or "neutral"
                for horizon, offset in horizons.items():
                    target_index = execution_index + offset - 1
                    status = "pending"
                    note = "等待目标交易日后的板块快照"
                    return_pct = benchmark_return = relative_return = mfe = mae = None
                    if target_index < len(daily) and daily[target_index]["trade_date"] <= as_of.isoformat():
                        target_close = daily[target_index]["close"]
                        path = [row["close"] for row in daily[execution_index:target_index + 1] if row["close"]]
                        if target_close and path:
                            return_pct = round((target_close / baseline - 1) * 100, 4)
                            path_returns = [(close / baseline - 1) * 100 for close in path]
                            favorable = path_returns if direction != "weakening" else [-value for value in path_returns]
                            mfe = round(max(favorable), 4)
                            mae = round(min(favorable), 4)
                            benchmark_base = benchmark.get(execution_date)
                            benchmark_target = benchmark.get(daily[target_index]["trade_date"])
                            if benchmark_base and benchmark_target:
                                benchmark_return = round((benchmark_target / benchmark_base - 1) * 100, 4)
                                relative_return = round(return_pct - benchmark_return, 4)
                            status, note = "verified", None
                    elif as_of > date.fromisoformat(signal["trade_date"]) + timedelta(days=offset + 10):
                        status, note = "unavailable", "目标交易日后仍无足够板块历史快照"
                    connection.execute(
                        """INSERT INTO industry_signal_outcomes
                        (signal_id, horizon, return_pct, benchmark_return_pct, relative_return_pct,
                         mfe_pct, mae_pct, execution_date, status, measured_at, note)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(signal_id, horizon) DO UPDATE SET
                          return_pct=excluded.return_pct, benchmark_return_pct=excluded.benchmark_return_pct,
                          relative_return_pct=excluded.relative_return_pct, mfe_pct=excluded.mfe_pct,
                         mae_pct=excluded.mae_pct, execution_date=excluded.execution_date,
                         status=excluded.status,
                          measured_at=excluded.measured_at, note=excluded.note""",
                        (signal["id"], horizon, return_pct, benchmark_return, relative_return,
                         mfe, mae, execution_date, status, measured_at if status != "pending" else None, note),
                    )
                    outcomes.append(IndustrySignalOutcome(
                        signal_id=signal["id"], industry_id=industry_id,
                        signal_date=date.fromisoformat(signal["trade_date"]), execution_date=date.fromisoformat(execution_date),
                        signal_direction=direction, horizon=horizon,
                        return_pct=return_pct, benchmark_return_pct=benchmark_return,
                        relative_return_pct=relative_return, mfe_pct=mfe, mae_pct=mae,
                        status=status, measured_at=datetime.fromisoformat(measured_at) if status != "pending" else None,
                        note=note,
                    ))

        summaries: list[PerformanceHorizonSummary] = []
        direction_summary: list[dict[str, object]] = []
        for horizon in horizons:
            sample = [item for item in outcomes if item.horizon == horizon]
            verified = [item for item in sample if item.status == "verified" and item.return_pct is not None]
            returns = [item.return_pct for item in verified if item.return_pct is not None]
            relatives = [item.relative_return_pct for item in verified if item.relative_return_pct is not None]
            directional_returns = [value if item.signal_direction != "weakening" else -value for item, value in ((item, item.return_pct) for item in verified) if value is not None]
            summaries.append(PerformanceHorizonSummary(
                horizon=horizon, samples=len(sample), verified=len(verified),
                wins=sum(value > 0 for value in directional_returns),
                win_rate_pct=round(sum(value > 0 for value in directional_returns) / len(directional_returns) * 100, 2) if directional_returns else None,
                average_return_pct=round(sum(returns) / len(returns), 4) if returns else None,
                median_return_pct=round(median(returns), 4) if returns else None,
                benchmark_code="sh000300" if relatives else None,
                average_relative_return_pct=round(sum(relatives) / len(relatives), 4) if relatives else None,
            ))
            for direction in ("improving", "weakening", "neutral"):
                directional = [item for item in verified if item.signal_direction == direction]
                favorable = [item.return_pct if direction != "weakening" else -item.return_pct for item in directional if item.return_pct is not None]
                direction_summary.append({
                    "horizon": horizon, "direction": direction, "samples": len(directional),
                    "verified": len(favorable), "wins": sum(value > 0 for value in favorable),
                    "win_rate_pct": round(sum(value > 0 for value in favorable) / len(favorable) * 100, 2) if favorable else None,
                    "average_mfe_pct": round(sum(item.mfe_pct for item in directional if item.mfe_pct is not None) / len([item for item in directional if item.mfe_pct is not None]), 4) if any(item.mfe_pct is not None for item in directional) else None,
                    "average_mae_pct": round(sum(item.mae_pct for item in directional if item.mae_pct is not None) / len([item for item in directional if item.mae_pct is not None]), 4) if any(item.mae_pct is not None for item in directional) else None,
                })
        counts = {status: sum(item.status == status for item in outcomes) for status in ("verified", "pending", "unavailable")}
        return IndustrySignalVerificationResponse(
            as_of=as_of, processed=len(outcomes), verified=counts["verified"],
            pending=counts["pending"], unavailable=counts["unavailable"],
            outcomes=outcomes, horizon_summary=summaries, direction_summary=direction_summary,
        )

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
                candidate_row = connection.execute(
                    "SELECT stock_code, selected_at FROM candidate_items WHERE id = ?",
                    (row["candidate_id"],),
                ).fetchone()
                quote_row = connection.execute(
                    """SELECT payload_json FROM quote_snapshots
                    WHERE stock_code = ? AND date(trade_at) >= ? AND date(trade_at) <= ?
                    ORDER BY trade_at LIMIT 1""",
                    (candidate_row["stock_code"], row["due_date"], as_of.isoformat()),
                ).fetchone()
                status, realized, return_pct, source, note = "pending", None, None, None, None
                realized_trade_date = None
                benchmark_code, benchmark_baseline, benchmark_realized = "sh000300", None, None
                benchmark_return, relative_return = None, None
                if quote_row:
                    quote = QuoteSnapshot.model_validate_json(quote_row["payload_json"])
                    if quote.price and quote.price > 0:
                        realized = quote.price
                        return_pct = round((realized - row["baseline_price"]) / row["baseline_price"] * 100, 4)
                        realized_trade_date = quote.trade_at.date() if quote.trade_at else None
                        benchmark_baseline_row = connection.execute(
                            """SELECT payload_json FROM quote_snapshots
                            WHERE stock_code = ? AND datetime(trade_at) <= datetime(?)
                            ORDER BY trade_at DESC LIMIT 1""",
                            (benchmark_code, candidate_row["selected_at"]),
                        ).fetchone()
                        benchmark_realized_row = connection.execute(
                            """SELECT payload_json FROM quote_snapshots
                            WHERE stock_code = ? AND date(trade_at) >= ? AND date(trade_at) <= ?
                            ORDER BY trade_at LIMIT 1""",
                            (benchmark_code, realized_trade_date.isoformat(), as_of.isoformat()),
                        ).fetchone() if realized_trade_date else None
                        if benchmark_baseline_row and benchmark_realized_row:
                            benchmark_baseline_quote = QuoteSnapshot.model_validate_json(benchmark_baseline_row["payload_json"])
                            benchmark_realized_quote = QuoteSnapshot.model_validate_json(benchmark_realized_row["payload_json"])
                            if benchmark_baseline_quote.price and benchmark_baseline_quote.price > 0 and benchmark_realized_quote.price and benchmark_realized_quote.price > 0:
                                benchmark_baseline = benchmark_baseline_quote.price
                                benchmark_realized = benchmark_realized_quote.price
                                benchmark_return = round((benchmark_realized - benchmark_baseline) / benchmark_baseline * 100, 4)
                                relative_return = round(return_pct - benchmark_return, 4)
                        status, source = "verified", quote.source
                elif as_of > date.fromisoformat(row["due_date"]) + timedelta(days=10):
                    status, note = "unavailable", "目标交易日后仍无有效行情快照"
                if status != "pending":
                    connection.execute(
                        """UPDATE candidate_performance SET realized_price=?, realized_trade_date=?, return_pct=?,
                        benchmark_code=?, benchmark_baseline_price=?, benchmark_realized_price=?, benchmark_return_pct=?,
                        relative_return_pct=?, status=?, measured_at=?, source=?, note=? WHERE id=?""",
                        (realized, realized_trade_date.isoformat() if realized_trade_date else None, return_pct,
                         benchmark_code if benchmark_return is not None else None, benchmark_baseline, benchmark_realized,
                         benchmark_return, relative_return, status, now, source, note, row["id"]),
                    )
                changed.append(PerformanceOutcome(
                    candidate_id=row["candidate_id"], horizon=row["horizon"], due_date=date.fromisoformat(row["due_date"]),
                    baseline_price=row["baseline_price"], realized_price=realized,
                    realized_trade_date=realized_trade_date, return_pct=return_pct,
                    benchmark_code=benchmark_code if benchmark_return is not None else None,
                    benchmark_baseline_price=benchmark_baseline, benchmark_realized_price=benchmark_realized,
                    benchmark_return_pct=benchmark_return, relative_return_pct=relative_return,
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
                ORDER BY CASE horizon WHEN '1d' THEN 1 WHEN '5d' THEN 5 WHEN '20d' THEN 20 ELSE 60 END"""
            ).fetchall()
            return_rows = connection.execute(
                "SELECT horizon, return_pct, relative_return_pct FROM candidate_performance WHERE status = 'verified'"
            ).fetchall()
        returns_by_horizon: dict[str, list[float]] = {}
        relative_by_horizon: dict[str, list[float]] = {}
        for row in return_rows:
            if row["return_pct"] is not None:
                returns_by_horizon.setdefault(row["horizon"], []).append(float(row["return_pct"]))
            if row["relative_return_pct"] is not None:
                relative_by_horizon.setdefault(row["horizon"], []).append(float(row["relative_return_pct"]))
        horizon_summary = [PerformanceHorizonSummary(
            horizon=row["horizon"], samples=row["samples"], verified=row["verified"] or 0, wins=row["wins"] or 0,
            win_rate_pct=round((row["wins"] or 0) / row["verified"] * 100, 2) if row["verified"] else None,
            average_return_pct=round(row["average_return"], 4) if row["average_return"] is not None else None,
            median_return_pct=round(median(returns_by_horizon[row["horizon"]]), 4) if returns_by_horizon.get(row["horizon"]) else None,
            benchmark_code="sh000300" if relative_by_horizon.get(row["horizon"]) else None,
            average_relative_return_pct=round(sum(relative_by_horizon[row["horizon"]]) / len(relative_by_horizon[row["horizon"]]), 4) if relative_by_horizon.get(row["horizon"]) else None,
        ) for row in horizon_rows]
        return {
            "processed": sum(counts.values()), "verified": counts.get("verified", 0),
            "pending": counts.get("pending", 0), "unavailable": counts.get("unavailable", 0),
            "horizon_summary": horizon_summary,
        }

    def list_performance(self, candidate_id: int) -> list[PerformanceOutcome]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM candidate_performance WHERE candidate_id = ? ORDER BY CASE horizon WHEN '1d' THEN 1 WHEN '5d' THEN 5 WHEN '20d' THEN 20 ELSE 60 END",
                (candidate_id,),
            ).fetchall()
        return [PerformanceOutcome(
            candidate_id=row["candidate_id"], horizon=row["horizon"], due_date=date.fromisoformat(row["due_date"]),
            baseline_price=row["baseline_price"], realized_price=row["realized_price"],
            realized_trade_date=date.fromisoformat(row["realized_trade_date"]) if row["realized_trade_date"] else None,
            return_pct=row["return_pct"], benchmark_code=row["benchmark_code"],
            benchmark_baseline_price=row["benchmark_baseline_price"], benchmark_realized_price=row["benchmark_realized_price"],
            benchmark_return_pct=row["benchmark_return_pct"], relative_return_pct=row["relative_return_pct"],
            status=row["status"], measured_at=datetime.fromisoformat(row["measured_at"]) if row["measured_at"] else None,
            source=row["source"], note=row["note"],
        ) for row in rows]

    def save_analysis(self, report: AnalysisReport) -> AnalysisReport:
        """Compatibility wrapper; new callers should use save_snapshot."""
        return self.save_snapshot(report)[0]

    def save_snapshot(self, report: AnalysisReport, reason: str = "manual", note: str | None = None) -> tuple[AnalysisReport, bool]:
        trade_date = self._analysis_trade_date(report)
        fingerprint = self._analysis_fingerprint(report, trade_date)
        stored = report.model_copy(update={
            "report_id": None, "trade_date": trade_date, "snapshot_reason": reason, "snapshot_note": note,
            "content_fingerprint": fingerprint,
        })
        payload = stored.model_dump_json()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id, payload_json, trade_date, snapshot_reason, snapshot_note, content_fingerprint FROM analysis_reports WHERE content_fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if existing is not None:
                return self._analysis_model(existing), False
            try:
                cursor = connection.execute(
                    """INSERT INTO analysis_reports
                    (created_at, stock_code, stock_name, sector, source, status, payload_json,
                     trade_date, content_fingerprint, snapshot_reason, snapshot_note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (report.created_at.isoformat(), report.stock_code, report.stock_name, report.sector,
                     report.source, report.status, payload, trade_date, fingerprint, reason, note),
                )
            except sqlite3.IntegrityError:
                existing = connection.execute(
                    "SELECT id, payload_json, trade_date, snapshot_reason, snapshot_note, content_fingerprint FROM analysis_reports WHERE content_fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
                if existing is not None:
                    return self._analysis_model(existing), False
                raise
            report_id = int(cursor.lastrowid)
            for fact_type, value in (("quote", report.quote), ("technical", report.technical.model_dump()),
                                     ("rocket", stored.rocket.model_dump()), ("advice", stored.advice.model_dump()),
                                     ("fund_flow", stored.fund_flow), ("finance", stored.finance),
                                     ("industry", stored.industry), ("news", stored.news),
                                     ("bars", [bar.model_dump() for bar in stored.bars]),
                                     ("weekly_bars", [bar.model_dump() for bar in stored.weekly_bars])):
                source = value.get("source", stored.source) if isinstance(value, dict) else stored.source
                fetched_at = value.get("fetched_at", stored.created_at.isoformat()) if isinstance(value, dict) else stored.created_at.isoformat()
                connection.execute(
                    """INSERT INTO analysis_facts
                    (report_id, fact_type, source, fetched_at, payload_json)
                    VALUES (?, ?, ?, ?, ?)""",
                    (report_id, fact_type, source, str(fetched_at),
                     json.dumps(value, ensure_ascii=False, default=str)),
                )
        return stored.model_copy(update={"report_id": report_id}), True

    def get_analysis(self, report_id: int) -> AnalysisReport:
        with self._connect() as connection:
            row = connection.execute("SELECT id, payload_json, trade_date, snapshot_reason, snapshot_note, content_fingerprint FROM analysis_reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            raise KeyError(report_id)
        return self._analysis_model(row)

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
        params: list[object] = [stock_code] if stock_code else []
        if stock_code:
            query = "SELECT id, payload_json, trade_date, snapshot_reason, snapshot_note, content_fingerprint FROM analysis_reports WHERE stock_code = ? ORDER BY created_at DESC, id DESC LIMIT ?"
        else:
            query = """SELECT id, payload_json, trade_date, snapshot_reason, snapshot_note, content_fingerprint
                       FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY created_at DESC, id DESC) AS latest_rank
                             FROM analysis_reports)
                       WHERE latest_rank = 1 ORDER BY created_at DESC, id DESC LIMIT ?"""
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._analysis_model(row) for row in rows]

    @staticmethod
    def _analysis_model(row: sqlite3.Row) -> AnalysisReport:
        return AnalysisReport.model_validate_json(row["payload_json"]).model_copy(update={
            "report_id": row["id"], "trade_date": row["trade_date"], "snapshot_reason": row["snapshot_reason"],
            "snapshot_note": row["snapshot_note"], "content_fingerprint": row["content_fingerprint"],
        })

    @staticmethod
    def _analysis_trade_date(report: AnalysisReport) -> str | None:
        raw = report.quote.get("trade_at") or report.technical.latest_trade_date
        return str(raw)[:10] if raw else None

    @classmethod
    def _analysis_fingerprint(cls, report: AnalysisReport, trade_date: str | None) -> str:
        request_input = report.facts.get("input", {}) if isinstance(report.facts, dict) else {}
        position_cost = request_input.get("position_cost")
        context = {
            "is_holding": bool(request_input.get("is_holding", False)),
            "position_cost": round(float(position_cost), 4) if position_cost is not None else None,
        }
        conclusion = {
            "action": report.advice.action,
            "category": report.advice.category,
            "position": report.diagnosis.position,
            "level": report.zhixing_level,
            "score_bucket": round(report.zhixing_index / 5) * 5,
            "invalidation": sorted(report.advice.invalidation_conditions),
        }
        payload = {
            "stock_code": report.stock_code, "trade_date": trade_date,
            "algorithm_version": report.algorithm_version, "rule_fingerprint": report.rule_fingerprint,
            "context": context, "conclusion": conclusion,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def _analysis_signal_fingerprint(cls, report: AnalysisReport, trade_date: str | None) -> str:
        payload = {
            "stock_code": report.stock_code,
            "trade_date": trade_date,
            "algorithm_version": report.algorithm_version,
            "rule_fingerprint": report.rule_fingerprint,
            "price": round(float(report.quote["price"]), 4) if report.quote.get("price") else None,
            "action": report.advice.action,
            "category": report.advice.category,
            "score_bucket": round(report.zhixing_index / 5) * 5,
            "invalidation": sorted(report.advice.invalidation_conditions),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

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
            signal_context=json.loads(row["signal_context_json"] or "{}"),
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
