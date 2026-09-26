from __future__ import annotations

import json
import csv
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.database import CandidateRepository
from app.analysis.models import AnalysisReport, AnalysisRequest, AnalysisSignalCandidateRequest, AnalysisSnapshotRequest, AnalysisSnapshotResponse, CompareRequest, CompareResponse
from app.analysis.service import IndividualAnalysisService
from app.market.scanner import MarketScanner, StockPool
from app.market.akshare import FallbackHistoryProvider, FallbackQuoteProvider
from app.market.health import DataSourceHealthService
from app.market.tencent import TencentQuoteProvider
from app.market.tencent_daily import TencentDailyProvider
from app.market.all_a_snapshot import AllAMarketSnapshotProvider
from app.market.industry_radar import IndustryRadarProvider
from app.market.constituent_history import TencentConstituentHistoryProvider
from app.market.industry_scheduler import IndustryRadarScheduler
from app.models import (
    CandidateBatchRequest, CandidateBatchResponse, CandidateCreate, CandidateItem, CandidateList, CandidateUpdate,
    AllAMarketSnapshot, DataSourceHealthResponse, IndustryAlert, IndustryRadarResponse, IndustryRadarDetailResponse, IndustrySignalVerificationResponse, IndustryTaskStatus, IndustryWatchCreate, IndustryWatchItem, MarketReviewResponse, MarketReviewRun, MarketScanRequest, MarketScanResponse, PerformanceVerificationResponse, PoolResponse, QuoteSnapshot,
    ScoreInput, ScoreResult, StockSearchResult, WatchlistCreate, WatchlistItem,
)
from app.scoring import StrategyEngine
from app.settings import Settings, get_settings
from app.training.router import router as training_router
from app.training.service import TrainingService
from app.data_lake.reader import LakeReader
from app.data_lake.history import DailyHistoryRouter, LakeTrainingProvider
from app.data_lake.jobs import LakeJobs
from app.data_lake.router import router as lake_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.engine = StrategyEngine(settings.strategy_path)
    app.state.candidates = CandidateRepository(settings.database_path)
    app.state.pool = StockPool(settings.stock_pool_path)
    app.state.lake = LakeReader(settings.lake_root)
    app.state.lake_jobs = LakeJobs(settings.lake_root, settings.database_path)
    app.state.daily_history = DailyHistoryRouter(app.state.lake, cache_path=settings.database_path)
    app.state.training = TrainingService(settings.database_path, app.state.pool, app.state.candidates.list_watchlist,
                                        provider=LakeTrainingProvider(app.state.daily_history))
    quote_provider = FallbackQuoteProvider(TencentQuoteProvider())
    history_provider = FallbackHistoryProvider(TencentDailyProvider(bars_provider=app.state.daily_history.fetch_bars))
    app.state.market_scanner = MarketScanner(
        pool=app.state.pool,
        provider=quote_provider,
        engine=app.state.engine,
        history_provider=history_provider,
    )
    app.state.analysis_service = IndividualAnalysisService(app.state.pool, quote_provider, cache=app.state.candidates,
                                                          bars_provider=app.state.daily_history.fetch_bars, lake=app.state.lake)
    app.state.all_a_snapshot = AllAMarketSnapshotProvider()
    app.state.industry_history = TencentConstituentHistoryProvider(days=150, cache_path=settings.database_path,
                                                                 bars_provider=app.state.daily_history.fetch_bars)
    app.state.industry_radar = IndustryRadarProvider(history_provider=app.state.industry_history)
    app.state.industry_scheduler = IndustryRadarScheduler(
        lambda: _refresh_industry_snapshot(app.state.candidates, app.state.industry_radar, include_history=True, require_complete=True),
        state_path=settings.database_path,
    )
    app.state.industry_scheduler.start()
    app.state.lake_jobs.begin_schedule()
    try:
        yield
    finally:
        app.state.industry_scheduler.stop()
        app.state.lake_jobs.stop()


