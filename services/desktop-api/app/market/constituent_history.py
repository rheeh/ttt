from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.analysis.models import DailyBar
from app.market.daily_contract import parse_tencent_daily
from app.market.history_cache import HistoryBatch, HistoryCache
from app.market.trading_calendar import latest_session


class TencentConstituentHistoryProvider:
    """Fetch raw constituent bars for breadth and derived industry indices."""

    name = "tencent-qfq-constituent-history"

    def __init__(self, days: int = 150, max_workers: int = 6, timeout_seconds: float = 8, cache_path: Path | None = None, bars_provider=None):
        self.days = days
        self.max_workers = max_workers
        self.timeout_seconds = timeout_seconds
        self.cache = HistoryCache(cache_path) if cache_path else None
        self.bars_provider = bars_provider

    def fetch(self, codes: list[str]) -> dict[str, list[DailyBar]]:
        unique = list(dict.fromkeys(code for code in codes if code))
        result = HistoryBatch()
        expected = latest_session()
        pending = []
        for code in unique:
            cached = self.cache.get(code, expected, self.days) if self.cache and not self.bars_provider else None
            if cached:
                result[code] = cached
                result.cache_hits.append(code)
            else:
                pending.append(code)
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._fetch_one, code): code for code in pending}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    bars = future.result()
                except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
                    result.failures[code] = str(exc)
                    if self.cache:
                        self.cache.record(code, str(exc))
                    continue
                if bars:
                    result[code] = bars
                    if self.cache and not self.bars_provider:
                        self.cache.save(code, bars)
                else:
                    result.failures[code] = "不足60根有效的已完成日线"
                    if self.cache:
                        self.cache.record(code, result.failures[code])
        return result

    def _fetch_one(self, code: str) -> list[DailyBar]:
        provider_code = self._provider_code(code)
        if self.bars_provider:
            bars = self.bars_provider(provider_code, self.days)
            if getattr(bars, "error", None):
                raise ValueError(bars.error)
            return bars if len(bars) >= 60 else []
        query = urlencode({"param": f"{provider_code},day,,,{self.days},qfq"})
        request = Request(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + query,
            headers={"User-Agent": "Mozilla/5.0 ZhixingStockResearch/0.3", "Referer": "https://gu.qq.com/"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        bars = parse_tencent_daily(payload, provider_code)
        if len(bars) < 60:
            return []
        return bars

    @staticmethod
    def _provider_code(code: str) -> str:
        normalized = code.lower().strip()
        if normalized.startswith(("sh", "sz", "bj")):
            return normalized
        return ("sh" if normalized.startswith(("5", "6", "68", "9")) else "sz") + normalized.zfill(6)


def build_equal_weighted_industry_series(
    constituents: list[str], histories: dict[str, list[DailyBar]], *, minimum_members: int = 5,
    minimum_history_days: int = 120,
    expected_member_count: int | None = None,
) -> list[dict[str, Any]]:
    """Build a transparent equal-weighted index and true member breadth.

    The result is explicitly a derived index, not an official exchange or
    vendor industry index. Every metric is calculated from the same constituent
    close series, so MA20/MA60 breadth and new-high ratios share one date axis.
    """
    requested = list(dict.fromkeys(constituents))
    expected_count = max(len(requested), expected_member_count or 0)
    members = [code for code in requested if len(histories.get(code, [])) >= 60]
    if len(members) < minimum_members:
        return []
    by_code = {code: {bar.trade_date: bar for bar in histories[code]} for code in members}
    dates = sorted(set.intersection(*(set(rows) for rows in by_code.values())))
    if len(dates) < minimum_history_days:
        return []
    index_values: list[float] = [100.0]
    rows: list[dict[str, Any]] = []
    for position, trade_date in enumerate(dates):
        if position == 0:
            index_close = 100.0
        else:
            returns = []
            for code in members:
                previous = by_code[code].get(dates[position - 1])
                current = by_code[code].get(trade_date)
                if previous and current and previous.close > 0:
                    returns.append(current.close / previous.close - 1)
            if not returns:
                continue
            index_close = index_values[-1] * (1 + sum(returns) / len(returns))
            index_values.append(index_close)
        closes = [by_code[code][trade_date].close for code in members if trade_date in by_code[code]]
        advances = 0
        above20 = 0
        above60 = 0
        new_highs = 0
        volumes: list[float] = []
        for code in members:
            bars = histories[code]
            current = by_code[code].get(trade_date)
            if current is None:
                continue
            prior = [bar for bar in bars if bar.trade_date < trade_date]
            if prior and current.close > prior[-1].close:
                advances += 1
            if len(prior) >= 19 and current.close > sum(bar.close for bar in prior[-19:]) / 19:
                above20 += 1
            if len(prior) >= 59 and current.close > sum(bar.close for bar in prior[-59:]) / 59:
                above60 += 1
                if current.close >= max(bar.close for bar in prior[-59:]):
                    new_highs += 1
            volumes.append(current.volume)
        observed = len(closes)
        rows.append({
            "trade_date": trade_date,
            "close": round(index_close, 6),
            "advance_ratio_pct": round(advances / observed * 100, 2) if observed else None,
            "breadth_ma20_pct": round(above20 / observed * 100, 2) if observed else None,
            "breadth_ma60_pct": round(above60 / observed * 100, 2) if observed else None,
            "new_high_ratio_pct": round(new_highs / observed * 100, 2) if observed else None,
            "coverage_pct": round(observed / expected_count * 100, 2) if expected_count else None,
            "volume": sum(volumes) if volumes else None,
            "observed": observed,
            "member_count": expected_count,
            "missing_members": [code for code in requested if code not in members],
        })
    if len(rows) < 60:
        return []
    volumes = [row["volume"] for row in rows]
    closes = [row["close"] for row in rows]
    for index, row in enumerate(rows):
        row["return_5d_pct"] = round((closes[index] / closes[index - 5] - 1) * 100, 2) if index >= 5 else None
        row["return_20d_pct"] = round((closes[index] / closes[index - 20] - 1) * 100, 2) if index >= 20 else None
        row["return_60d_pct"] = round((closes[index] / closes[index - 60] - 1) * 100, 2) if index >= 60 else None
    for index, row in enumerate(rows):
        prior_volumes = [value for value in volumes[max(0, index - 20):index] if value is not None]
        average = sum(prior_volumes) / len(prior_volumes) if prior_volumes else 0
        row["volume_ratio"] = round(row["volume"] / average, 2) if average > 0 and row["volume"] is not None else None
    return rows
