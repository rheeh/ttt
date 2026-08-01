from __future__ import annotations

import importlib.util
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from app.analysis.data_sources import EastmoneyFinanceProvider, EastmoneyFundFlowProvider, EastmoneyIndustryProvider, EastmoneyNewsProvider
from app.market.akshare import AkshareQuoteProvider
from app.market.tencent import TencentQuoteProvider
from app.models import DataSourceHealth, DataSourceHealthResponse, StockPreset


class DataSourceHealthService:
    def __init__(self, repository: Any, timeout_seconds: float = 5):
        self.repository = repository
        self.timeout_seconds = timeout_seconds

    def test_all(self, preset: StockPreset | None = None) -> DataSourceHealthResponse:
        preset = preset or StockPreset(secid="sh600519", code="sh600519", name="贵州茅台", sector="食品饮料")
        checks: list[tuple[str, str, Callable[[], Any], bool]] = [
            ("tencent-qt", "行情", lambda: TencentQuoteProvider(timeout_seconds=self.timeout_seconds).fetch([preset])[0], True),
            ("akshare-spot-em", "行情备用", lambda: AkshareQuoteProvider().fetch([preset])[0], importlib.util.find_spec("akshare") is not None),
            ("eastmoney-fflow", "东方财富", lambda: EastmoneyFundFlowProvider(self.timeout_seconds).fetch(preset.code), True),
            ("eastmoney-finance", "东方财富", lambda: EastmoneyFinanceProvider(self.timeout_seconds).fetch(preset.code), True),
            ("eastmoney-industry", "东方财富", lambda: EastmoneyIndustryProvider(self.timeout_seconds).fetch(preset.code), True),
            ("eastmoney-news", "东方财富", lambda: EastmoneyNewsProvider(self.timeout_seconds).fetch(preset.name, limit=1), True),
        ]
        with ThreadPoolExecutor(max_workers=len(checks)) as executor:
            futures = {source: executor.submit(self._check, source, category, function, installed) for source, category, function, installed in checks}
            results = [futures[source].result() for source, _, _, _ in checks]
        checked_at = max((item.checked_at for item in results), default=None)
        return DataSourceHealthResponse(checked_at=checked_at, sources=results)

    def _check(self, source: str, category: str, function: Callable[[], Any], installed: bool) -> DataSourceHealth:
        checked_at = datetime.now(timezone.utc)
        previous = next((item for item in self.repository.list_source_health() if item.source == source), None)
        if not installed:
            result = DataSourceHealth(source=source, category=category, installed=False, accessible=False, valid=False,
                                      status="unavailable", checked_at=checked_at, last_success_at=previous.last_success_at if previous else None,
                                      error="未安装 AKShare，可选安装 requirements-optional.txt")
            self.repository.save_source_health(result)
            return result
        started = time.perf_counter()
        try:
            payload = function()
            response_ms = int((time.perf_counter() - started) * 1000)
            status = getattr(payload, "status", "error")
            valid = status in {"ok", "degraded"} and self._has_valid_data(payload)
            health_status = "ok" if status == "ok" and valid else "degraded" if valid else "error"
            result = DataSourceHealth(
                source=source, category=category, installed=True, accessible=status != "error", valid=valid,
                status=health_status, checked_at=checked_at, response_ms=response_ms,
                last_success_at=checked_at if valid else previous.last_success_at if previous else None,
                error=getattr(payload, "error", None), details=f"payload_status={status}",
            )
        except Exception as exc:
            result = DataSourceHealth(source=source, category=category, installed=True, accessible=False, valid=False,
                                      status="error", checked_at=checked_at, response_ms=int((time.perf_counter() - started) * 1000),
                                      last_success_at=previous.last_success_at if previous else None, error=str(exc))
        self.repository.save_source_health(result)
        return result

    @staticmethod
    def _has_valid_data(payload: Any) -> bool:
        if hasattr(payload, "items"):
            return bool(payload.items)
        return any(getattr(payload, field, None) is not None for field in ("price", "revenue", "main_inflow", "rank", "revenue_yoy"))
