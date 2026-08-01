from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any, Type
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.analysis.advice import build_advice
from app.analysis.data_sources import EastmoneyFinanceProvider, EastmoneyFundFlowProvider, EastmoneyIndustryProvider, EastmoneyNewsProvider, FinanceFacts, FundFlowFacts, IndustryFacts, NewsFacts
from app.analysis.diagnostics import ZHIXING_ALGORITHM_VERSION, ZHIXING_RULE_FINGERPRINT, build_diagnosis, build_factors, build_radar
from app.analysis.indicators import aggregate_weekly, calculate_indicators, trend_series
from app.analysis.models import AnalysisReport, AnalysisRequest, DailyBar
from app.analysis.rocket_score import calculate_rocket_score
from app.market.scanner import StockPool
from app.market.tencent import TencentQuoteProvider
from app.models import QuoteSnapshot, StockPreset, StockSearchResult


class IndividualAnalysisService:
    name = "tencent-qt+tencent-qfq-day"

    def __init__(self, pool: StockPool, quote_provider: TencentQuoteProvider | None = None, timeout_seconds: float = 8, cache: Any | None = None):
        self.pool = pool
        self.quote_provider = quote_provider or TencentQuoteProvider(timeout_seconds=timeout_seconds)
        self.timeout_seconds = timeout_seconds
        self.by_code = {item.code: item for item in pool.stocks + pool.etfs}
        self.cache = cache
        self.fund_flow_provider = EastmoneyFundFlowProvider(timeout_seconds)
        self.finance_provider = EastmoneyFinanceProvider(timeout_seconds)
        self.industry_provider = EastmoneyIndustryProvider(timeout_seconds)
        self.news_provider = EastmoneyNewsProvider(timeout_seconds)

    def analyze(self, request: AnalysisRequest) -> AnalysisReport:
        preset = self.resolve(request.stock)
        quote = self.quote_provider.fetch([preset])[0]
        bars = self.fetch_bars(preset.code)
        technical = calculate_indicators(bars)
        weekly_bars = aggregate_weekly(bars)
        weekly = calculate_indicators(weekly_bars)
        benchmark_bars = [] if preset.code == "sh000001" else self.fetch_bars("sh000001")
        benchmark = calculate_indicators(benchmark_bars) if benchmark_bars else None
        fund_flow, finance, industry, news = self.fetch_supplementary(preset.code, quote.stock_name or preset.name)
        core_missing = [field for field in quote.missing_fields if field in {"price", "change_pct", "pe", "pb", "turnover_pct", "amplitude_pct"}]
        if not bars:
            core_missing.append("daily_bars")
        if technical.bar_count < 60:
            core_missing.append("long_history")
        rocket = calculate_rocket_score(
            change_pct=quote.change_pct, pe=quote.pe, main_flow_ratio=fund_flow.main_flow_ratio,
            sector_rank=industry.rank, volume_ratio=technical.volume_ratio, inout_ratio=None,
            macd=technical.macd, revenue_growth=finance.revenue_yoy,
        )
        legacy_missing = rocket.missing_fields
        enrichment_missing = [name for name, source in (("fund_flow", fund_flow), ("finance_growth", finance), ("industry_heat", industry), ("news", news)) if source.status in {"error", "degraded"}]
        enrichment_stale = [name for name, source in (("fund_flow", fund_flow), ("finance_growth", finance), ("industry_heat", industry), ("news", news)) if source.status == "stale"]
        advice = build_advice(pe=quote.pe, roe=None, score=rocket.score, technical=technical,
                              is_holding=request.is_holding, position_cost=request.position_cost)
        factors = build_factors(
            price=quote.price, change_pct=quote.change_pct, daily=technical, weekly=weekly,
            benchmark=benchmark, sector_rank=industry.rank, in_reference_pool=preset.code in self.by_code,
            fund_flow_ratio=fund_flow.main_flow_ratio, revenue_growth=finance.revenue_yoy,
        )
        available_count = sum(factor.available for factor in factors)
        total_factors = len(factors)
        zhixing_raw_score = round(sum(factor.score if factor.available else 50 for factor in factors) / total_factors, 2) if total_factors else 50
        zhixing_index = zhixing_raw_score
        zhixing_confidence = round(available_count / total_factors * 100, 2) if total_factors else 0
        zhixing_level = "强势" if zhixing_index >= 80 else "偏强" if zhixing_index >= 60 else "中性" if zhixing_index >= 40 else "偏弱"
        radar = build_radar(factors)
        diagnosis = build_diagnosis(price=quote.price, daily=technical, weekly=weekly, index_score=zhixing_index)
        diagnosis = diagnosis.model_copy(update={
            "positive_evidence": diagnosis.positive_evidence + [f"主力净流入占比 {fund_flow.main_flow_ratio * 100:+.2f}%" if fund_flow.main_flow_ratio is not None and fund_flow.main_flow_ratio > .02 else f"营收同比 {finance.revenue_yoy:+.1f}%" if finance.revenue_yoy is not None and finance.revenue_yoy > 5 else ""],
            "risk_evidence": diagnosis.risk_evidence + [f"主力净流出占比 {fund_flow.main_flow_ratio * 100:.2f}%" if fund_flow.main_flow_ratio is not None and fund_flow.main_flow_ratio < -.02 else f"营收同比 {finance.revenue_yoy:+.1f}%" if finance.revenue_yoy is not None and finance.revenue_yoy < -5 else ""],
        })
        diagnosis = diagnosis.model_copy(update={
            "positive_evidence": [item for item in diagnosis.positive_evidence if item],
            "risk_evidence": [item for item in diagnosis.risk_evidence if item],
        })
        news_bull = sum(item.sentiment == "bull" for item in news.items)
        news_bear = sum(item.sentiment == "bear" for item in news.items)
        if news_bull:
            diagnosis = diagnosis.model_copy(update={"positive_evidence": diagnosis.positive_evidence + [f"近期开源新闻中有 {news_bull} 条偏积极"]})
        if news_bear:
            diagnosis = diagnosis.model_copy(update={"risk_evidence": diagnosis.risk_evidence + [f"近期开源新闻中有 {news_bear} 条偏风险"]})
        source_statuses = [fund_flow.status, finance.status, industry.status, news.status]
        enrichment_status = "error" if any(status == "error" for status in source_statuses) else "stale" if any(status == "stale" for status in source_statuses) else "degraded" if any(status == "degraded" for status in source_statuses) else "ok"
        core_status = "error" if quote.status == "error" or not bars else "degraded" if core_missing else "ok"
        legacy_status = "error" if quote.status == "error" else "degraded" if legacy_missing else "ok"
        deduped_missing = sorted(set(core_missing + enrichment_missing + enrichment_stale))
        return AnalysisReport(
            created_at=datetime.now(timezone.utc), stock_code=preset.code,
            stock_name=quote.stock_name or preset.name, sector=preset.sector, asset_type=preset.asset_type,
            source=self.name, status=core_status, core_status=core_status, core_missing_fields=sorted(set(core_missing)),
            enrichment_status=enrichment_status, enrichment_missing_fields=sorted(set(enrichment_missing)),
            enrichment_stale_fields=sorted(set(enrichment_stale)), legacy_score_status=legacy_status,
            legacy_missing_fields=sorted(set(legacy_missing)),
            missing_fields=deduped_missing, quote=quote.model_dump(mode="json"), technical=technical,
            weekly=weekly, rocket=rocket, zhixing_index=zhixing_index, zhixing_level=zhixing_level,
            zhixing_raw_score=zhixing_raw_score, raw_score=zhixing_raw_score, zhixing_confidence=zhixing_confidence, confidence=zhixing_confidence,
            factor_coverage=f"{available_count}/{total_factors}", algorithm_version=ZHIXING_ALGORITHM_VERSION,
            rule_fingerprint=ZHIXING_RULE_FINGERPRINT,
            factors=factors, radar=radar, trend_series=trend_series(bars), diagnosis=diagnosis, advice=advice,
            facts={"input": request.model_dump(), "data_policy": "缺失字段显示为未接入，不用默认值伪造",
                   "benchmark": "sh000001" if benchmark_bars else None, "daily_bars": len(bars), "weekly_bars": len(weekly_bars),
                   "algorithm_version": ZHIXING_ALGORITHM_VERSION, "rule_fingerprint": ZHIXING_RULE_FINGERPRINT},
            fund_flow=fund_flow.model_dump(mode="json"), finance=finance.model_dump(mode="json"),
            industry=industry.model_dump(mode="json"), news=news.model_dump(mode="json"), bars=bars,
        )

    def fetch_supplementary(self, code: str, name: str):
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                "fund_flow": executor.submit(self.fund_flow_provider.fetch, code),
                "finance": executor.submit(self.finance_provider.fetch, code),
                "industry": executor.submit(self.industry_provider.fetch, code),
                "news": executor.submit(self.news_provider.fetch, name),
            }
            raw = tuple(futures[key].result() for key in ("fund_flow", "finance", "industry", "news"))
        return (
            self._with_cache(code, raw[0], FundFlowFacts),
            self._with_cache(code, raw[1], FinanceFacts),
            self._with_cache(code, raw[2], IndustryFacts),
            self._with_cache(code, raw[3], NewsFacts),
        )

    def _with_cache(self, code: str, result: Any, model_type: Type[Any]) -> Any:
        now = datetime.now(timezone.utc)
        age = max(0.0, (now - result.fetched_at).total_seconds())
        if result.status == "ok":
            fresh = result.model_copy(update={"data_age_seconds": round(age, 1)})
            if self.cache is not None:
                self.cache.save_source_cache(code, result.source, result.fetched_at.isoformat(), fresh.model_dump(mode="json"))
            return fresh
        if self.cache is not None:
            cached = self.cache.get_source_cache(code, result.source)
            if cached is not None:
                cached_at, payload = cached
                cached_result = model_type.model_validate(payload)
                try:
                    cached_age = max(0.0, (now - datetime.fromisoformat(cached_at)).total_seconds())
                except ValueError:
                    cached_age = age
                return cached_result.model_copy(update={
                    "status": "stale", "cache_used": True, "data_age_seconds": round(cached_age, 1),
                    "error": f"本次请求失败，使用最近成功缓存：{result.error or 'unknown error'}",
                })
        return result.model_copy(update={"data_age_seconds": round(age, 1)})

    def resolve(self, value: str) -> StockPreset:
        normalized = value.strip().lower()
        if normalized.isdigit() and len(normalized) == 6:
            normalized = ("sh" if normalized.startswith("6") else "sz") + normalized
        if normalized in self.by_code:
            return self.by_code[normalized]
        for preset in self.by_code.values():
            if preset.name and preset.name in value:
                return preset
        searched = self._search_name(value)
        if searched is not None:
            return searched
        if normalized.startswith(("sh", "sz")) and len(normalized) == 8 and normalized[2:].isdigit():
            return StockPreset(secid=normalized, code=normalized, name=value, sector="其他")
        raise ValueError(f"无法识别股票：{value}，请输入 6 位代码、sh/sz 代码或股票名称")

    def search(self, value: str, limit: int = 20) -> list[StockSearchResult]:
        query = value.strip().lower()
        if not query:
            return []
        local: list[StockSearchResult] = []
        for preset in self.by_code.values():
            if query in preset.code or query in preset.name.lower():
                local.append(StockSearchResult(code=preset.code, name=preset.name, asset_type=preset.asset_type, source="reference-pool"))
        remote = self._search_remote(value, limit=limit)
        merged: dict[str, StockSearchResult] = {item.code: item for item in local}
        merged.update({item.code: item for item in remote})
        return list(merged.values())[:limit]

    def _search_name(self, value: str) -> StockPreset | None:
        """Resolve names outside the fixed pool without copying a second pool locally."""
        rows = self._search_remote(value, limit=1)
        if rows:
            item = rows[0]
            return StockPreset(secid=item.code, code=item.code, name=item.name, sector="其他", asset_type=item.asset_type)
        return None

    def _search_remote(self, value: str, limit: int = 20) -> list[StockSearchResult]:
        try:
            query = urlencode({"input": value.strip(), "type": "14"})
            request = Request(
                "https://searchapi.eastmoney.com/api/suggest/get?" + query,
                headers={"User-Agent": "Mozilla/5.0 ZhixingStockResearch/0.3", "Referer": "https://quote.eastmoney.com/"},
            )
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            rows = payload.get("QuotationCodeTable", {}).get("Data", [])
            results: list[StockSearchResult] = []
            for row in rows:
                code = str(row.get("Code") or "")
                name = str(row.get("Name") or "")
                if len(code) != 6 or not name:
                    continue
                prefix = "sh" if code.startswith("6") else "sz"
                normalized_code = prefix + code
                security_name = str(row.get("SecurityTypeName") or "")
                asset_type = "etf" if "基金" in security_name or code.startswith(("15", "16", "50", "51", "56", "58")) else "stock"
                results.append(StockSearchResult(code=normalized_code, name=name, market=security_name or None, asset_type=asset_type))
                if len(results) >= limit:
                    break
            return results
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
            return []

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
