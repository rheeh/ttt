from __future__ import annotations

from app.analysis.models import Advice, PriceZone, TechnicalIndicators


def build_zones(support: float | None, resistance: float | None) -> list[PriceZone]:
    if not support or not resistance or resistance <= support:
        return []
    span = resistance - support
    bounds = [
        ("梭哈区", support * .97, support, "仅作为极端低位观察", "green"),
        ("加仓区", support, support + span * .25, "回踩支撑附近分批观察", "blue"),
        ("持有区", support + span * .25, resistance * .92, "观察趋势是否延续", "purple"),
        ("减仓区", resistance * .92, resistance * 1.08, "接近压力位，关注风险", "orange"),
        ("清仓警戒区", resistance * 1.08, resistance * 1.25, "仅作风险提示，不自动交易", "red"),
    ]
    return [PriceZone(name=name, low=round(low, 2), high=round(high, 2), action=action, tone=tone) for name, low, high, action, tone in bounds]


def build_advice(*, pe: float | None, roe: float | None, score: float, technical: TechnicalIndicators,
                 is_holding: bool, position_cost: float | None) -> Advice:
    if pe is not None and 0 < pe < 40 and roe is not None and roe > 5:
        category = "A档价值型"
    elif pe is not None and 0 < pe < 80:
        category = "B档成长型"
    else:
        category = "C档情绪型"
    support, resistance = technical.support20, technical.resistance20
    operations: list[str] = []
    if technical.trend == "快速下跌" and score < 40:
        action, summary, risk = "失效", "趋势跌破短中期均线，先等待结构修复", "高"
    elif is_holding and technical.trend in {"下跌", "快速下跌"} and score < 50:
        action, summary, risk = "减仓警戒", "持仓状态下趋势转弱，关注支撑是否失守", "高"
    elif category == "A档价值型" and score >= 50:
        action, summary, risk = "建仓", "价值分组与综合评分达到观察门槛，可在支撑附近分批研究", "中"
    elif category == "B档成长型" and score >= 50:
        action, summary, risk = "等回调", "成长分组评分偏强，等待回踩支撑后再确认", "中"
    elif technical.macd and technical.macd.golden_cross and score >= 40:
        action, summary, risk = "右侧确认", "MACD 金叉且评分不弱，等待量价确认趋势延续", "中"
    elif is_holding and position_cost:
        action, summary, risk = "持有", f"当前作为持仓复盘，成本价 {position_cost:.2f} 仅用于计算参考", "中"
    else:
        action, summary, risk = "观望", "数据或信号尚未形成一致方向，继续积累证据", "中"
    if support:
        operations.append(f"关注支撑 {support:.2f}")
    if resistance:
        operations.append(f"关注压力 {resistance:.2f}")
    if technical.macd and technical.macd.death_cross:
        operations.append("MACD 死叉，避免追涨")
    return Advice(action=action, category=category, summary=summary, risk_level=risk, operations=operations,
                  zones=build_zones(support, resistance))
