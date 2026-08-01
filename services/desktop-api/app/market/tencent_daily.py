from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.models import DailyIndicators, StockPreset


class TencentDailyProvider:
    name = "tencent-qfq-day"

    def __init__(self, timeout_seconds: float = 8, max_workers: int = 6, days: int = 30):
        self.timeout_seconds = timeout_seconds
        self.max_workers = max_workers
        self.days = days

    def fetch(self, presets: list[StockPreset]) -> dict[str, DailyIndicators]:
        results: dict[str, DailyIndicators] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._fetch_one, item.code): item.code for item in presets}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    results[code] = future.result()
                except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                    results[code] = DailyIndicators(
                        stock_code=code, source=self.name, status="error", error=str(exc),
                    )
        return results

    def _fetch_one(self, code: str) -> DailyIndicators:
        query = urlencode({"param": f"{code},day,,,{self.days},qfq"})
        request = Request(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + query,
            headers={"User-Agent": "Mozilla/5.0 ZhixingStockResearch/0.2", "Referer": "https://gu.qq.com/"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("code") != 0:
            raise ValueError(payload.get("msg") or "daily endpoint returned an error")
        rows = payload.get("data", {}).get(code, {}).get("qfqday") or payload.get("data", {}).get(code, {}).get("day") or []
        return self.parse_rows(code, rows)

    @classmethod
    def parse_rows(cls, code: str, rows: list[list[str]]) -> DailyIndicators:
        valid: list[tuple[str, float]] = []
        for row in rows:
            if len(row) < 3:
                continue
            try:
                close = float(row[2])
            except (TypeError, ValueError):
                continue
            if close > 0:
                valid.append((str(row[0]), close))
        if len(valid) < 20:
            return DailyIndicators(
                stock_code=code, bar_count=len(valid),
                latest_trade_date=valid[-1][0] if valid else None,
                source=cls.name, status="error", error="fewer than 20 valid daily bars",
            )
        closes = [item[1] for item in valid]
        average = lambda days: round(sum(closes[-days:]) / days, 4)
        return DailyIndicators(
            stock_code=code, ma5=average(5), ma10=average(10), ma20=average(20),
            bar_count=len(valid), latest_trade_date=valid[-1][0], source=cls.name, status="ok",
        )
