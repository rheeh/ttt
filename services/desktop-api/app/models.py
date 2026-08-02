from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


CandidateStatus = Literal["new", "watching", "ready", "abandoned", "validated"]


class ScoreInput(BaseModel):
    stock_code: str = Field(min_length=6, max_length=12)
    stock_name: str = Field(min_length=1, max_length=80)
    sector: str = Field(default="其他", max_length=50)
    price: float = Field(gt=0)
    pe: float = Field(gt=0)
    pb: float = Field(gt=0)
    pe_percentile: float = Field(ge=0, le=1)
    pb_percentile: float = Field(ge=0, le=1)
    change_pct: float
    turnover_pct: float = Field(ge=0)
    amplitude_pct: float = Field(ge=0)
    main_flow_ratio: float = Field(description="0.05 means 5 percent")
    sector_change_pct: float = 0
    quality_score: int = Field(default=0, ge=-4, le=4)
    ma5: float | None = Field(default=None, gt=0)
    ma10: float | None = Field(default=None, gt=0)
    ma20: float | None = Field(default=None, gt=0)
    in_rotation_pool: bool = False
    is_st: bool = False
    mode: Literal["pre-market", "review"] = "pre-market"

    @field_validator("stock_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().lower()


class ScoreDimension(BaseModel):
    name: str
    label: str
    score: int
    reasons: list[str] = Field(default_factory=list)


class ScoreResult(BaseModel):
    stock_code: str
    stock_name: str
    strategy_id: str
    strategy_version: str
    rule_fingerprint: str
    total_score: int
    grade: Literal["S", "A", "B", "C"]
    eligible: bool
    rejected_reasons: list[str]
    dimensions: list[ScoreDimension]


class PriceZones(BaseModel):
    add_low: float | None = Field(default=None, gt=0)
    add_high: float | None = Field(default=None, gt=0)
    trade_low: float | None = Field(default=None, gt=0)
    trade_high: float | None = Field(default=None, gt=0)
    clear_below: float | None = Field(default=None, gt=0)
    conviction_low: float | None = Field(default=None, gt=0)
    conviction_high: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "PriceZones":
        for low_name, high_name in (
            ("add_low", "add_high"),
            ("trade_low", "trade_high"),
            ("conviction_low", "conviction_high"),
        ):
            low = getattr(self, low_name)
            high = getattr(self, high_name)
            if low is not None and high is not None and low > high:
                raise ValueError(f"{low_name} must not exceed {high_name}")
        return self


class CandidateCreate(BaseModel):
    score_input: ScoreInput
    source_type: str = Field(default="strategy", max_length=32)
    source_name: str = Field(default="群友原版", max_length=100)
    note: str | None = Field(default=None, max_length=2000)
    status: CandidateStatus = "new"
    price_zones: PriceZones = Field(default_factory=PriceZones)


class CandidateUpdate(BaseModel):
    status: CandidateStatus | None = None
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_change(self) -> "CandidateUpdate":
        if self.status is None and self.note is None:
            raise ValueError("status or note is required")
        return self


class CandidateItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    selected_at: datetime
    source_type: str
    source_name: str
    strategy_id: str
    strategy_version: str
    rule_fingerprint: str
    total_score: int
    grade: Literal["S", "A", "B", "C"]
    reasons: list[str]
    dimensions: list[ScoreDimension]
    score_input: ScoreInput
    selected_price: float
    status: CandidateStatus
    note: str | None
    price_zones: PriceZones
    performance: list["PerformanceOutcome"] = Field(default_factory=list)


class CandidateList(BaseModel):
    candidates: list[CandidateItem]
    total: int


class StockPreset(BaseModel):
    secid: str
    code: str
    name: str
    sector: str
    asset_type: Literal["stock", "etf"] = "stock"


class StockSearchResult(BaseModel):
    code: str
    name: str
    market: str | None = None
    asset_type: Literal["stock", "etf"] = "stock"
    source: str = "eastmoney-suggest"


class WatchlistCreate(BaseModel):
    code: str = Field(min_length=6, max_length=8)
    name: str = Field(min_length=1, max_length=80)
    sector: str = Field(default="其他", max_length=50)
    asset_type: Literal["stock", "etf"] = "stock"


class WatchlistItem(BaseModel):
    id: int
    code: str
    name: str
    sector: str
    asset_type: Literal["stock", "etf"]
    added_at: datetime
    source: str


class QuoteSnapshot(BaseModel):
    stock_code: str
    stock_name: str
    price: float | None = None
    previous_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    change_pct: float | None = None
    turnover_pct: float | None = None
    amplitude_pct: float | None = None
    pe: float | None = None
    pb: float | None = None
    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    volume: float | None = None
    amount: float | None = None
    main_flow_ratio: float | None = None
    # Tencent's undocumented extension fields (p[68]/p[70]/p[71]).  Values
    # are normalized to 亿元 and are only used as an explicitly labelled
    # fallback when the formal five-level flow endpoint is unavailable.
    main_inflow: float | None = None
    main_inflow_5d: float | None = None
    main_inflow_10d: float | None = None
    fund_flow_ratio_estimated: float | None = None
    trade_at: datetime | None = None
    fetched_at: datetime
    source: str
    history_source: str | None = None
    status: Literal["ok", "degraded", "error"]
    missing_fields: list[str] = Field(default_factory=list)
    error: str | None = None
    fallback_reason: str | None = None


class DailyIndicators(BaseModel):
    stock_code: str
    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    bar_count: int = 0
    latest_trade_date: str | None = None
    source: str
    status: Literal["ok", "error"]
    error: str | None = None
    fallback_reason: str | None = None


class PoolResponse(BaseModel):
    version: str
    stocks: list[StockPreset]
    etfs: list[StockPreset]


class MarketScanRequest(BaseModel):
    include_etfs: bool = False
    limit: int | None = Field(default=None, ge=1, le=100)


class MarketScanItem(BaseModel):
    preset: StockPreset
    quote: QuoteSnapshot
    score: ScoreResult | None = None
    score_input: ScoreInput | None = None


class MarketScanResponse(BaseModel):
    started_at: datetime
    completed_at: datetime
    source: str
    total: int
    succeeded: int
    degraded: int
    failed: int
    scoreable: int
    run_id: int | None = None
    rule_fingerprint: str
    rotation_pool_codes: list[str] = Field(default_factory=list)
    items: list[MarketScanItem]
    # Scope metadata: a strategy scan is never a whole-market health snapshot.
    scope: Literal["reference_pool", "all_a_market"] = "reference_pool"
    pool_name: str = "reference-pool"
    pool_version: str = "unknown"
    pool_component_count: int = 0
    transaction_date: date | None = None
    coverage_count: int = 0
    coverage_total: int = 0
    coverage_pct: float | None = None
    data_status: Literal["ok", "degraded", "error"] = "degraded"
    degraded_reasons: list[str] = Field(default_factory=list)


class MarketReviewItem(BaseModel):
    stock_code: str
    stock_name: str
    sector: str
    price: float | None = None
    change_pct: float | None = None
    grade: Literal["S", "A", "B", "C"] | None = None
    score: int | None = None
    status: Literal["ok", "degraded", "error"]


class MarketSectorReview(BaseModel):
    sector: str
    count: int
    average_change_pct: float | None = None
    up_count: int
    scoreable: int
    average_score: float | None = None


class MarketReviewResponse(BaseModel):
    run_id: int | None = None
    as_of: datetime | None = None
    source: str = "none"
    total: int = 0
    succeeded: int = 0
    degraded: int = 0
    failed: int = 0
    scoreable: int = 0
    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    # Deprecated alias retained for API compatibility; UI uses sample_up_rate_pct.
    breadth_pct: float | None = None
    sample_up_rate_pct: float | None = None
    change_sample_count: int = 0
    average_change_pct: float | None = None
    average_score: float | None = None
    strategy_average_score: float | None = None
    strategy_scoreable: int = 0
    rotation_pool_codes: list[str] = Field(default_factory=list)
    top_gainers: list[MarketReviewItem] = Field(default_factory=list)
    top_scores: list[MarketReviewItem] = Field(default_factory=list)
    sectors: list[MarketSectorReview] = Field(default_factory=list)
    scope: Literal["reference_pool", "all_a_market"] = "reference_pool"
    pool_name: str = "reference-pool"
    pool_version: str = "unknown"
    pool_component_count: int = 0
    transaction_date: date | None = None
    scan_started_at: datetime | None = None
    scan_completed_at: datetime | None = None
    coverage_count: int = 0
    coverage_total: int = 0
    coverage_pct: float | None = None
    data_status: Literal["ok", "degraded", "error"] = "degraded"
    degraded_reasons: list[str] = Field(default_factory=list)


class MarketReviewRun(BaseModel):
    run_id: int
    completed_at: datetime
    source: str
    total: int
    scoreable: int
    average_change_pct: float | None = None
    scope: Literal["reference_pool", "all_a_market"] = "reference_pool"
    pool_name: str = "reference-pool"
    pool_version: str = "unknown"
    pool_component_count: int = 0
    transaction_date: date | None = None
    coverage_pct: float | None = None
    data_status: Literal["ok", "degraded", "error"] = "degraded"


class AllAMarketSnapshot(BaseModel):
    """Whole-A health snapshot; deliberately contains no strategy scores."""
    scope: Literal["all_a_market"] = "all_a_market"
    snapshot_at: datetime
    transaction_date: date | None = None
    source: str
    data_status: Literal["ok", "degraded", "error"]
    total: int = 0
    coverage_count: int = 0
    coverage_total: int = 0
    coverage_pct: float | None = None
    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    sample_up_rate_pct: float | None = None
    average_change_pct: float | None = None
    degraded_reasons: list[str] = Field(default_factory=list)
    strategy_used: bool = False
    strategy_scoreable: int = 0


IndustryStage = Literal["下跌中", "低位企稳", "底部改善", "突破确认", "高位拥挤"]


class IndustryRadarItem(BaseModel):
    name: str
    stage: IndustryStage
    score: float | None = None
    low_position_score: float | None = None
    deceleration_score: float | None = None
    breadth_score: float | None = None
    volume_price_score: float | None = None
    relative_strength_score: float | None = None
    change_pct: float | None = None
    return_5d_pct: float | None = None
    return_20d_pct: float | None = None
    drawdown_1y_pct: float | None = None
    up_count: int | None = None
    down_count: int | None = None
    constituent_count: int | None = None
    coverage_pct: float | None = None
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    status: Literal["ok", "degraded", "error"] = "degraded"
    source: str
    fetched_at: datetime


class IndustryRadarResponse(BaseModel):
    scope: Literal["all_industries"] = "all_industries"
    snapshot_at: datetime
    source: str
    data_status: Literal["ok", "degraded", "error"]
    coverage_count: int
    coverage_total: int
    coverage_pct: float | None = None
    confirmation_days: int = 1
    rule_version: str = "industry-radar-v1"
    building: list[IndustryRadarItem] = Field(default_factory=list)
    confirmed: list[IndustryRadarItem] = Field(default_factory=list)
    overheated: list[IndustryRadarItem] = Field(default_factory=list)
    other: list[IndustryRadarItem] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)