app = FastAPI(
    title="知行股研本地 API",
    version="0.1.0",
    description="仅用于本地股票研究；不含交易接口。",
    lifespan=lifespan,
)
app.include_router(training_router)
app.include_router(lake_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


def engine(request: Request) -> StrategyEngine:
    return request.app.state.engine


def candidates(request: Request) -> CandidateRepository:
    return request.app.state.candidates


def analysis_service(request: Request) -> IndividualAnalysisService:
    return request.app.state.analysis_service


@app.get("/api/market/pool", response_model=PoolResponse)
def get_market_pool(request: Request) -> PoolResponse:
    return request.app.state.pool.response()


@app.post("/api/market/scan", response_model=MarketScanResponse)
def scan_market(payload: MarketScanRequest, request: Request) -> MarketScanResponse:
    result = request.app.state.market_scanner.scan(
        include_etfs=payload.include_etfs,
        limit=payload.limit,
    )
    repo = candidates(request)
    repo.save_quotes([item.quote for item in result.items])
    run_id = repo.save_scan(result)
    trade_dates = [item.quote.trade_at.date() for item in result.items if item.quote.trade_at]
    as_of = max(trade_dates) if trade_dates else date.today()
    repo.verify_performance(as_of)
    return result.model_copy(update={"run_id": run_id})


@app.post("/api/market/scan/candidates", response_model=CandidateBatchResponse)
def save_scan_candidates(payload: CandidateBatchRequest, request: Request) -> CandidateBatchResponse:
    repo = candidates(request)
    pairs = repo.scan_candidates(payload.run_id, payload.limit, payload.min_grade)
    created: list[CandidateItem] = []
    for score_input, score in pairs:
        created.append(repo.create(CandidateCreate(
            score_input=score_input, source_type="pool-scan", source_name=payload.source_name,
            note=f"扫描运行 #{payload.run_id}，轮动池自动筛选结果",
        ), score))
    return CandidateBatchResponse(run_id=payload.run_id, created=len(created), skipped=max(0, len(pairs) - len(created)), candidates=created)


def _refresh_industry_snapshot(repo: CandidateRepository, provider: IndustryRadarProvider, *, include_history: bool = False,
                               require_complete: bool = False) -> IndustryRadarResponse:
    raw = provider.fetch(include_history=include_history)
    if raw.data_status == "error":
        if require_complete:
            raise RuntimeError("；".join(raw.degraded_reasons) or "板块采集失败，保留上次成功快照")
        cached = repo.latest_industry_snapshot()
        if cached is None:
            return raw
        return cached.model_copy(update={
            "data_status": "degraded",
            "degraded_reasons": list(dict.fromkeys([
                *cached.degraded_reasons,
                "本次更新失败，正在显示上次保存的板块快照",
                *raw.degraded_reasons,
            ])),
        })
    snapshot = provider.enrich_history(raw, repo.list_industry_history())
    repo.save_industry_snapshot(snapshot)
    missing_boards = snapshot.coverage_total - snapshot.coverage_count
    if require_complete and (snapshot.history_failures or missing_boards > 0):
        raise RuntimeError(f"{max(0, missing_boards)}个板块详情、{len(snapshot.history_failures)}只成分历史采集失败；成功部分已缓存，下次补缺失或过期数据")
    return snapshot


def _industry_snapshot(request: Request, *, refresh: bool) -> IndustryRadarResponse:
    repo = candidates(request)
    snapshot = None if refresh else repo.latest_industry_snapshot()
    if refresh:
        snapshot = _refresh_industry_snapshot(repo, request.app.state.industry_radar, include_history=False)
    if snapshot is None:
        return IndustryRadarResponse(
            snapshot_at=datetime.now(timezone.utc), source="sina-industry-radar", data_status="degraded",
            coverage_count=0, coverage_total=0,
            degraded_reasons=["本机尚无板块快照，请在数据状态与维护中更新数据；读取页面不会自动发起采集"],
        )
    history_count = len(repo.list_industry_history())
    return snapshot.model_copy(update={
        "history_snapshot_count": history_count,
        "last_success_trade_date": snapshot.last_success_trade_date,
    })


@app.get("/api/market/industry-radar", response_model=IndustryRadarResponse)
def industry_radar(request: Request) -> IndustryRadarResponse:
    """Read the latest SQLite snapshot; the UI does not block on upstream data."""
    return _industry_snapshot(request, refresh=False)


@app.post("/api/market/industry-radar/refresh", response_model=IndustryRadarResponse)
def refresh_industry_radar(request: Request) -> IndustryRadarResponse:
    return _industry_snapshot(request, refresh=True)


@app.post("/api/market/industry-radar/backfill", response_model=IndustryRadarResponse)
def backfill_industry_radar(request: Request) -> IndustryRadarResponse:
    """Run the expensive 120+ trading-day constituent backfill explicitly."""
    try:
        snapshot = request.app.state.industry_scheduler.run_now()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    history_count = len(candidates(request).list_industry_history())
    return snapshot.model_copy(update={"history_snapshot_count": history_count})


@app.get("/api/market/industry-radar/tasks", response_model=IndustryTaskStatus)
def industry_radar_task_status(request: Request) -> IndustryTaskStatus:
    return IndustryTaskStatus.model_validate(request.app.state.industry_scheduler.status())


@app.get("/api/market/industry-radar/watches", response_model=list[IndustryWatchItem])
def list_industry_watches(request: Request) -> list[IndustryWatchItem]:
    return candidates(request).list_industry_watches()


@app.post("/api/market/industry-radar/watches", response_model=IndustryWatchItem, status_code=201)
def add_industry_watch(payload: IndustryWatchCreate, request: Request) -> IndustryWatchItem:
    try:
        return candidates(request).add_industry_watch(payload.industry_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="板块不存在") from exc


@app.get("/api/market/industry-radar/alerts", response_model=list[IndustryAlert])
def industry_alerts(request: Request) -> list[IndustryAlert]:
    return candidates(request).industry_alerts()


@app.get("/api/market/industry-radar/export")
def export_industry_radar(
    request: Request,
    format: str = Query(default="csv", pattern="^(csv|json)$"),
) -> Response:
    rows = candidates(request).industry_export_rows()
    if format == "json":
        return Response(
            content=json.dumps(rows, ensure_ascii=False, default=str),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=industry-radar.json"},
        )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]) if rows else ["trade_date", "industry_id", "name"])
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=industry-radar.csv"},
    )


