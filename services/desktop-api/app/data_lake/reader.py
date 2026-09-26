from __future__ import annotations

import json
import re
from datetime import date, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from app.market.daily_contract import BarSeries, INDEX_SYMBOLS, parse_daily_rows
from app.market.trading_calendar import latest_session, market_now

SUPPORTED_VERSION = "0.11.0"
DATASETS = {
    "instruments": "证券名录", "trading_calendar": "交易日历", "daily_bars": "个股日线",
    "index_bars": "指数日线", "adj_factors": "复权因子",
    "financial_statement_items": "财务历史", "announcement_index": "公告索引",
    "industry_members": "行业成员历史",
}


def installed_version() -> str | None:
    try:
        return version("cnequity")
    except PackageNotFoundError:
        return None


def symbol_for(code: str) -> str:
    value = code.strip().upper()
    if re.fullmatch(r"(?:SH|SZ|BJ)\d{6}", value):
        return f"{value[2:]}.{value[:2]}"
    if re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", value):
        return value
    raise ValueError("股票代码需含市场，例如 sh600519 或 600519.SH")


class LakeReader:
    def __init__(self, root: Path):
        self.root = root

    def _require(self):
        if installed_version() != SUPPORTED_VERSION:
            raise ValueError(f"需要安装 cnequity=={SUPPORTED_VERSION}")
        if not (self.root / "meta").is_dir():
            raise ValueError("本地数据湖尚未采集")

    def _load(self, dataset, **kwargs):
        from cnequity.query import load
        try:
            return load(dataset, data_root=self.root, **kwargs)
        except Exception as exc:
            raise ValueError(f"本地{dataset}读取失败：{exc}") from exc

    def revisions(self, datasets: list[str]) -> dict:
        result = {}
        for dataset in datasets:
            path = self.root / "meta" / "revisions" / dataset / "current.json"
            if path.exists():
                payload = json.loads(path.read_text())
                result[dataset] = payload.get("revision_id") or payload["revision"]
        return result

    def bars(self, code: str, days: int = 252) -> BarSeries:
        self._require()
        index = code.lower() in INDEX_SYMBOLS
        dataset = "index_bars" if index else "daily_bars"
        end = latest_session()
        if end is None:
            raise ValueError("交易日历范围未知，暂不采用本地日线")
        revisions = self.revisions([dataset] if index else [dataset, "adj_factors"])
        frame = self._load(dataset, symbols=[symbol_for(code)], start=end - timedelta(days=days * 2 + 60),
                     end=end, adjust=None if index else "qfq", strict_adj=not index,
                     revision_map=revisions or None)
        if index and "frequency" in frame.columns:
            frame = frame.filter(frame["frequency"] == "1d")
        frame = frame.sort("trade_date").tail(days)
        if frame.is_empty():
            raise ValueError("本地数据湖尚未覆盖该股票")
        if not index and ("adj_is_exact" not in frame.columns or not frame["adj_is_exact"].fill_null(False).all()):
            raise ValueError("本地复权因子覆盖不完整")
        prefix = "" if index else "adj_"
        rows = [[row["trade_date"], row[prefix + "open"], row[prefix + "close"],
                 row[prefix + "high"], row[prefix + "low"], row["volume"]] for row in frame.to_dicts()]
        bars = BarSeries(parse_daily_rows(rows), adjustment="index_points" if index else "qfq")
        bars.source = "cnequity-local"
        bars.contract_version = "cnequity-0.11.0-daily-v1"
        # Index upstream units differ from equity shares and between vendors.
        bars.volume_unit = "cnequity_index_native" if index else "shares"
        bars.adjustment_anchor = end.isoformat() if not index else None
        bars.revisions = revisions
        bars.upstream_sources = sorted(set(frame["source"].drop_nulls().to_list()))
        if "fetched_at" in frame.columns:
            bars.fetched_at = frame["fetched_at"].max().isoformat()
        return bars

    def records(self, dataset: str, *, code: str | None = None, start: date | None = None,
                end: date | None = None, as_of: date | None = None, limit: int = 200) -> list[dict]:
        self._require()
        if dataset not in DATASETS:
            raise ValueError("不支持的数据集")
        kwargs = {"symbols": [symbol_for(code)]} if code else {}
        if dataset in {"financial_statement_items", "announcement_index"}:
            kwargs.update(as_of=as_of or market_now().date(), pit_mode="best_effort")
        frame = self._load(dataset, start=start, end=end, **kwargs)
        sort = next((key for key in ("trade_date", "announce_date", "as_of_date", "report_period") if key in frame.columns), None)
        if sort:
            frame = frame.sort(sort, descending=True)
        return frame.head(limit).to_dicts()

    def catalog(self) -> list[dict]:
        self._require()
        from cnequity.query import list_datasets
        rows = list_datasets(data_root=self.root).to_dicts()
        return [{**row, "label": DATASETS[row["dataset"]]} for row in rows if row["dataset"] in DATASETS]

    def finance(self, code: str):
        from app.analysis.data_sources import FinanceFacts
        rows = self.records("financial_statement_items", code=code, limit=1000)
        if not rows:
            raise ValueError("本地尚无财务历史")
        period = max(str(row["report_period"]) for row in rows)
        current = [row for row in rows if str(row["report_period"]) == period]
        values = {row["item_code"]: row["item_value"] for row in current}
        if not any(values.get(key) is not None for key in ("revenue_yoy", "net_profit_yoy", "roe")):
            raise ValueError("本地最新财报缺少研究所需指标")
        year, quarter = int(period[:4]), int(period[-1])
        report_date = date(year, quarter * 3, (31, 30, 30, 31)[quarter - 1])
        return FinanceFacts(
            history_semantics="versioned_financial_statements", pit_quality="reconstructed",
            report_date=report_date.isoformat(), notice_date=max(str(row["announce_date"]) for row in current),
            revenue=values.get("revenue"), profit=values.get("net_profit"),
            revenue_yoy=values.get("revenue_yoy"), profit_yoy=values.get("net_profit_yoy"), roe=values.get("roe"),
            source="cnequity-finance", fetched_at=max(row["fetched_at"] for row in current), status="ok",
        )
