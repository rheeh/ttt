"""One explicit price contract shared by Tencent daily consumers."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta

from app.analysis.models import DailyBar
from app.market.trading_calendar import DAILY_READY_AT, SHANGHAI, market_now

CONTRACT_VERSION = "tencent-completed-daily-v1"
INDEX_SYMBOLS = frozenset({"sh000001", "sh000300"})


class DailyDataError(ValueError):
    pass


class BarSeries(list):
    def __init__(self, bars=(), *, adjustment: str = "qfq", error: str | None = None):
        super().__init__(bars)
        self.adjustment = adjustment
        self.error = error
        self.fetched_at = market_now().isoformat()
        self.source = "tencent-kline"
        self.fallback_reason = None


def parse_daily_rows(rows: list, *, now: datetime | None = None) -> list[DailyBar]:
    local = (now or market_now()).astimezone(SHANGHAI)
    last_completed = local.date() if local.time() >= DAILY_READY_AT else local.date() - timedelta(days=1)
    bars: list[DailyBar] = []
    previous = None
    for row in rows:
        try:
            if len(row) < 6:
                raise ValueError("OHLCV 字段不完整")
            bar = DailyBar(trade_date=row[0], open=row[1], close=row[2], high=row[3], low=row[4], volume=row[5])
            numbers = (bar.open, bar.close, bar.high, bar.low, bar.volume)
            if not all(math.isfinite(value) for value in numbers):
                raise ValueError("存在非有限数值")
            if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
                raise ValueError("OHLC 高低价关系错误")
            if previous is not None and bar.trade_date <= previous:
                raise ValueError("日期重复或未严格递增")
            previous = bar.trade_date
            if bar.trade_date > local.date():
                raise ValueError("存在未来日期")
            if bar.trade_date <= last_completed:
                bars.append(bar)
        except (TypeError, ValueError, IndexError) as exc:
            raise DailyDataError(f"日线校验失败：{exc}") from exc
    return bars


def parse_tencent_daily(payload: dict, code: str, *, now: datetime | None = None) -> BarSeries:
    if payload.get("code") != 0:
        raise DailyDataError(payload.get("msg") or "日线接口返回失败")
    data = (payload.get("data") or {}).get(code) or {}
    # Benchmarks are indices, so raw index points are the correct contract.
    # This explicit exception must never extend to equities or ETFs.
    index = code in INDEX_SYMBOLS
    rows = (data.get("day") or data.get("qfqday")) if index else data.get("qfqday")
    if not rows:
        raise DailyDataError("缺少指数日线" if index else "缺少显式前复权 qfqday，未使用未复权 day 替代")
    return BarSeries(parse_daily_rows(rows, now=now), adjustment="index_points" if index else "qfq")


def daily_metadata(bars: list[DailyBar]) -> dict:
    payload = [bar.model_dump(mode="json") for bar in bars]
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    adjustment = getattr(bars, "adjustment", "unknown")
    return {"contract_version": getattr(bars, "contract_version", CONTRACT_VERSION), "adjustment": adjustment,
            "adjustment_anchor": getattr(bars, "adjustment_anchor", "vendor_current" if adjustment == "qfq" else None),
            "source": getattr(bars, "source", "unknown"),
            "volume_unit": getattr(bars, "volume_unit", "source_native"), "content_sha256": digest,
            "revisions": getattr(bars, "revisions", {}), "upstream_sources": getattr(bars, "upstream_sources", []),
            "fallback_reason": getattr(bars, "fallback_reason", None),
            "fetched_at": getattr(bars, "fetched_at", None), "bar_count": len(bars),
            "coverage_start": bars[0].trade_date.isoformat() if bars else None,
            "coverage_end": bars[-1].trade_date.isoformat() if bars else None,
            "error": getattr(bars, "error", None)}