@app.get("/api/backup")
def backup_database(request: Request) -> Response:
    return Response(
        content=candidates(request).backup_bytes(), media_type="application/vnd.sqlite3",
        headers={"Content-Disposition": "attachment; filename=zhixing-research.sqlite3"},
    )


@app.get("/api/market/industry-radar/{industry_key}", response_model=IndustryRadarDetailResponse)
def industry_radar_detail(industry_key: str, request: Request) -> IndustryRadarDetailResponse:
    detail = candidates(request).industry_detail(industry_key)
    if detail is None:
        raise HTTPException(status_code=404, detail="板块详情不存在")
    return detail


@app.post("/api/market/industry-radar/signals/verify", response_model=IndustrySignalVerificationResponse)
def verify_industry_signals(request: Request, as_of: date | None = Query(default=None)) -> IndustrySignalVerificationResponse:
    effective_date = as_of or date.today()
    return candidates(request).verify_industry_signals(effective_date)


@app.delete("/api/market/industry-radar/watches/{industry_key}")
def delete_industry_watch(industry_key: str, request: Request) -> dict[str, bool]:
    if not candidates(request).delete_industry_watch(industry_key):
        raise HTTPException(status_code=404, detail="板块提醒不存在")
    return {"deleted": True}


@app.get("/api/market/review", response_model=MarketReviewResponse, include_in_schema=False)
def legacy_market_review(request: Request, run_id: int | None = Query(default=None, ge=1)) -> MarketReviewResponse:
    """Deprecated compatibility endpoint; the desktop product no longer exposes this page."""
    return candidates(request).market_review(run_id=run_id)


@app.get("/api/market/review/runs", response_model=list[MarketReviewRun], include_in_schema=False)
def legacy_market_review_runs(request: Request, limit: int = Query(default=30, ge=1, le=100)) -> list[MarketReviewRun]:
    return candidates(request).list_market_review_runs(limit=limit)


@app.get("/api/market/all-a/snapshot", response_model=AllAMarketSnapshot)
def all_a_snapshot(request: Request) -> AllAMarketSnapshot:
    """Whole-A health only; never invokes StrategyEngine or reference-pool scores."""
    return request.app.state.all_a_snapshot.fetch()


