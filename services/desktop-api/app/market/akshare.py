from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.models import DailyIndicators, QuoteSnapshot, StockPreset


class AkshareQuoteProvider:
    """Optional AKShare spot fallback.

    AKShare is intentionally imported lazily: the normal Tencent path keeps the
    desktop app lightweight, while users who install ``akshare`` get a second
    public source when the primary quote is unavailable.
    """

    name = "akshare-spot-em"

    def fetch(self, presets: list[StockPreset]) -> list[QuoteSnapshot]:
        try:
            import akshare as ak

            rows = ak.stock_zh_a_spot_em().to_dict("records")
            by_code = {str(row.get("代码") or "").zfill(6): row for row in rows}
        except Exception as exc:  # optional dependency and remote failures are data-source errors
            return [self._error(item, str(exc)) for item in presets]
        fetched_at = datetime.now(timezone.utc)
        return [self._parse(item, by_code.get(item.code[2:]), fetched_at) for item in presets]

    @classmethod
    def _parse(cls, preset: StockPreset, row: dict[str, Any] | None, fetched_at: datetime) -> QuoteSnapshot:
        if row is None:
            return cls._error(preset, "AKShare spot row not found", fetched_at)
        price = cls._number(row.get("最新价"))
        missing = [field for field, value in {
            "price": price,
            "change_pct": cls._number(row.get("涨跌幅")),
            "turnover_pct": cls._number(row.get("换手率")),
            "amplitude_pct": cls._number(row.get("振幅")),
            "pe": cls._number(row.get("市盈率-动态")),
            "pb": cls._number(row.get("市净率")),
        }.items() if value is None or (field in {"price", "pe", "pb"} and value <= 0)]
        missing.extend(["main_flow_ratio", "quality_score", "ma5", "ma10", "ma20"])
        status = "error" if price is None or price <= 0 else "degraded"
        return QuoteSnapshot(
            stock_code=preset.code, stock_name=str(row.get("名称") or preset.name), price=price,
            change_pct=cls._number(row.get("涨跌幅")), turnover_pct=cls._number(row.get("换手率")),
            amplitude_pct=cls._number(row.get("振幅")), pe=cls._number(row.get("市盈率-动态")),
            pb=cls._number(row.get("市净率")), fetched_at=fetched_at, source=cls.name,
            status=status, missing_fields=missing,
            error="invalid or missing latest price" if status == "error" else None,
        )

    @staticmethod
    def _error(preset: StockPreset, error: str, fetched_at: datetime | None = None) -> QuoteSnapshot:
        return QuoteSnapshot(
            stock_code=preset.code, stock_name=preset.name, fetched_at=fetched_at or datetime.now(timezone.utc),
            source=AkshareQuoteProvider.name, status="error", error=error,
        )

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value) if value not in (None, "", "-") else None
        except (TypeError, ValueError):
            return None


class FallbackQuoteProvider:
    """Use the primary quote source and fill core gaps from AKShare."""

    name = "tencent-qt+akshare-spot-em"

    def __init__(self, primary: Any, fallback: AkshareQuoteProvider | None = None):
        self.primary = primary
        self.fallback = fallback or AkshareQuoteProvider()

    def fetch(self, presets: list[StockPreset]) -> list[QuoteSnapshot]:
        primary = self.primary.fetch(presets)
        gaps = [quote for quote in primary if self._needs_fallback(quote)]
        if not gaps:
            return primary
        fallback_by_code = {quote.stock_code: quote for quote in self.fallback.fetch([item for item in presets if item.code in {gap.stock_code for gap in gaps}])}
        return [self._merge(quote, fallback_by_code.get(quote.stock_code)) for quote in primary]

    @staticmethod
    def _needs_fallback(quote: QuoteSnapshot) -> bool:
        return quote.status == "error" or any(field in quote.missing_fields for field in ("price", "change_pct", "pe", "pb"))

    @staticmethod
    def _merge(primary: QuoteSnapshot, fallback: QuoteSnapshot | None) -> QuoteSnapshot:
        if fallback is None or fallback.status == "error":
            return primary
        updates: dict[str, Any] = {field: getattr(fallback, field) for field in ("stock_name", "price", "change_pct", "turnover_pct", "amplitude_pct", "pe", "pb") if getattr(primary, field) is None and getattr(fallback, field) is not None}
        missing = [field for field in sorted(set(primary.missing_fields + fallback.missing_fields)) if getattr(primary, field, None) is None and getattr(fallback, field, None) is None]
        price = updates.get("price", primary.price)
        status = "error" if price is None or price <= 0 else "degraded" if missing else "ok"
        updates.update({"missing_fields": missing, "status": status, "source": f"{primary.source}+{fallback.source}", "error": None if status != "error" else primary.error})
        return primary.model_copy(update=updates)


class AkshareDailyProvider:
    name = "akshare-qfq-day"

    def __init__(self, days: int = 40):
        self.days = days

    def fetch(self, presets: list[StockPreset]) -> dict[str, DailyIndicators]:
        try:
            import akshare as ak
        except ImportError as exc:
            return {item.code: DailyIndicators(stock_code=item.code, source=self.name, status="error", error=str(exc)) for item in presets}
        result: dict[str, DailyIndicators] = {}
        start = (date.today() - timedelta(days=self.days * 3)).strftime("%Y%m%d")
        end = date.today().strftime("%Y%m%d")
        for item in presets:
            try:
                frame = ak.stock_zh_a_hist(symbol=item.code[2:], period="daily", start_date=start, end_date=end, adjust="qfq")
                rows = frame.to_dict("records")
                closes = [float(row["收盘"]) for row in rows if row.get("收盘") not in (None, "-") and float(row["收盘"]) > 0]
                dates = [str(row.get("日期")) for row in rows if row.get("收盘") not in (None, "-")]
                if len(closes) < 20:
                    raise ValueError("fewer than 20 valid daily bars")
                result[item.code] = DailyIndicators(
                    stock_code=item.code, ma5=round(sum(closes[-5:]) / 5, 4), ma10=round(sum(closes[-10:]) / 10, 4),
                    ma20=round(sum(closes[-20:]) / 20, 4), bar_count=len(closes), latest_trade_date=dates[-1] if dates else None,
                    source=self.name, status="ok",
                )
            except Exception as exc:
                result[item.code] = DailyIndicators(stock_code=item.code, source=self.name, status="error", error=str(exc))
        return result


class FallbackHistoryProvider:
    name = "tencent-qfq-day+akshare-qfq-day"

    def __init__(self, primary: Any, fallback: AkshareDailyProvider | None = None):
        self.primary = primary
        self.fallback = fallback or AkshareDailyProvider()

    def fetch(self, presets: list[StockPreset]) -> dict[str, DailyIndicators]:
        primary = self.primary.fetch(presets)
        missing = [item for item in presets if primary.get(item.code) is None or primary[item.code].status == "error"]
        if not missing:
            return primary
        backup = self.fallback.fetch(missing)
        for item in missing:
            if backup.get(item.code) and backup[item.code].status == "ok":
                primary[item.code] = backup[item.code]
        return primary
