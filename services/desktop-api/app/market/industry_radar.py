from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from app.models import IndustryRadarItem, IndustryRadarResponse


RULE_VERSION = "industry-radar-v1-sina"


def _number(value: Any) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _value(row: dict[str, Any], *names: str) -> Any:
    return next((row[name] for name in names if name in row), None)


class IndustryRadarProvider:
    """Industry radar backed by Sina industry data through AKShare.

    This is intentionally separate from the Eastmoney adapters used by some
    individual-stock enrichment fields. Sina's industry endpoint supplies the
    current board snapshot and constituents. It does not supply board history,
    so this provider never upgrades a board to bottoming or breakout without
    historical evidence.
    """

    name = "sina-industry-radar"

    def fetch(self) -> IndustryRadarResponse:
        snapshot_at = datetime.now(timezone.utc)
        try:
            import akshare as ak
            frame = ak.stock_sector_spot(indicator="新浪行业")
            rows = frame.to_dict("records")
        except Exception as exc:
            return IndustryRadarResponse(
                snapshot_at=snapshot_at, source=self.name, data_status="error",
                coverage_count=0, coverage_total=0,
                rule_version=RULE_VERSION,
                degraded_reasons=[f"新浪行业数据暂时不可用：{self._short_error(exc)}"],
            )

        # Sina's constituent endpoint is one request per board. Keep the
        # detailed breadth sample bounded so one refresh cannot become a
        # dozens-of-requests timeout; the remaining boards retain their
        # current snapshot but are explicitly marked as lacking breadth.
        detail_rows = rows[:12]
        items: list[IndustryRadarItem] = [self._current_only_item(row, snapshot_at) for row in rows[12:]]
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(self._build_one, ak, row, snapshot_at): row for row in detail_rows}
            for future in as_completed(futures):
                row = futures[future]
                name = str(_value(row, "板块", "板块名称") or "未知板块")
                try:
                    items.append(future.result())
                except Exception as exc:
                    items.append(self._item(name, snapshot_at, error=self._short_error(exc)))

        items.sort(key=lambda item: item.change_pct if item.change_pct is not None else -999, reverse=True)
        detail_count = sum(item.status == "ok" for item in items)
        return IndustryRadarResponse(
            snapshot_at=snapshot_at, source=self.name,
            data_status="degraded", coverage_count=detail_count,
            coverage_total=len(items), coverage_pct=round(detail_count / len(items) * 100, 2) if items else None,
            rule_version=RULE_VERSION,
            # No Sina board history is available here, therefore these are
            # deliberately kept separate from confirmed bottoming signals.
            building=[], confirmed=[], overheated=[],
            other=[item for item in items if item.stage == "数据不足"][:100],
            degraded_reasons=["新浪行业当前快照已返回；板块历史K线尚未接入，因此暂不生成筑底/突破评分"],
        )

    @staticmethod
    def _current_only_item(row: dict[str, Any], fetched_at: datetime) -> IndustryRadarItem:
        name = str(_value(row, "板块", "板块名称") or "未知板块")
        change = _number(_value(row, "涨跌幅", "板块涨跌幅"))
        count = int(_number(_value(row, "公司家数", "成分股数量")) or 0)
        return IndustryRadarProvider._item(
            name, fetched_at, change=change, constituent_count=count or None,
            evidence=[f"当前涨跌幅 {change:+.2f}%" if change is not None else "当前涨跌幅缺失", "未请求成分详情（受请求上限保护）"],
            error="当前仅有新浪行业快照，未取得成分广度和历史K线",
        )

    def _build_one(self, ak: Any, row: dict[str, Any], fetched_at: datetime) -> IndustryRadarItem:
        name = str(_value(row, "板块", "板块名称") or "未知板块")
        label = str(_value(row, "label", "代码") or "")
        change = _number(_value(row, "涨跌幅", "板块涨跌幅"))
        company_count = int(_number(_value(row, "公司家数", "成分股数量")) or 0)
        try:
            detail = ak.stock_sector_detail(sector=label)
            detail_rows = detail.to_dict("records")
            changes = [_number(_value(item, "changepercent", "涨跌幅")) for item in detail_rows]
            changes = [value for value in changes if value is not None]
            up_count = sum(value > 0 for value in changes)
            down_count = sum(value < 0 for value in changes)
            observed = len(changes)
            coverage = round(observed / company_count * 100, 2) if company_count else None
            evidence = [f"当前涨跌幅 {change:+.2f}%" if change is not None else "当前涨跌幅缺失"]
            evidence.append(f"成分覆盖 {observed}/{company_count or '—'}")
            if observed:
                evidence.append(f"上涨 {up_count} 只、下跌 {down_count} 只")
            return self._item(
                name, fetched_at, change=change, up_count=up_count or None,
                down_count=down_count or None, constituent_count=company_count or None,
                coverage_pct=coverage, status="ok" if observed else "degraded",
                evidence=evidence,
                error="新浪行业接口未提供板块历史K线，当前不生成阶段评分",
            )
        except Exception as exc:
            return self._item(
                name, fetched_at, change=change, constituent_count=company_count or None,
                evidence=[f"当前涨跌幅 {change:+.2f}%" if change is not None else "当前涨跌幅缺失"],
                error=f"成分详情不可用：{self._short_error(exc)}",
            )

    @staticmethod
    def _item(name: str, fetched_at: datetime, *, change: float | None = None,
              up_count: int | None = None, down_count: int | None = None,
              constituent_count: int | None = None, coverage_pct: float | None = None,
              status: str = "degraded", evidence: list[str] | None = None,
              error: str | None = None) -> IndustryRadarItem:
        risks = [error] if error else ["缺少板块历史K线，不能判断筑底或突破"]
        return IndustryRadarItem(
            name=name, stage="数据不足", score=None, change_pct=change,
            up_count=up_count, down_count=down_count, constituent_count=constituent_count,
            coverage_pct=coverage_pct, evidence=evidence or [], risks=risks,
            status=status if status in {"ok", "degraded", "error"} else "degraded",
            source="sina-industry-radar", fetched_at=fetched_at,
        )

    @staticmethod
    def _short_error(error: Exception) -> str:
        text = str(error).replace("\n", " ")
        return text if len(text) <= 220 else text[:217] + "..."