@app.get("/api/market/snapshots", response_model=list[QuoteSnapshot])
def list_market_snapshots(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[QuoteSnapshot]:
    return candidates(request).list_quote_snapshots(limit=limit)


@app.post("/api/analysis", response_model=AnalysisReport)
def analyze_stock(payload: AnalysisRequest, request: Request) -> AnalysisReport:
    try:
        report = analysis_service(request).analyze(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return report


@app.post("/api/analysis/compare", response_model=CompareResponse)
def compare_stocks(payload: CompareRequest, request: Request) -> CompareResponse:
    stocks = list(dict.fromkeys(item.strip() for item in payload.stocks if item.strip()))
    if len(stocks) < 2 or len(stocks) > 3:
        raise HTTPException(status_code=422, detail="股票对比需要选择 2～3 只股票")

    reports: list[AnalysisReport] = []
    errors: dict[str, str] = {}

    def analyze_one(stock: str) -> AnalysisReport:
        report = analysis_service(request).analyze(AnalysisRequest(stock=stock))
        return report

    with ThreadPoolExecutor(max_workers=len(stocks)) as executor:
        pending = {executor.submit(analyze_one, stock): stock for stock in stocks}
        for future in as_completed(pending):
            stock = pending[future]
            try:
                reports.append(future.result())
            except ValueError as exc:
                errors[stock] = str(exc)
            except Exception as exc:  # keep one unavailable source from hiding other comparisons
                errors[stock] = f"分析失败：{exc}"
    reports.sort(key=lambda report: stocks.index(report.stock_code) if report.stock_code in stocks else len(stocks))
    if not reports:
        raise HTTPException(status_code=422, detail={"message": "没有成功获取可对比的股票", "errors": errors})
    return CompareResponse(reports=reports, errors=errors)


@app.post("/api/analysis/snapshots", response_model=AnalysisSnapshotResponse)
def save_analysis_snapshot(payload: AnalysisSnapshotRequest, request: Request) -> AnalysisSnapshotResponse:
    report, saved = candidates(request).save_snapshot(payload.report, reason=payload.reason, note=payload.note)
    return AnalysisSnapshotResponse(
        report=report, saved=saved,
        message="研究快照已保存" if saved else "同一股票、交易日和结论已存在，未重复保存",
    )


@app.get("/api/stocks/search", response_model=list[StockSearchResult])
def search_stocks(
    request: Request,
    q: str = Query(min_length=1, max_length=40),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[StockSearchResult]:
    return analysis_service(request).search(q, limit=limit)


@app.get("/api/watchlist", response_model=list[WatchlistItem])
def list_watchlist(request: Request) -> list[WatchlistItem]:
    return candidates(request).list_watchlist()


@app.post("/api/watchlist", response_model=WatchlistItem, status_code=201)
def add_watchlist(payload: WatchlistCreate, request: Request) -> WatchlistItem:
    return candidates(request).add_watchlist(payload)


@app.delete("/api/watchlist/{code}")
def delete_watchlist(code: str, request: Request) -> dict[str, bool]:
    if not candidates(request).delete_watchlist(code):
        raise HTTPException(status_code=404, detail="自选股不存在")
    return {"deleted": True}


@app.get("/api/analysis/{report_id}", response_model=AnalysisReport)
def get_analysis(report_id: int, request: Request) -> AnalysisReport:
    try:
        return candidates(request).get_analysis(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析报告不存在") from exc


@app.get("/api/analysis", response_model=list[AnalysisReport])
def list_analysis(
    request: Request,
    stock_code: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AnalysisReport]:
    return candidates(request).list_analyses(stock_code=stock_code, limit=limit)


@app.get("/api/health")
def health(request: Request) -> dict[str, str]:
    settings: Settings = request.app.state.settings
    return {"status": "ok", "storage": "local-sqlite", "database": str(settings.database_path)}


@app.get("/api/health/sources", response_model=DataSourceHealthResponse)
def source_health(request: Request) -> DataSourceHealthResponse:
    return DataSourceHealthResponse(sources=candidates(request).list_source_health())


@app.post("/api/health/sources/test", response_model=DataSourceHealthResponse)
def test_source_health(request: Request) -> DataSourceHealthResponse:
    return DataSourceHealthService(candidates(request)).test_all()


@app.get("/api/strategy")
def get_strategy(request: Request) -> dict:
    return json.loads(engine(request).path.read_text(encoding="utf-8"))


@app.post("/api/score", response_model=ScoreResult)
def score(payload: ScoreInput, request: Request) -> ScoreResult:
    return engine(request).score(payload)


@app.post("/api/candidates", response_model=CandidateItem, status_code=201)
def create_candidate(payload: CandidateCreate, request: Request) -> CandidateItem:
    result = engine(request).score(payload.score_input)
    if not result.eligible:
        raise HTTPException(status_code=422, detail={"message": "候选股未通过策略强制过滤", "reasons": result.rejected_reasons})
    return candidates(request).create(payload, result)


@app.get("/api/candidates", response_model=CandidateList)
def list_candidates(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> CandidateList:
    rows = candidates(request).list(status=status, limit=limit)
    return CandidateList(candidates=rows, total=len(rows))


@app.post("/api/candidates/from-analysis", response_model=CandidateItem, status_code=201)
def create_analysis_candidate(payload: AnalysisSignalCandidateRequest, request: Request) -> CandidateItem:
    try:
        return candidates(request).create_analysis_signal(payload.report, payload.planned_horizon, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/candidates/{candidate_id}", response_model=CandidateItem)
def update_candidate(candidate_id: int, payload: CandidateUpdate, request: Request) -> CandidateItem:
    try:
        return candidates(request).update(candidate_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="预选股不存在") from exc


@app.post("/api/candidates/performance/verify", response_model=PerformanceVerificationResponse)
def verify_candidate_performance(request: Request, as_of: date | None = Query(default=None)) -> PerformanceVerificationResponse:
    repo = candidates(request)
    effective_date = as_of or date.today()
    outcomes = repo.verify_performance(effective_date)
    summary = repo.performance_summary(effective_date)
    return PerformanceVerificationResponse(as_of=effective_date, outcomes=outcomes, **summary)
