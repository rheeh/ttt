from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class DailyBar(BaseModel):
    trade_date: date
    open: float = Field(gt=0)
    close: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    volume: float = Field(ge=0)


class MacdIndicator(BaseModel):
    dif: float
    dea: float
    hist: float
    golden_cross: bool = False
    death_cross: bool = False


class TechnicalIndicators(BaseModel):
    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    rsi14: float | None = None
    macd: MacdIndicator | None = None
    support20: float | None = None
    resistance20: float | None = None
    prior_support20: float | None = None
    prior_resistance20: float | None = None
    high52w: float | None = None
    low52w: float | None = None
    volume_ratio: float | None = None
    volume_ratio_basis: Literal["completed_day", "intraday_unavailable"] | None = None
    trend: Literal["强势上涨", "上涨", "震荡", "下跌", "快速下跌", "数据不足"] = "数据不足"
    bar_count: int = 0
    atr14: float | None = None
    bollinger_width: float | None = None
    return_20d_pct: float | None = None
    return_60d_pct: float | None = None


class RocketDimension(BaseModel):
    key: str
    label: str
    score: float
    max_score: float = 12.5
    reasons: list[str] = Field(default_factory=list)
    available: bool = True


class RocketScore(BaseModel):
    score: float = Field(ge=0, le=100)
    level: Literal["极强", "偏强", "中性", "偏弱", "弱势"]
    dimensions: list[RocketDimension]
    missing_fields: list[str] = Field(default_factory=list)


class FactorScore(BaseModel):
    key: str
    label: str
    score: float = Field(ge=0, le=100)
    reason: str
    available: bool = True
    source: str = "derived"


class RadarDimension(BaseModel):
    key: str
    label: str
    score: float = Field(ge=0, le=100)
    factor_keys: list[str] = Field(default_factory=list)


class TrendPoint(BaseModel):
    trade_date: date
    close: float
    ma20: float | None = None


class Diagnosis(BaseModel):
    summary: str
    position: Literal["突破", "回踩", "震荡区间", "下行趋势", "数据不足"]
    positive_evidence: list[str] = Field(default_factory=list)
    risk_evidence: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    reassess_conditions: list[str] = Field(default_factory=list)


class PriceZone(BaseModel):
    name: str
    low: float
    high: float
    action: str
    tone: Literal["green", "blue", "purple", "orange", "red"]


class Advice(BaseModel):
    action: Literal["建仓", "等回调", "观察买入", "右侧确认", "持有", "减仓警戒", "失效", "观望"]
    category: Literal["A档价值型", "B档成长型", "C档情绪型"]
    summary: str
    risk_level: Literal["低", "中", "高"]
    operations: list[str] = Field(default_factory=list)
    zones: list[PriceZone] = Field(default_factory=list)
    triggered_conditions: list[str] = Field(default_factory=list)
    unmet_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    data_confidence: float = Field(default=0, ge=0, le=100)
    data_completeness: float = Field(default=0, ge=0, le=100)
    review_after: str = "下一个交易日收盘后"


class AnalysisRequest(BaseModel):
    stock: str = Field(min_length=1, max_length=40)
    is_holding: bool = False
    position_cost: float | None = Field(default=None, gt=0)


class CompareRequest(BaseModel):
    stocks: list[str] = Field(min_length=2, max_length=3)


class AnalysisReport(BaseModel):
    report_id: int | None = None
    trade_date: str | None = None
    snapshot_reason: Literal["legacy_run", "manual", "meaningful_change", "daily_close"] | None = None
    snapshot_note: str | None = None
    content_fingerprint: str | None = None
    created_at: datetime
    stock_code: str
    stock_name: str
    sector: str
    asset_type: Literal["stock", "etf"] = "stock"
    source: str
    status: Literal["ok", "degraded", "error"]
    missing_fields: list[str] = Field(default_factory=list)
    core_status: Literal["ok", "degraded", "error"] = "degraded"
    core_missing_fields: list[str] = Field(default_factory=list)
    enrichment_status: Literal["ok", "degraded", "stale", "error", "not_applicable"] = "degraded"
    enrichment_missing_fields: list[str] = Field(default_factory=list)
    enrichment_stale_fields: list[str] = Field(default_factory=list)
    legacy_score_status: Literal["ok", "degraded", "error"] = "degraded"
    legacy_missing_fields: list[str] = Field(default_factory=list)
    quote: dict
    technical: TechnicalIndicators
    weekly: TechnicalIndicators = Field(default_factory=TechnicalIndicators)
    rocket: RocketScore
    zhixing_index: float = Field(default=0, ge=0, le=100)
    zhixing_raw_score: float = Field(default=0, ge=0, le=100)
    raw_score: float = Field(default=0, ge=0, le=100)
    zhixing_confidence: float = Field(default=0, ge=0, le=100)
    data_completeness: float = Field(default=0, ge=0, le=100)
    confidence: float = Field(default=0, ge=0, le=100)
    factor_coverage: str = "0/0"
    algorithm_version: str = "1.1.0"
    rule_fingerprint: str = ""
    zhixing_level: Literal["强势", "偏强", "中性", "偏弱"] = "中性"
    factors: list[FactorScore] = Field(default_factory=list)
    radar: list[RadarDimension] = Field(default_factory=list)
    trend_series: list[TrendPoint] = Field(default_factory=list)
    diagnosis: Diagnosis = Field(default_factory=lambda: Diagnosis(summary="数据不足", position="数据不足"))
    fund_flow: dict = Field(default_factory=dict)
    finance: dict = Field(default_factory=dict)
    industry: dict = Field(default_factory=dict)
    news: dict = Field(default_factory=dict)
    freshness: dict[str, dict] = Field(default_factory=dict)
    advice: Advice
    facts: dict = Field(default_factory=dict)
    bars: list[DailyBar] = Field(default_factory=list)
    weekly_bars: list[DailyBar] = Field(default_factory=list)


class CompareResponse(BaseModel):
    reports: list[AnalysisReport] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)


class AnalysisSnapshotRequest(BaseModel):
    report: AnalysisReport
    reason: Literal["manual", "meaningful_change", "daily_close"] = "manual"
    note: str | None = Field(default=None, max_length=2000)


class AnalysisSnapshotResponse(BaseModel):
    report: AnalysisReport
    saved: bool
    message: str


class AnalysisSignalCandidateRequest(BaseModel):
    report: AnalysisReport
    planned_horizon: Literal["1d", "5d", "20d", "60d"] = "20d"
    note: str | None = Field(default=None, max_length=2000)
