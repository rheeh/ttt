from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import re
from typing import Any

from app.analysis.industry_stage import RULE_VERSION as STAGE_RULE_VERSION, classify_stage
from app.market.constituent_history import build_equal_weighted_industry_series
from app.market.trading_calendar import latest_session
from app.models import IndustryBenchmarkPoint, IndustryConstituent, IndustryHistoryPoint, IndustryRadarItem, IndustryRadarResponse


RULE_VERSION = STAGE_RULE_VERSION


def _number(value: Any) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _value(row: dict[str, Any], *names: str) -> Any:
    return next((row[name] for name in names if name in row), None)


def industry_taxonomy(name: str) -> str:
    """Keep non-industry Sina groups out of stage rankings by default."""
    special = ("次新", "昨日", "ST", "退市", "停牌", "亏损股", "新股")
    concept = ("概念", "主题", "指数", "板块")
    style = ("低价", "高价", "超跌", "高送转", "预盈预增")
    if any(token in name for token in special):
        return "special"
    if any(token in name for token in concept):
        return "concept"
    if any(token in name for token in style):
        return "style"
    return "industry"


def industry_id(name: str, taxonomy: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", name).strip("-").lower()
    return f"{taxonomy}:{slug or 'unknown'}"


class IndustryRadarProvider:
    """Fetch all Sina industry groups and their current breadth.

    The provider only fetches the current observation. Historical returns and
    stage labels are derived from SQLite observations in ``enrich_history``;
    this keeps the upstream adapter honest and makes the stage rules replayable.
    """

    name = "sina-industry-radar"

    def __init__(self, max_workers: int = 4, history_provider: Any | None = None):
        self.max_workers = max_workers
        self.history_provider = history_provider

    def fetch(self, *, include_history: bool = False) -> IndustryRadarResponse:
        snapshot_at = datetime.now(timezone.utc)
        try:
            import akshare as ak
            rows = ak.stock_sector_spot(indicator="新浪行业").to_dict("records")
        except Exception as exc:
            return IndustryRadarResponse(
                snapshot_at=snapshot_at, source=self.name, data_status="error",
                coverage_count=0, coverage_total=0, rule_version=RULE_VERSION,
                degraded_reasons=[f"新浪行业数据暂时不可用：{self._short_error(exc)}"],
            )

        items: list[IndustryRadarItem] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._build_one, ak, row, snapshot_at): row for row in rows}
            for future in as_completed(futures):
                row = futures[future]
                name = str(_value(row, "板块", "板块名称") or "未知板块")
                try:
                    items.append(future.result())
                except Exception as exc:
                    taxonomy = industry_taxonomy(name)
                    items.append(self._item(
                        name, snapshot_at, taxonomy=taxonomy, industry_key=industry_id(name, taxonomy),
                        error=self._short_error(exc),
                    ))

        benchmark_history = self._benchmark_history(ak)
        benchmark_return = self._benchmark_return_20d(benchmark_history)
        history_series: dict[str, list[IndustryHistoryPoint]] = {}
        history_failures: dict[str, str] = {}
        if include_history and self.history_provider is not None:
            enriched_items: list[IndustryRadarItem] = []
            for offset in range(0, len(items), 4):
                batch = items[offset:offset + 4]
                batch_industries = [item for item in batch if item.taxonomy == "industry"]
                histories = self.history_provider.fetch([stock.code for item in batch_industries for stock in item.constituents])
                history_failures.update(getattr(histories, "failures", {}))
                for item in batch:
                    if item.taxonomy != "industry":
                        enriched_items.append(item.model_copy(update={
                            "evidence": item.evidence + [f"分类 {item.taxonomy}，第一版不参与稳定行业阶段识别"],
                            "risks": item.risks + ["非严格行业分类，不纳入阶段排名"],
                        }))
                        continue
                    series = build_equal_weighted_industry_series(
                        [stock.code for stock in item.constituents], histories,
                        expected_member_count=item.constituent_count,
                    )
                    requested = list(dict.fromkeys(stock.code for stock in item.constituents))
                    missing = [code for code in requested if len(histories.get(code, [])) < 60]
                    expected_members = max(len(requested), item.constituent_count or 0)
                    item = item.model_copy(update={
                        "history_coverage_pct": round((len(requested) - len(missing)) / expected_members * 100, 2) if expected_members else 0,
                        "history_missing_codes": missing,
                        "history_semantics": "current_constituents_reconstruction",
                        "risks": item.risks + ["按当前成分回推历史，不代表当时行业成员；存在存续与分类变更偏差"] +
                                 ([f"历史缺失 {len(missing)}/{len(requested)} 只，已保留补采记录"] if missing else []) +
                                 ([] if series else ["共同交易日不足120日或有效成分少于5只，暂不判断阶段"]),
                    })
                    if series:
                        points = [IndustryHistoryPoint(
                            trade_date=row["trade_date"], close=row["close"],
                            return_5d_pct=row["return_5d_pct"], return_20d_pct=row["return_20d_pct"],
                            return_60d_pct=row["return_60d_pct"],
                            breadth_ma20_pct=row["breadth_ma20_pct"], breadth_ma60_pct=row["breadth_ma60_pct"],
                            advance_ratio_pct=row["advance_ratio_pct"], new_high_ratio_pct=row["new_high_ratio_pct"],
                            volume_ratio=row["volume_ratio"], breadth_source="constituent-qfq-history",
                            coverage_pct=row["coverage_pct"],
                        ) for row in series]
                        history_series[item.industry_id] = points
                        item = self._apply_index_series(item, series, benchmark_return, benchmark_history,
                                                        expected_trade_date=latest_session(), calendar_known=latest_session() is not None)
                        item = self._enrich_constituents(item, histories)
                    enriched_items.append(item)
            items = enriched_items
        reasons = ["当前快照已返回；板块历史K线样本不足，阶段识别将在累计60个交易日后启用"]
        if benchmark_return is None:
            reasons.append("沪深300历史基准暂不可用，暂不计算相对收益")
        result = self._response(items, snapshot_at, reasons, benchmark_return, benchmark_history, history_series)
        return result.model_copy(update={"history_failures": history_failures})

    def enrich_history(
        self, snapshot: IndustryRadarResponse, previous: list[IndustryRadarResponse]
    ) -> IndustryRadarResponse:
        """Calculate trailing metrics and conservative stages from stored days."""
        old_by_id: dict[str, list[IndustryRadarItem]] = {}
        for stored in reversed(previous):
            for item in self._all_items(stored):
                old_by_id.setdefault(item.industry_id or industry_id(item.name, item.taxonomy), []).append(item)

        enriched: list[IndustryRadarItem] = []
        for item in self._all_items(snapshot):
            if item.industry_id in snapshot.history_series:
                update: dict[str, Any] = {}
                if item.return_20d_pct is not None and snapshot.benchmark_return_20d_pct is not None:
                    update["relative_return_20d_pct"] = round(item.return_20d_pct - snapshot.benchmark_return_20d_pct, 2)
                if update:
                    item = item.model_copy(update=update)
                enriched.append(item)
                continue
            # A failed/insufficient reconstructed history must not be replaced
            # by an average of previous snapshots' advance ratios.
            if item.history_semantics == "current_constituents_reconstruction":
                enriched.append(item)
                continue
            old = old_by_id.get(item.industry_id, [])
            old_closes = [entry.proxy_close for entry in old if entry.proxy_close is not None]
            closes = old_closes + ([item.proxy_close] if item.proxy_close is not None else [])
            update: dict[str, Any] = {}
            breadth_history = [entry.advance_ratio_pct for entry in old if entry.advance_ratio_pct is not None]
            if item.advance_ratio_pct is not None:
                breadth_history.append(item.advance_ratio_pct)
            if len(breadth_history) >= 20:
                update["breadth_ma20_pct"] = round(sum(breadth_history[-20:]) / 20, 2)
            if len(breadth_history) >= 60:
                update["breadth_ma60_pct"] = round(sum(breadth_history[-60:]) / 60, 2)
            if item.proxy_close is not None and len(closes) >= 2:
                peak = max(closes[-252:])
                if peak > 0:
                    update["drawdown_1y_pct"] = round((item.proxy_close / peak - 1) * 100, 2)
            old_volumes = [entry.proxy_volume for entry in old if entry.proxy_volume is not None]
            if item.proxy_volume is not None and len(old_volumes) >= 20:
                average_volume = sum(old_volumes[-20:]) / 20
                if average_volume > 0:
                    update["volume_ratio"] = round(item.proxy_volume / average_volume, 2)
            if len(closes) >= 6:
                update["return_5d_pct"] = self._return_pct(closes, 5)
            if len(closes) >= 21:
                update["return_20d_pct"] = self._return_pct(closes, 20)
            if len(closes) >= 61:
                update["return_60d_pct"] = self._return_pct(closes, 60)
            relative_20 = None
            if update.get("return_20d_pct") is not None and snapshot.benchmark_return_20d_pct is not None:
                relative_20 = round(update["return_20d_pct"] - snapshot.benchmark_return_20d_pct, 2)
                update["relative_return_20d_pct"] = relative_20
            history_for_rule = closes[:-1] if item.proxy_close is not None else closes
            breadth20 = update.get("breadth_ma20_pct", item.breadth_ma20_pct)
            stage = classify_stage(
                close=item.proxy_close,
                history_closes=history_for_rule,
                return_5d_pct=update.get("return_5d_pct"),
                return_20d_pct=update.get("return_20d_pct"),
                relative_return_20d_pct=relative_20,
                breadth_ma20_pct=breadth20,
                volume_ratio=item.volume_ratio,
                confirmation_days=snapshot.confirmation_days,
            )
            update.update(stage.model_dump() if hasattr(stage, "model_dump") else {
                "stage": stage.stage, "score": stage.score,
                "evidence": item.evidence + stage.evidence,
                "risks": list(dict.fromkeys(item.risks + stage.risks)),
            })
            enriched.append(item.model_copy(update=update))

        result = self._response(
            enriched, snapshot.snapshot_at, snapshot.degraded_reasons,
            snapshot.benchmark_return_20d_pct, snapshot.benchmark_history, snapshot.history_series,
        )
        return result.model_copy(update={"history_failures": snapshot.history_failures})

    @staticmethod
    def _all_items(snapshot: IndustryRadarResponse) -> list[IndustryRadarItem]:
        seen: set[str] = set()
        items: list[IndustryRadarItem] = []
        for group in (snapshot.ranking, snapshot.building, snapshot.confirmed, snapshot.overheated, snapshot.other):
            for item in group:
                key = item.industry_id or industry_id(item.name, item.taxonomy)
                if key not in seen:
                    seen.add(key)
                    items.append(item)
        return items

    @staticmethod
    def _return_pct(closes: list[float], days: int) -> float | None:
        if len(closes) <= days or closes[-1 - days] <= 0:
            return None
        return round((closes[-1] / closes[-1 - days] - 1) * 100, 2)

    @staticmethod
    def _apply_index_series(
        item: IndustryRadarItem, series: list[dict[str, Any]], benchmark_return: float | None = None,
        benchmark_history: list[IndustryBenchmarkPoint] | None = None,
        *, expected_trade_date=None, calendar_known: bool = True,
    ) -> IndustryRadarItem:
        closes = [row["close"] for row in series]
        current = series[-1]
        return_5d = IndustryRadarProvider._return_pct(closes, 5)
        return_20d = IndustryRadarProvider._return_pct(closes, 20)
        return_60d = IndustryRadarProvider._return_pct(closes, 60)

        relative_return = round(return_20d - benchmark_return, 2) if return_20d is not None and benchmark_return is not None else None
        benchmark_by_date = {point.trade_date: point.close for point in (benchmark_history or [])}
        benchmark_dates = sorted(benchmark_by_date)

        def benchmark_return_at(trade_date: Any) -> float | None:
            if trade_date not in benchmark_dates:
                return None
            index = benchmark_dates.index(trade_date)
            if index < 20 or benchmark_by_date[benchmark_dates[index - 20]] <= 0:
                return None
            return (benchmark_by_date[trade_date] / benchmark_by_date[benchmark_dates[index - 20]] - 1) * 100

        def candidate_at(index: int) -> str:
            if index < 60 or not calendar_known or (series[index].get("coverage_pct") or 0) < 80:
                return "数据不足"
            point = series[index]
            result = classify_stage(
                close=point["close"], history_closes=closes[:index],
                return_5d_pct=IndustryRadarProvider._return_pct(closes[:index + 1], 5),
                return_20d_pct=IndustryRadarProvider._return_pct(closes[:index + 1], 20),
                relative_return_20d_pct=(
                    (IndustryRadarProvider._return_pct(closes[:index + 1], 20) or 0) - benchmark_return_at(point["trade_date"])
                    if benchmark_return_at(point["trade_date"]) is not None and IndustryRadarProvider._return_pct(closes[:index + 1], 20) is not None
                    else relative_return if index == len(series) - 1 else None
                ),
                breadth_ma20_pct=point["breadth_ma20_pct"], volume_ratio=point["volume_ratio"],
            )
            return result.stage

        candidates = [candidate_at(index) for index in range(len(series))]
        current_candidate = candidates[-1]
        confirmation_days = 0
        if current_candidate != "数据不足":
            for candidate in reversed(candidates):
                if candidate != current_candidate:
                    break
                confirmation_days += 1
        confirmed_stages: list[str] = []
        for index, candidate in enumerate(candidates):
            count = 0
            if candidate != "数据不足":
                for previous in reversed(candidates[:index + 1]):
                    if previous != candidate:
                        break
                    count += 1
            confirmed_stages.append(candidate if count >= 2 else "数据不足")
        run_start = len(confirmed_stages) - 1
        if current_candidate != "数据不足":
            while run_start > 0 and confirmed_stages[run_start - 1] == current_candidate:
                run_start -= 1
        previous_stage = next((stage for stage in reversed(confirmed_stages[:run_start]) if stage != "数据不足"), None)
        confirmed_stage = current_candidate if confirmation_days >= 2 else "数据不足"
        stale_history = expected_trade_date is not None and current["trade_date"] != expected_trade_date
        if stale_history:
            confirmed_stage = current_candidate = "数据不足"
            confirmation_days = 0
        prior_confirmed = confirmed_stages[-2] if len(confirmed_stages) >= 2 else "数据不足"
        stage_changed = confirmed_stage != "数据不足" and confirmed_stage != prior_confirmed
        improving_stages = {"低位企稳", "底部改善", "突破确认"}
        weakening_stages = {"下跌中", "高位拥挤"}
        direction = "improving" if confirmed_stage in improving_stages and confirmed_stage != previous_stage else "weakening" if confirmed_stage in weakening_stages and confirmed_stage != previous_stage else "neutral"
        peak = max(closes[-252:])
        update = {
            "stage": confirmed_stage,
            "stage_candidate": current_candidate,
            "stage_confirmation_days": confirmation_days,
            "stage_confirmed_at": series[run_start]["trade_date"] if confirmed_stage != "数据不足" else None,
            "trade_date": current["trade_date"],
            "previous_stage": previous_stage,
            "stage_changed": stage_changed,
            "signal_direction": direction,
            "history_days": len(series),
            "history_coverage_pct": current.get("coverage_pct"),
            "history_semantics": "current_constituents_reconstruction",
            "index_source": "derived-equal-weighted-constituents",
            "breadth_source": "constituent-qfq-history",
            "proxy_close": current["close"],
            "proxy_volume": current["volume"],
            "return_5d_pct": return_5d,
            "return_20d_pct": return_20d,
            "return_60d_pct": return_60d,
            "relative_return_20d_pct": relative_return,
            "drawdown_1y_pct": round((current["close"] / peak - 1) * 100, 2) if peak > 0 else None,
            "breadth_ma20_pct": current["breadth_ma20_pct"],
            "breadth_ma60_pct": current["breadth_ma60_pct"],
            "advance_ratio_pct": current["advance_ratio_pct"],
            "new_high_ratio_pct": current["new_high_ratio_pct"],
            "volume_ratio": current["volume_ratio"],
            "evidence": item.evidence + [
                f"指数来源：等权成分指数，历史 {len(series)} 个交易日",
                f"MA20宽度 {current['breadth_ma20_pct']:.1f}% · MA60宽度 {current['breadth_ma60_pct']:.1f}%",
                f"阶段候选 {current_candidate}，连续确认 {confirmation_days}/2 日",
            ],
            "risks": item.risks +
                     (["历史成分覆盖不足80%，暂不判断阶段"] if (current.get("coverage_pct") or 0) < 80 else []) +
                     ([f"历史停留在{current['trade_date']}，应有{expected_trade_date}，暂不判断阶段"] if stale_history else []) +
                     ([] if calendar_known else ["交易日历超出覆盖范围，暂不判断阶段"]),
        }
        return item.model_copy(update=update)

    @staticmethod
    def _enrich_constituents(item: IndustryRadarItem, histories: dict[str, list[Any]]) -> IndustryRadarItem:
        """Attach constituent-level evidence used by the drill-down groups."""
        enriched = []
        sector_return = item.return_20d_pct
        for constituent in item.constituents:
            bars = sorted(histories.get(constituent.code, []), key=lambda bar: bar.trade_date)
            closes = [bar.close for bar in bars]
            volumes = [bar.volume for bar in bars]
            return_5d = (closes[-1] / closes[-6] - 1) * 100 if len(closes) > 5 and closes[-6] > 0 else None
            return_20d = (closes[-1] / closes[-21] - 1) * 100 if len(closes) > 20 and closes[-21] > 0 else None
            ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
            previous_high = max(closes[-21:-1]) if len(closes) >= 21 else None
            previous_volumes = volumes[-21:-1] if len(volumes) >= 21 else []
            average_volume = sum(previous_volumes) / len(previous_volumes) if previous_volumes else None
            volume_ratio = volumes[-1] / average_volume if average_volume and volumes[-1] >= 0 else None
            enriched.append(constituent.model_copy(update={
                "return_5d_pct": round(return_5d, 2) if return_5d is not None else None,
                "return_20d_pct": round(return_20d, 2) if return_20d is not None else None,
                "relative_return_20d_pct": round(return_20d - sector_return, 2) if return_20d is not None and sector_return is not None else None,
                "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
                "ma20_above": bool(ma20 is not None and closes[-1] > ma20),
                "breakout_confirmed": bool(previous_high is not None and closes[-1] >= previous_high and (volume_ratio is None or volume_ratio >= 1.05)),
                "history_days": len(closes),
            }))
        return item.model_copy(update={"constituents": enriched})

    def _build_one(self, ak: Any, row: dict[str, Any], fetched_at: datetime) -> IndustryRadarItem:
        name = str(_value(row, "板块", "板块名称") or "未知板块")
        taxonomy = industry_taxonomy(name)
        key = industry_id(name, taxonomy)
        label = str(_value(row, "label", "代码") or "")
        change = _number(_value(row, "涨跌幅", "板块涨跌幅"))
        company_count = int(_number(_value(row, "公司家数", "成分股数量")) or 0)
        try:
            detail_rows = ak.stock_sector_detail(sector=label).to_dict("records")
            changes = [_number(_value(item, "changepercent", "涨跌幅")) for item in detail_rows]
            changes = [value for value in changes if value is not None]
            up_count = sum(value > 0 for value in changes)
            down_count = sum(value < 0 for value in changes)
            observed = len(changes)
            coverage = round(observed / company_count * 100, 2) if company_count else None
            advance_ratio = round(up_count / observed * 100, 2) if observed else None
            evidence = [f"当前涨跌幅 {change:+.2f}%" if change is not None else "当前涨跌幅缺失"]
            evidence.append(f"成分覆盖 {observed}/{company_count or '—'}")
            if observed:
                evidence.append(f"上涨 {up_count} 只、下跌 {down_count} 只")
            return self._item(
                name, fetched_at, taxonomy=taxonomy, industry_key=key, change=change,
                constituent_count=company_count or None, up_count=up_count or None,
                down_count=down_count or None, constituent_observed=observed,
                coverage_pct=coverage, advance_ratio_pct=advance_ratio,
                constituents=self._constituents(detail_rows), status="ok" if observed else "degraded",
                evidence=evidence,
                error="历史样本不足，暂不生成阶段评分",
            )
        except Exception as exc:
            return self._item(
                name, fetched_at, taxonomy=taxonomy, industry_key=key, change=change,
                constituent_count=company_count or None,
                evidence=[f"当前涨跌幅 {change:+.2f}%" if change is not None else "当前涨跌幅缺失"],
                error=f"成分详情不可用：{self._short_error(exc)}",
            )

    @staticmethod
    def _item(name: str, fetched_at: datetime, *, taxonomy: str = "industry", industry_key: str = "",
              change: float | None = None, up_count: int | None = None, down_count: int | None = None,
              constituent_count: int | None = None, coverage_pct: float | None = None,
              constituent_observed: int | None = None, advance_ratio_pct: float | None = None,
              proxy_close: float | None = None, proxy_volume: float | None = None,
              constituents: list[IndustryConstituent] | None = None, status: str = "degraded",
              evidence: list[str] | None = None, error: str | None = None) -> IndustryRadarItem:
        risks = [error] if error else ["历史样本不足，不能判断筑底或突破"]
        return IndustryRadarItem(
            industry_id=industry_key or industry_id(name, taxonomy), name=name, taxonomy=taxonomy,
            stage="数据不足", score=None, change_pct=change, up_count=up_count, down_count=down_count,
            constituent_count=constituent_count, constituent_observed=constituent_observed,
            coverage_pct=coverage_pct, advance_ratio_pct=advance_ratio_pct, proxy_close=proxy_close,
            proxy_volume=proxy_volume,
            constituents=constituents or [], evidence=evidence or [], risks=risks,
            status=status if status in {"ok", "degraded", "error"} else "degraded",
            source="sina-industry-radar", fetched_at=fetched_at,
        )

    @staticmethod
    def _response(
        items: list[IndustryRadarItem], snapshot_at: datetime, reasons: list[str],
        benchmark_return: float | None = None, benchmark_history: list[IndustryBenchmarkPoint] | None = None,
        history_series: dict[str, list[IndustryHistoryPoint]] | None = None,
    ) -> IndustryRadarResponse:
        items.sort(key=lambda item: item.change_pct if item.change_pct is not None else -999, reverse=True)
        detail_count = sum(item.status == "ok" for item in items)
        observed = sum(item.constituent_observed or 0 for item in items)
        expected = sum(item.constituent_count or 0 for item in items)
        taxonomy_counts: dict[str, int] = {}
        for item in items:
            taxonomy_counts[item.taxonomy] = taxonomy_counts.get(item.taxonomy, 0) + 1
        eligible = [item for item in items if item.taxonomy == "industry"]
        eligible.sort(key=lambda item: item.return_20d_pct if item.return_20d_pct is not None else -999, reverse=True)
        return IndustryRadarResponse(
            snapshot_at=snapshot_at, source=IndustryRadarProvider.name,
            data_status="ok" if detail_count == len(items) and items else "degraded",
            coverage_count=detail_count, coverage_total=len(items),
            coverage_pct=round(detail_count / len(items) * 100, 2) if items else None,
            detail_board_count=len(items), detail_constituent_observed=observed,
            detail_constituent_total=expected, rule_version=RULE_VERSION,
            last_success_trade_date=max((item.trade_date for item in items if item.trade_date), default=None),
            benchmark_return_20d_pct=benchmark_return,
            benchmark_history=benchmark_history or [],
            history_series=history_series or {},
            ranking=eligible[:100],
            building=[item for item in eligible if item.stage in {"低位企稳", "底部改善"}],
            confirmed=[item for item in eligible if item.stage == "突破确认"],
            overheated=[item for item in eligible if item.stage == "高位拥挤"],
            other=[item for item in items if item.stage == "数据不足"],
            taxonomy_counts=taxonomy_counts, degraded_reasons=reasons,
        )

    @staticmethod
    def _benchmark_history(ak: Any) -> list[IndustryBenchmarkPoint]:
        """Read沪深300 only when the installed AKShare exposes its index history."""
        try:
            frame = ak.stock_zh_index_daily(symbol="sh000300")
            rows = frame.to_dict("records")
            points: list[IndustryBenchmarkPoint] = []
            for row in rows:
                close = _number(_value(row, "close", "收盘", "收盘价"))
                raw_date = _value(row, "date", "日期", "交易日期")
                if close is None or close <= 0 or raw_date in (None, ""):
                    continue
                try:
                    trade_date = raw_date if hasattr(raw_date, "year") else datetime.fromisoformat(str(raw_date)).date()
                    points.append(IndustryBenchmarkPoint(trade_date=trade_date, close=close))
                except (TypeError, ValueError):
                    continue
            return points[-400:]
        except Exception:
            return []

    @staticmethod
    def _benchmark_return_20d(points: list[IndustryBenchmarkPoint]) -> float | None:
        closes = [point.close for point in points]
        if len(closes) <= 20:
            return None
        return IndustryRadarProvider._return_pct(closes, 20)

    @staticmethod
    def _short_error(error: Exception) -> str:
        text = str(error).replace("\n", " ")
        return text if len(text) <= 220 else text[:217] + "..."

    @staticmethod
    def _constituents(rows: list[dict[str, Any]]) -> list[IndustryConstituent]:
        constituents: list[IndustryConstituent] = []
        for row in rows:
            code = _value(row, "symbol", "代码", "股票代码", "code")
            name = _value(row, "name", "名称", "股票名称")
            if not code or not name:
                continue
            constituents.append(IndustryConstituent(
                code=str(code).strip(), name=str(name).strip(),
                change_pct=_number(_value(row, "changepercent", "涨跌幅")),
            ))
        return constituents
