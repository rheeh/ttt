from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models import ScoreDimension, ScoreInput, ScoreResult


LABELS = {
    "valuation": "估值",
    "price_momentum": "价量",
    "sector": "板块",
    "capital_flow": "资金",
    "trend": "趋势",
    "risk": "风险",
    "quality": "扣非质量",
}


class StrategyEngine:
    def __init__(self, strategy_path: Path):
        self.path = strategy_path
        self.config = self._load(strategy_path)

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        thresholds = data["grade_thresholds"]
        if not thresholds["S"] > thresholds["A"] > thresholds["B"]:
            raise ValueError("grade thresholds must satisfy S > A > B")
        return data

    def score(self, item: ScoreInput) -> ScoreResult:
        dimensions = [
            self._valuation(item), self._price_momentum(item), self._sector(item),
            self._capital_flow(item), self._trend(item), self._risk(item), self._quality(item),
        ]
        total = sum(part.score for part in dimensions)
        rejected = self._rejected(item)
        return ScoreResult(
            stock_code=item.stock_code, stock_name=item.stock_name,
            strategy_id=self.config["id"], strategy_version=self.config["version"],
            total_score=total, grade=self._grade(total), eligible=not rejected,
            rejected_reasons=rejected, dimensions=dimensions,
        )

    @staticmethod
    def _dimension(name: str, score: int, *reasons: str) -> ScoreDimension:
        return ScoreDimension(name=name, label=LABELS[name], score=score, reasons=[r for r in reasons if r])

    def _valuation(self, x: ScoreInput) -> ScoreDimension:
        if x.pe > 100:
            pe_score, pe_reason = -6, "PE>100高估"
        elif x.pe_percentile < .30:
            pe_score, pe_reason = 6, "PE行业前30%"
        elif x.pe_percentile < .60:
            pe_score, pe_reason = 3, "PE行业30-60%"
        elif x.pe_percentile < .80:
            pe_score, pe_reason = -1, "PE行业60-80%"
        else:
            pe_score, pe_reason = -4, "PE行业后20%"
        if x.pb_percentile < .30:
            pb_score, pb_reason = 5, "PB行业前30%"
        elif x.pb_percentile < .60:
            pb_score, pb_reason = 2, "PB行业30-60%"
        elif x.pb_percentile < .80:
            pb_score, pb_reason = -1, "PB行业60-80%"
        else:
            pb_score, pb_reason = -3, "PB行业后20%"
        raw = pe_score + pb_score
        score = max(-3, raw)
        return self._dimension("valuation", score, pe_reason, pb_reason, "估值惩罚下限-3" if score != raw else "")

    def _price_momentum(self, x: ScoreInput) -> ScoreDimension:
        score, reasons = 0, []
        if 0 < x.change_pct < 3: score, reasons = 5, ["温和上涨"]
        elif 3 <= x.change_pct < 6: score, reasons = 3, ["强势上涨"]
        elif x.change_pct >= 6: score, reasons = -5, ["超买>6%"]
        elif x.change_pct < -3: score, reasons = -5, ["下跌>3%"]
        elif x.change_pct < 0: score, reasons = -2, ["微跌"]
        if x.change_pct > 0 and x.turnover_pct > 3: score += 3; reasons.append("放量上涨")
        elif x.change_pct < 0 and x.turnover_pct > 3: score -= 3; reasons.append("放量下跌")
        elif x.change_pct > 0 and x.turnover_pct < .5: score += 2; reasons.append("缩量上涨")
        if x.mode == "pre-market" and x.change_pct > 3: score -= 1; reasons.append("盘前抑制追强")
        elif x.mode == "review" and x.main_flow_ratio > 0: score += 1; reasons.append("复盘资金微调")
        return self._dimension("price_momentum", score, *reasons)

    def _sector(self, x: ScoreInput) -> ScoreDimension:
        if x.sector in self.config["preferred_sectors"]: score, reasons = 9, [f"{x.sector}偏好"]
        elif x.sector == "证券": score, reasons = 2, ["证券加分"]
        elif x.sector in self.config["avoided_sectors"]: score, reasons = -5, [f"{x.sector}回避"]
        else: score, reasons = 3, ["中性板块"]
        if x.in_rotation_pool: score += self.config["rotation_bonus"]; reasons.append("轮动池+4")
        if x.sector_change_pct > 5: score += 8; reasons.append("板块爆发+8")
        elif x.sector_change_pct > 3: score += 5; reasons.append("板块大涨+5")
        elif x.sector_change_pct > 1.5: score += 2; reasons.append("板块跑赢+2")
        elif x.sector_change_pct < -1.5: score -= 2; reasons.append("板块承压-2")
        return self._dimension("sector", score, *reasons)

    def _capital_flow(self, x: ScoreInput) -> ScoreDimension:
        if x.main_flow_ratio > .05: return self._dimension("capital_flow", 4, "主力净流入>5%")
        if x.main_flow_ratio > .02: return self._dimension("capital_flow", 2, "主力净流入>2%")
        if x.main_flow_ratio < -.05: return self._dimension("capital_flow", -4, "主力净流出>5%")
        if x.main_flow_ratio < -.02: return self._dimension("capital_flow", -2, "主力净流出>2%")
        return self._dimension("capital_flow", 0)

    def _trend(self, x: ScoreInput) -> ScoreDimension:
        if not all((x.ma5, x.ma10, x.ma20)): return self._dimension("trend", 0, "均线数据缺失")
        if x.price > x.ma5 > x.ma10 > x.ma20: return self._dimension("trend", 3, "多头排列")
        if x.price > x.ma5: return self._dimension("trend", 1, "站上MA5")
        if x.price < x.ma5 < x.ma10: return self._dimension("trend", -2, "MA5下穿MA10")
        if x.price < x.ma20: return self._dimension("trend", -3, "跌破MA20")
        return self._dimension("trend", 0)

    def _risk(self, x: ScoreInput) -> ScoreDimension:
        score, reasons = 0, []
        if x.turnover_pct > 10: score -= 5; reasons.append("换手>10%")
        elif x.turnover_pct > 5: score -= 2; reasons.append("换手偏大")
        if x.amplitude_pct > 8: score -= 3; reasons.append("振幅>8%")
        return self._dimension("risk", score, *reasons)

    def _quality(self, x: ScoreInput) -> ScoreDimension:
        score, reasons = x.quality_score, []
        if score: reasons.append(f"扣非质量{score:+d}")
        if score < 0 and x.sector_change_pct > 3:
            exemption = abs(score) // 2; score += exemption; reasons.append(f"强势板块豁免+{exemption}")
        return self._dimension("quality", score, *reasons)

    def _rejected(self, x: ScoreInput) -> list[str]:
        clean = x.stock_code.removeprefix("sh").removeprefix("sz")
        reasons = ["市场前缀被策略过滤"] if any(clean.startswith(p) for p in self.config["filters"]["exclude_prefixes"]) else []
        if x.is_st and self.config["filters"]["exclude_st"]: reasons.append("ST股被策略过滤")
        return reasons

    def _grade(self, score: int) -> str:
        levels = self.config["grade_thresholds"]
        return "S" if score >= levels["S"] else "A" if score >= levels["A"] else "B" if score >= levels["B"] else "C"