class DataSourceHealth(BaseModel):
    source: str
    category: str
    installed: bool
    accessible: bool
    valid: bool
    status: Literal["ok", "degraded", "error", "unavailable"]
    checked_at: datetime
    response_ms: int | None = None
    last_success_at: datetime | None = None
    error: str | None = None
    details: str | None = None


class DataSourceHealthResponse(BaseModel):
    checked_at: datetime | None = None
    sources: list[DataSourceHealth] = Field(default_factory=list)


class CandidateBatchRequest(BaseModel):
    run_id: int = Field(gt=0)
    limit: int = Field(default=10, ge=1, le=100)
    min_grade: Literal["S", "A", "B", "C"] = "B"
    source_name: str = Field(default="固定观察池扫描", max_length=100)


class CandidateBatchResponse(BaseModel):
    run_id: int
    created: int
    skipped: int
    candidates: list[CandidateItem]


class PerformanceOutcome(BaseModel):
    candidate_id: int
    horizon: Literal["1d", "5d", "20d"]
    due_date: date
    baseline_price: float
    realized_price: float | None = None
    return_pct: float | None = None
    status: Literal["pending", "verified", "unavailable"]
    measured_at: datetime | None = None
    source: str | None = None
    note: str | None = None


class PerformanceHorizonSummary(BaseModel):
    horizon: Literal["1d", "5d", "20d"]
    samples: int
    verified: int
    wins: int
    win_rate_pct: float | None = None
    average_return_pct: float | None = None


class PerformanceVerificationResponse(BaseModel):
    as_of: date
    processed: int
    verified: int
    pending: int
    unavailable: int
    outcomes: list[PerformanceOutcome]
    horizon_summary: list[PerformanceHorizonSummary] = Field(default_factory=list)


CandidateItem.model_rebuild()
