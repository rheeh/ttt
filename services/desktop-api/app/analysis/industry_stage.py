from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RULE_VERSION = "industry-stage-v1.0.0"
IndustryStage = Literal["下跌中", "低位企稳", "底部改善", "突破确认", "高位拥挤", "数据不足"]


@dataclass(frozen=True)
class StageEvidence:
    stage: IndustryStage
    score: float | None
    evidence: list[str]
    risks: list[str]


def classify_stage(
    *,
    close: float | None,
    history_closes: list[float],
    return_5d_pct: float | None,
    return_20d_pct: float | None,
    relative_return_20d_pct: float | None,
    breadth_ma20_pct: float | None,
    volume_ratio: float | None,
    confirmation_days: int = 2,
) -> StageEvidence:
    """Classify an industry using explicit, deliberately conservative rules.

    The rule refuses to classify a board until 60 observations and a usable
    proxy close exist. This prevents the current snapshot from being presented
    as a historical bottom or breakout signal.
    """
    if close is None or len(history_closes) < 60:
        return StageEvidence(
            stage="数据不足", score=None,
            evidence=[f"历史样本 {len(history_closes)}/60 个交易日"],
            risks=["未达到60个交易日历史要求，暂不判断阶段"],
        )

    ma20 = sum(history_closes[-20:]) / 20
    ma60 = sum(history_closes[-60:]) / 60
    low60 = min(history_closes[-60:])
    high60 = max(history_closes[-60:])
    position = (close - low60) / (high60 - low60) if high60 > low60 else 0.5
    prior_ma20 = sum(history_closes[-21:-1]) / 20 if len(history_closes) >= 61 else None
    ma20_rising = prior_ma20 is not None and ma20 >= prior_ma20
    relative_positive = relative_return_20d_pct is not None and relative_return_20d_pct > 0
    breadth_improving = breadth_ma20_pct is not None and breadth_ma20_pct >= 50
    breakout = close > max(history_closes[-20:]) and volume_ratio is not None and volume_ratio >= 1.2
    high_crowded = position >= 0.85 and breadth_ma20_pct is not None and breadth_ma20_pct >= 75

    evidence = [
        f"近60日位置 {position * 100:.0f}%",
        f"MA20 {'向上' if ma20_rising else '向下或持平'}",
    ]
    if breadth_ma20_pct is not None:
        evidence.append(f"MA20宽度 {breadth_ma20_pct:.1f}%")
    if relative_return_20d_pct is not None:
        evidence.append(f"20日相对收益 {relative_return_20d_pct:+.2f}%")

    if high_crowded and (return_5d_pct or 0) > 8:
        return StageEvidence("高位拥挤", 80.0, evidence + ["近60日高位且内部宽度偏高", "短期涨幅过快"], ["相对强度高不等于适合追涨"])
    if breakout and confirmation_days >= 2 and relative_positive and breadth_improving:
        return StageEvidence("突破确认", 75.0, evidence + ["突破20日上沿", "成交量至少为近期均值1.2倍", "已满足连续确认要求"], ["突破确认仍需防止次日失效"])
    if close >= ma20 and breadth_improving and (return_5d_pct or 0) > 0 and (relative_return_20d_pct is None or relative_positive):
        return StageEvidence("底部改善", 65.0, evidence + ["重新站上MA20", "内部宽度达到改善阈值"], ["板块改善不是个股建仓信号，仍需个股独立确认"])
    if position <= 0.35 and not ma20_rising and breadth_ma20_pct is not None and breadth_ma20_pct >= 35:
        return StageEvidence("低位企稳", 50.0, evidence + ["处于60日区间低位", "上涨参与度不再极端恶化"], ["低位企稳可能只是下跌中继"])
    if close < ma20 and close < ma60 and not relative_positive and (breadth_ma20_pct is None or breadth_ma20_pct < 50):
        return StageEvidence("下跌中", 25.0, evidence + ["价格低于MA20/MA60", "相对强度或内部宽度偏弱"], ["不因价格便宜而提前判定筑底"])
    return StageEvidence("数据不足", None, evidence, ["当前证据未满足任一阶段规则"])
