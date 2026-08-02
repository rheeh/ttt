from __future__ import annotations

import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.models import QuoteSnapshot, StockPreset


class TencentQuoteProvider:
    name = "tencent-qt"

    def __init__(self, timeout_seconds: float = 8, retries: int = 2, chunk_size: int = 50):
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.chunk_size = chunk_size

    def fetch(self, presets: list[StockPreset]) -> list[QuoteSnapshot]:
        by_code: dict[str, QuoteSnapshot] = {}
        for start in range(0, len(presets), self.chunk_size):
            chunk = presets[start:start + self.chunk_size]
            try:
                text = self._request([item.code for item in chunk])
                by_code.update(self.parse_response(text))
            except (HTTPError, URLError, TimeoutError, UnicodeError, ValueError) as exc:
                fetched_at = datetime.now(timezone.utc)
                for item in chunk:
                    by_code[item.code] = QuoteSnapshot(
                        stock_code=item.code, stock_name=item.name, fetched_at=fetched_at,
                        source=self.name, status="error", error=str(exc),
                    )
        fetched_at = datetime.now(timezone.utc)
        return [by_code.get(item.code) or QuoteSnapshot(
            stock_code=item.code, stock_name=item.name, fetched_at=fetched_at,
            source=self.name, status="error", error="data source returned no record",
        ) for item in presets]

    def _request(self, codes: list[str]) -> str:
        url = "https://qt.gtimg.cn/q=" + ",".join(codes)
        request = Request(url, headers={
            "User-Agent": "Mozilla/5.0 ZhixingStockResearch/0.2",
            "Referer": "https://gu.qq.com/",
        })
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    return response.read().decode("gbk")
            except (HTTPError, URLError, TimeoutError, UnicodeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(.25 * (attempt + 1))
        assert last_error is not None
        raise last_error

    @classmethod
    def parse_response(cls, text: str) -> dict[str, QuoteSnapshot]:
        fetched_at = datetime.now(timezone.utc)
        results: dict[str, QuoteSnapshot] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("v_") or '="' not in line:
                continue
            variable, payload = line.split('="', 1)
            fields = payload.rstrip('";').split("~")
            code = variable.removeprefix("v_").lower()
            if len(fields) < 47:
                results[code] = QuoteSnapshot(
                    stock_code=code, stock_name=fields[1] if len(fields) > 1 else "",
                    fetched_at=fetched_at, source=cls.name, status="error",
                    error=f"unexpected field count: {len(fields)}",
                )
                continue
            price = cls._number(fields[3])
            trade_at = cls._trade_datetime(fields[30])
            required = {
                "price": price, "change_pct": cls._number(fields[32]),
                "pe": cls._number(fields[39]), "pb": cls._number(fields[46]),
                "turnover_pct": cls._number(fields[38]), "amplitude_pct": cls._number(fields[43]),
            }
            # Undocumented Tencent extensions: p[68]/p[70]/p[71] have been
            # observed as current/5-day/10-day main-flow amounts in 万元.
            # Keep them separate from the formal five-level flow fields and
            # normalize to 亿元 for an explicitly labelled fallback source.
            extension_main = cls._scaled_fund_flow(fields[68]) if len(fields) > 68 else None
            extension_main_5d = cls._scaled_fund_flow(fields[70]) if len(fields) > 70 else None
            extension_main_10d = cls._scaled_fund_flow(fields[71]) if len(fields) > 71 else None
            amount = cls._scaled_amount(fields[37])
            extension_ratio = extension_main / (amount / 1e8) if extension_main is not None and amount and amount > 0 else None
            missing = [name for name, value in required.items() if value is None or (name in {"price", "pe", "pb"} and value <= 0)]
            missing.extend(["main_flow_ratio", "quality_score", "ma5", "ma10", "ma20"])
            status = "error" if price is None or price <= 0 else "degraded" if missing else "ok"
            results[code] = QuoteSnapshot(
                stock_code=code, stock_name=fields[1], price=price,
                previous_close=cls._number(fields[4]), open=cls._number(fields[5]),
                high=cls._number(fields[33]), low=cls._number(fields[34]),
                change_pct=required["change_pct"], turnover_pct=required["turnover_pct"],
                amplitude_pct=required["amplitude_pct"], pe=required["pe"], pb=required["pb"],
                volume=cls._number(fields[6]), amount=amount,
                main_inflow=extension_main, main_inflow_5d=extension_main_5d,
                main_inflow_10d=extension_main_10d, fund_flow_ratio_estimated=extension_ratio,
                trade_at=trade_at, fetched_at=fetched_at, source=cls.name,
                status=status, missing_fields=missing,
                error="invalid or missing latest price" if status == "error" else None,
            )
        return results

    @staticmethod
    def _number(value: str) -> float | None:
        try:
            return float(value) if value.strip() else None
        except ValueError:
            return None

    @classmethod
    def _scaled_amount(cls, value: str) -> float | None:
        number = cls._number(value)
        return number * 10_000 if number is not None else None

    @classmethod
    def _scaled_fund_flow(cls, value: str) -> float | None:
        number = cls._number(value)
        return number / 10_000 if number is not None else None

    @staticmethod
    def _trade_datetime(value: str) -> datetime | None:
        try:
            parsed = datetime.strptime(value, "%Y%m%d%H%M%S")
            return parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        except (TypeError, ValueError):
            return None
