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
    high52w: float | None = None
    low52w: float | None = None
    volume_ratio: float | None = None
    trend: Literal["强势上涨", "上涨", "震荡", "下跌", "快速下跌", "数据不足"] = "数据不足"
    bar_count: int = 0


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


class AnalysisRequest(BaseModel):
    stock: str = Field(min_length=1, max_length=40)
    is_holding: bool = False
    position_cost: float | None = Field(default=None, gt=0)


class AnalysisReport(BaseModel):
    report_id: int | None = None
    created_at: datetime
    stock_code: str
    stock_name: str
    sector: str
    asset_type: Literal["stock", "etf"] = "stock"
    source: str
    status: Literal["ok", "degraded", "error"]
    missing_fields: list[str] = Field(default_factory=list)
    quote: dict
    technical: TechnicalIndicators
    rocket: RocketScore
    advice: Advice
    facts: dict = Field(default_factory=dict)
    bars: list[DailyBar] = Field(default_factory=list)
