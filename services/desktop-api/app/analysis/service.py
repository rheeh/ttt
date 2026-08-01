from __future__ import annotations

import json
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.analysis.advice import build_advice
from app.analysis.indicators import calculate_indicators
from app.analysis.models import AnalysisReport, AnalysisRequest, DailyBar
from app.analysis.rocket_score import calculate_rocket_score
from app.market.scanner import StockPool
from app.market.tencent import TencentQuoteProvider
from app.models import QuoteSnapshot, StockPreset


class IndividualAnalysisService:
    name = "tencent-qt+tencent-qfq-day"

    def __init__(self, pool: StockPool, quote_provider: TencentQuoteProvider | None = None, timeout_seconds: float = 8):
        self.pool = pool
        self.quote_provider = quote_provider or TencentQuoteProvider(timeout_seconds=timeout_seconds)
        self.timeout_seconds = timeout_seconds
        self.by_code = {item.code: item for item in pool.stocks + pool.etfs}

    def analyze(self, request: AnalysisRequest) -> AnalysisReport:
        preset = self.resolve(request.stock)
        quote = self.quote_provider.fetch([preset])[0]
        bars = self.fetch_bars(preset.code)
        technical = calculate_indicators(bars)
        missing = list(quote.missing_fields)
        if not bars:
            missing.append("daily_bars")
        if technical.bar_count < 60:
            missing.append("long_history")
        rocket = calculate_rocket_score(
            change_pct=quote.change_pct, pe=quote.pe, main_flow_ratio=quote.main_flow_ratio,
            sector_rank=None, volume_ratio=technical.volume_ratio, inout_ratio=None,
            macd=technical.macd, revenue_growth=None,
        )
        missing.extend(rocket.missing_fields)
        advice = build_advice(pe=quote.pe, roe=None, score=rocket.score, technical=technical,
                              is_holding=request.is_holding, position_cost=request.position_cost)
        deduped_missing = sorted(set(missing))
        return AnalysisReport(
            created_at=datetime.now(timezone.utc), stock_code=preset.code,
            stock_name=quote.stock_name or preset.name, sector=preset.sector, asset_type=preset.asset_type,
            source=self.name, status="error" if quote.status == "error" else "degraded" if deduped_missing else "ok",
            missing_fields=deduped_missing, quote=quote.model_dump(mode="json"), technical=technical,
            rocket=rocket, advice=advice,
            facts={"input": request.model_dump(), "data_policy": "缺失字段显示为未接入，不用默认值伪造"}, bars=bars,
        )

    def resolve(self, value: str) -> StockPreset:
        normalized = value.strip().lower()
        if normalized.isdigit() and len(normalized) == 6:
            normalized = ("sh" if normalized.startswith("6") else "sz") + normalized
        if normalized in self.by_code:
            return self.by_code[normalized]
        for preset in self.by_code.values():
            if preset.name and preset.name in value:
                return preset
        if normalized.startswith(("sh", "sz")) and len(normalized) == 8 and normalized[2:].isdigit():
            return StockPreset(secid=normalized, code=normalized, name=value, sector="其他")
        raise ValueError(f"无法识别股票：{value}，请输入 6 位代码、sh/sz 代码或固定池中的名称")

    def fetch_bars(self, code: str, days: int = 252) -> list[DailyBar]:
        query = urlencode({"param": f"{code},day,,,{days},qfq"})
        request = Request(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + query,
            headers={"User-Agent": "Mozilla/5.0 ZhixingStockResearch/0.3", "Referer": "https://gu.qq.com/"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
            return []
        rows = payload.get("data", {}).get(code, {}).get("qfqday") or payload.get("data", {}).get(code, {}).get("day") or []
        bars: list[DailyBar] = []
        for row in rows:
            if len(row) < 6:
                continue
            try:
                trade_date = date.fromisoformat(str(row[0]))
                open_price, close, high, low, volume = (float(row[index]) for index in range(1, 6))
                if min(open_price, close, high, low) <= 0:
                    continue
                bars.append(DailyBar(trade_date=trade_date, open=open_price, close=close, high=high, low=low, volume=max(volume, 0)))
            except (TypeError, ValueError):
                continue
        return bars
