from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from app.analysis.data_sources import _json_request_any
from app.models import IndustryRadarItem, IndustryRadarResponse


RULE_VERSION = "industry-radar-v1"


def _number(value: Any) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _field(row: dict[str, Any], *names: str) -> Any:
    return next((row[name] for name in names if name in row), None)


class IndustryRadarProvider:
    """Independent industry radar using AKShare industry data.

    This provider deliberately does not read the legacy stock pool. Missing
    history or breadth is surfaced as degraded instead of being synthesized
    from the 66-name example list.
    """

    name = "akshare-industry-radar"

    def fetch(self) -> IndustryRadarResponse:
        snapshot_at = datetime.now(timezone.utc)
        ak = None
        try:
            import akshare as ak
            frame = ak.stock_board_industry_name_em()
            rows = frame.to_dict("records")
        except Exception as exc:
            # AKShare currently hard-codes one Eastmoney host. Try the same
            # official endpoint through the rotating hosts before declaring the
            # radar unavailable.
            try:
                rows, endpoint = self._fetch_rows_direct()
                source = f"{self.name}+direct:{endpoint}"
            except Exception as direct_exc:
                return IndustryRadarResponse(
                    snapshot_at=snapshot_at, source=self.name, data_status="error",
                    coverage_count=0, coverage_total=0,
                    degraded_reasons=[f"行业列表暂时不可用（已尝试 AKShare 与备用节点）：{self._short_error(direct_exc)}"])
        else:
            source = self.name

        if not rows:
            return IndustryRadarResponse(
                snapshot_at=snapshot_at, source=source, data_status="error",
                coverage_count=0, coverage_total=0,
                degraded_reasons=["行业列表返回为空，未生成板块判断"])

        items: list[IndustryRadarItem] = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(self._build_one, ak, row, snapshot_at): row for row in rows}
            for future in as_completed(futures):
                try:
                    items.append(future.result())
                except Exception as exc:
                    row = futures[future]
                    name = str(_field(row, "板块名称", "名称") or "未知板块")
                    items.append(self._error_item(name, snapshot_at, self._short_error(exc)))
        items.sort(key=lambda item: item.score if item.score is not None else -1, reverse=True)
        usable = [item for item in items if item.score is not None and item.status != "error"]
        status = "ok" if usable and len(usable) == len(items) else "degraded" if usable else "error"
        reasons = [] if status == "ok" else [f"{len(usable)}/{len(items)} 个板块具备可评分历史数据"]
        return IndustryRadarResponse(
            snapshot_at=snapshot_at, source=source, data_status=status,
            coverage_count=len(usable), coverage_total=len(items),
            coverage_pct=round(len(usable) / len(items) * 100, 2) if items else None,
            building=sorted([item for item in items if item.stage in {"低位企稳", "底部改善"}], key=lambda x: x.score or -1, reverse=True)[:20],
            confirmed=sorted([item for item in items if item.stage == "突破确认"], key=lambda x: x.score or -1, reverse=True)[:20],
            overheated=sorted([item for item in items if item.stage == "高位拥挤"], key=lambda x: x.score or -1, reverse=True)[:20],
            other=[item for item in items if item.stage == "下跌中"][:20],
            degraded_reasons=reasons,
        )

    @classmethod
    def _fetch_rows_direct(cls) -> tuple[list[dict[str, Any]], str]:
        params = {
            "pn": 1, "pz": 100, "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": 2,
            "invt": 2, "fid": "f3", "fs": "m:90 t:2 f:!50",
            "fields": "f3,f14,f62,f104,f105",
        }
        hosts = ("17.push2.eastmoney.com", "push2.eastmoney.com", "push2his.eastmoney.com")
        urls = [f"https://{host}/api/qt/clist/get?{urlencode(params)}" for host in hosts]
        payload, endpoint = _json_request_any(urls, timeout=8)
        data = payload.get("data") or {}
        diff = data.get("diff") or []
        rows = list(diff.values()) if isinstance(diff, dict) else list(diff)
        normalized = [{"板块名称": row.get("f14"), "涨跌幅": row.get("f3"), "上涨家数": row.get("f104"), "下跌家数": row.get("f105")} for row in rows]
        return normalized, endpoint

    @staticmethod
    def _short_error(error: Exception) -> str:
        text = str(error).replace("\n", " ")
        return text if len(text) <= 220 else text[:217] + "..."

    def _build_one(self, ak: Any, row: dict[str, Any], fetched_at: datetime) -> IndustryRadarItem:
        name = str(_field(row, "板块名称", "名称") or "未知板块")
        change = _number(_field(row, "涨跌幅", "涨跌幅(%)"))
        try:
            if ak is None:
                raise RuntimeError("历史行情需要安装可选依赖 akshare")
            history = ak.stock_board_industry_hist_em(symbol=name, period="daily", adjust="")
            history_rows = history.to_dict("records")
            closes = [_number(_field(record, "收盘", "收盘价")) for record in history_rows]
            closes = [value for value in closes if value is not None and value > 0]
        except Exception as exc:
            return self._error_item(name, fetched_at, f"历史行情不可用：{self._short_error(exc)}")
        if len(closes) < 60:
            return self._error_item(name, fetched_at, f"历史行情不足（{len(closes)}/60）")
        latest = closes[-1]
        lookback = closes[-min(250, len(closes)):]
        high = max(lookback); low = min(lookback)
        position = (latest - low) / (high - low) if high > low else .5
        low_score = round(max(0, min(20, (1 - position) * 20)), 2)
        r5 = (latest / closes[-6] - 1) * 100
        r20 = (latest / closes[-21] - 1) * 100
        prior20 = (closes[-21] / closes[-41] - 1) * 100
        deceleration = max(0, min(20, 10 + (r5 - prior20) * 1.5))
        drawdown = (latest / high - 1) * 100
        breadth_up = int(_number(_field(row, "上涨家数")) or 0)
        breadth_down = int(_number(_field(row, "下跌家数")) or 0)
        members = breadth_up + breadth_down
        breadth = 25 * breadth_up / members if members else None
        volume_score = max(0, min(15, 7.5 + r5))
        relative_score = max(0, min(20, 10 + r5 - max(0, prior20)))
        score = round(low_score + deceleration + (breadth or 12.5) + volume_score + relative_score, 2)
        if position > .88 and r5 > 8:
            stage = "高位拥挤"
        elif r5 > 5 and latest > max(closes[-61:-1]):
            stage = "突破确认"
        elif score >= 62 and r5 >= -2:
            stage = "底部改善"
        elif score >= 48 and r5 >= -5:
            stage = "低位企稳"
        else:
            stage = "下跌中"
        evidence = [f"近一年位置约 {position * 100:.0f}%", f"近5日 {r5:+.2f}% / 近20日 {r20:+.2f}%"]
        if members:
            evidence.append(f"上涨家数 {breadth_up}/{members}")
        else:
            evidence.append("板块内部广度未接入")
        risks = ["板块历史与成分覆盖不足时不应升级阶段"] if not members else []
        return IndustryRadarItem(
            name=name, stage=stage, score=score, low_position_score=low_score,
            deceleration_score=round(deceleration, 2), breadth_score=round(breadth, 2) if breadth is not None else None,
            volume_price_score=round(volume_score, 2), relative_strength_score=round(relative_score, 2),
            change_pct=change, return_5d_pct=round(r5, 2), return_20d_pct=round(r20, 2),
            drawdown_1y_pct=round(drawdown, 2), up_count=breadth_up or None,
            down_count=breadth_down or None, constituent_count=members or None,
            coverage_pct=100 if members else None, evidence=evidence, risks=risks,
            status="ok" if members else "degraded", source=self.name, fetched_at=fetched_at,
        )

    @staticmethod
    def _error_item(name: str, fetched_at: datetime, error: str) -> IndustryRadarItem:
        return IndustryRadarItem(name=name, stage="下跌中", status="error", source="akshare-industry-radar", fetched_at=fetched_at, risks=[error])
