from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from app.models import (
    DailyIndicators, MarketScanItem, MarketScanResponse, PoolResponse, QuoteSnapshot,
    ScoreInput, StockPreset,
)
from app.scoring import StrategyEngine


class QuoteProvider(Protocol):
    name: str
    def fetch(self, presets: list[StockPreset]) -> list[QuoteSnapshot]: ...


class HistoryProvider(Protocol):
    name: str
    def fetch(self, presets: list[StockPreset]) -> dict[str, DailyIndicators]: ...


class StockPool:
    def __init__(self, path: Path):
        self.path = path
        data = json.loads(path.read_text(encoding="utf-8"))
        self.version = data["version"]
        self.stocks = [StockPreset(**item, asset_type="stock") for item in data["stocks"]]
        self.etfs = [StockPreset(**item, asset_type="etf") for item in data["etfs"]]

    def response(self) -> PoolResponse:
        return PoolResponse(version=self.version, stocks=self.stocks, etfs=self.etfs)


class MarketScanner:
    def __init__(self, pool: StockPool, provider: QuoteProvider, engine: StrategyEngine, history_provider: HistoryProvider | None = None):
        self.pool = pool
        self.provider = provider
        self.engine = engine
        self.history_provider = history_provider

    def scan(self, include_etfs: bool = False, limit: int | None = None) -> MarketScanResponse:
        started_at = datetime.now(timezone.utc)
        presets = list(self.pool.stocks)
        if include_etfs:
            presets.extend(self.pool.etfs)
        if limit is not None:
            presets = presets[:limit]
        quotes = self.provider.fetch(presets)
        if self.history_provider is not None:
            indicators = self.history_provider.fetch(presets)
            quotes = [self._merge_indicators(quote, indicators.get(quote.stock_code)) for quote in quotes]
        quote_by_code = {quote.stock_code: quote for quote in quotes}
        sector_stats = self._sector_stats(presets, quote_by_code)
        percentiles = self._percentiles(presets, quote_by_code)
        items: list[MarketScanItem] = []
        for preset in presets:
            quote = quote_by_code[preset.code]
            score = None
            pe_pct, pb_pct = percentiles.get(preset.code, (None, None))
            if self._scorable(quote, pe_pct, pb_pct) and preset.asset_type == "stock":
                score = self.engine.score(ScoreInput(
                    stock_code=preset.code, stock_name=quote.stock_name or preset.name,
                    sector=preset.sector, price=quote.price, pe=quote.pe, pb=quote.pb,
                    pe_percentile=pe_pct, pb_percentile=pb_pct,
                    change_pct=quote.change_pct or 0, turnover_pct=quote.turnover_pct or 0,
                    amplitude_pct=quote.amplitude_pct or 0, main_flow_ratio=0,
                    sector_change_pct=sector_stats.get(preset.sector, 0), quality_score=0,
                    ma5=quote.ma5, ma10=quote.ma10, ma20=quote.ma20,
                ))
            items.append(MarketScanItem(preset=preset, quote=quote, score=score))
        items.sort(key=lambda item: item.score.total_score if item.score else -10_000, reverse=True)
        completed_at = datetime.now(timezone.utc)
        return MarketScanResponse(
            started_at=started_at, completed_at=completed_at,
            source="+".join(filter(None, [self.provider.name, self.history_provider.name if self.history_provider else None])),
            total=len(items), succeeded=sum(item.quote.status != "error" for item in items),
            degraded=sum(item.quote.status == "degraded" for item in items),
            failed=sum(item.quote.status == "error" for item in items), items=items,
        )

    @staticmethod
    def _merge_indicators(quote: QuoteSnapshot, indicators: DailyIndicators | None) -> QuoteSnapshot:
        if indicators is None or indicators.status != "ok":
            return quote
        missing = [field for field in quote.missing_fields if field not in {"ma5", "ma10", "ma20"}]
        return quote.model_copy(update={
            "ma5": indicators.ma5, "ma10": indicators.ma10, "ma20": indicators.ma20,
            "history_source": indicators.source, "missing_fields": missing,
            "status": "degraded" if missing else "ok",
        })

    @staticmethod
    def _scorable(quote: QuoteSnapshot, pe_pct: float | None, pb_pct: float | None) -> bool:
        return all(value is not None and value > 0 for value in (quote.price, quote.pe, quote.pb)) and pe_pct is not None and pb_pct is not None

    @staticmethod
    def _sector_stats(presets: list[StockPreset], quotes: dict[str, QuoteSnapshot]) -> dict[str, float]:
        changes: dict[str, list[float]] = {}
        for preset in presets:
            value = quotes[preset.code].change_pct
            if value is not None:
                changes.setdefault(preset.sector, []).append(value)
        return {sector: sum(values) / len(values) for sector, values in changes.items() if values}

    @staticmethod
    def _percentiles(presets: list[StockPreset], quotes: dict[str, QuoteSnapshot]) -> dict[str, tuple[float, float]]:
        by_sector: dict[str, list[StockPreset]] = {}
        for preset in presets:
            if preset.asset_type == "stock":
                by_sector.setdefault(preset.sector, []).append(preset)
        results: dict[str, tuple[float, float]] = {}
        for members in by_sector.values():
            pe_values = sorted(q.pe for item in members if (q := quotes[item.code]).pe is not None and q.pe > 0)
            pb_values = sorted(q.pb for item in members if (q := quotes[item.code]).pb is not None and q.pb > 0)
            for item in members:
                quote = quotes[item.code]
                if quote.pe is not None and quote.pe > 0 and quote.pb is not None and quote.pb > 0:
                    results[item.code] = (
                        MarketScanner._percentile(quote.pe, pe_values),
                        MarketScanner._percentile(quote.pb, pb_values),
                    )
        return results

    @staticmethod
    def _percentile(value: float, values: list[float]) -> float:
        if not values:
            return .5
        return next((index / len(values) for index, candidate in enumerate(values) if candidate >= value), 1.0)
