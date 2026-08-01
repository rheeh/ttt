from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from app.database import CandidateRepository
from app.analysis.models import AnalysisReport, AnalysisRequest
from app.analysis.service import IndividualAnalysisService
from app.market.scanner import MarketScanner, StockPool
from app.market.tencent import TencentQuoteProvider
from app.market.tencent_daily import TencentDailyProvider
from app.models import (
    CandidateBatchRequest, CandidateBatchResponse, CandidateCreate, CandidateItem, CandidateList, CandidateUpdate,
    MarketScanRequest, MarketScanResponse, PerformanceVerificationResponse, PoolResponse, QuoteSnapshot,
    ScoreInput, ScoreResult,
)
from app.scoring import StrategyEngine
from app.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.engine = StrategyEngine(settings.strategy_path)
    app.state.candidates = CandidateRepository(settings.database_path)
    app.state.pool = StockPool(settings.stock_pool_path)
    app.state.market_scanner = MarketScanner(
        pool=app.state.pool,
        provider=TencentQuoteProvider(),
        engine=app.state.engine,
        history_provider=TencentDailyProvider(),
    )
    app.state.analysis_service = IndividualAnalysisService(app.state.pool, TencentQuoteProvider())
    yield


app = FastAPI(
    title="知行股研本地 API",
    version="0.1.0",
    description="仅用于本地股票研究；不含交易接口。",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
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
    return candidates(request).save_analysis(report)


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
