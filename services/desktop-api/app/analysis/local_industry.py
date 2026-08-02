from __future__ import annotations

import time
from datetime import datetime, timezone

from app.analysis.data_sources import IndustryFacts
from app.market.scanner import StockPool
from app.market.tencent import TencentQuoteProvider


class LocalIndustryProvider:
    """Compute a transparent industry snapshot from the local mapping + Tencent.

    The mapping is only used to group stocks; it is not a replacement for a
    real-time industry database.  We deliberately leave main-flow fields empty
    because ordinary quotes cannot reconstruct five-level capital flow.
    """

    name = "local-tencent-industry"

    def __init__(self, pool: StockPool, quote_provider: TencentQuoteProvider, cache_seconds: int = 120):
        self.by_code = {item.code: item for item in pool.stocks}
        self.presets = list(pool.stocks)
        self.quote_provider = quote_provider
        self.cache_seconds = cache_seconds
        self._cache: tuple[float, dict[str, IndustryFacts]] | None = None

    def fetch(self, code: str) -> IndustryFacts:
        preset = self.by_code.get(code)
        if preset is None or not preset.sector or preset.sector == "其他":
            return IndustryFacts(
                source=self.name, endpoint="qt.gtimg.cn", status="error",
                error="本地行业映射缺失，未使用猜测行业",
            )
        try:
            facts = self._build()
            result = facts.get(preset.sector)
            if result is None:
                raise ValueError(f"本地行业映射无成分行情：{preset.sector}")
            return result
        except Exception as exc:
            return IndustryFacts(source=self.name, endpoint="qt.gtimg.cn", status="error", error=str(exc))

    def _build(self) -> dict[str, IndustryFacts]:
        now = time.time()
        if self._cache and now - self._cache[0] < self.cache_seconds:
            return self._cache[1]
        quotes = self.quote_provider.fetch(self.presets)
        grouped: dict[str, list] = {}
        for quote in quotes:
            preset = self.by_code.get(quote.stock_code)
            if preset is None or quote.status == "error" or quote.change_pct is None:
                continue
            grouped.setdefault(preset.sector, []).append(quote)
        averages = {
            sector: sum(item.change_pct for item in rows) / len(rows)
            for sector, rows in grouped.items() if rows
        }
        ordered = sorted(averages, key=lambda sector: averages[sector], reverse=True)
        facts: dict[str, IndustryFacts] = {}
        fetched_at = datetime.now(timezone.utc)
        for sector, rows in grouped.items():
            leaders = sorted((item for item in rows if item.change_pct is not None), key=lambda item: item.change_pct, reverse=True)
            facts[sector] = IndustryFacts(
                name=sector,
                rank=ordered.index(sector) + 1 if sector in ordered else None,
                total=len(ordered),
                change_pct=round(averages[sector], 4),
                constituent_count=len(rows),
                up_count=sum(item.change_pct > 0 for item in rows if item.change_pct is not None),
                down_count=sum(item.change_pct < 0 for item in rows if item.change_pct is not None),
                average_amount=round(sum(item.amount or 0 for item in rows) / 1e8, 4),
                leader_name=leaders[0].stock_name if leaders else None,
                leader_change_pct=leaders[0].change_pct if leaders else None,
                source=self.name,
                endpoint="qt.gtimg.cn",
                fetched_at=fetched_at,
                status="degraded",
                error="东方财富行业接口失败，使用本地行业映射 + 腾讯成分行情计算；主力资金缺失",
            )
        self._cache = (now, facts)
        return facts
