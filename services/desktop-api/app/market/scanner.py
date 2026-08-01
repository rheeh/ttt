from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from app.models import (
    MarketScanItem, MarketScanResponse, PoolResponse, QuoteSnapshot,
    ScoreInput, StockPreset,
)
from app.scoring import StrategyEngine


class QuoteProvider(Protocol):
    name: str
    def fetch(self, presets: list[StockPreset]) -> list[QuoteSnapshot]: ...


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
    def __init__(self, pool: StockPool, provider: QuoteProvider, engine: StrategyEngine):
        self.pool = pool
        self.provider = provider
        self.engine = engine

    def scan(self, include_etfs: bool = False, limit: int | None = None) -> MarketScanResponse:
        started_at = datetime.now(timezone.utc)
        presets = list(self.pool.stocks)
        if include_etfs:
            presets.extend(self.pool.etfs)
        if limit is not None:
            presets = presets[:limit]
        quotes = self.provider.fetch(presets)
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
                ))
            items.append(MarketScanItem(preset=preset, quote=quote, score=score))
        items.sort(key=lambda item: item.score.total_score if item.score else -10_000, reverse=True)
        completed_at = datetime.now(timezone.utc)
        return MarketScanResponse(
            started_at=started_at, completed_at=completed_at, source=self.provider.name,
            total=len(items), succeeded=sum(item.quote.status != "error" for item in items),
            degraded=sum(item.quote.status == "degraded" for item in items),
            failed=sum(item.quote.status == "error" for item in items), items=items,
        )

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

