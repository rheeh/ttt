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
    trade_at: datetime | None = None
    fetched_at: datetime
    source: str
    history_source: str | None = None
    status: Literal["ok", "degraded", "error"]
    missing_fields: list[str] = Field(default_factory=list)
    error: str | None = None


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


class PerformanceVerificationResponse(BaseModel):
    as_of: date
    processed: int
    verified: int
    pending: int
    unavailable: int
    outcomes: list[PerformanceOutcome]


CandidateItem.model_rebuild()
