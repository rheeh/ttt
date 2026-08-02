from __future__ import annotations

from app.analysis.models import Advice, PriceZone, TechnicalIndicators


def build_zones(*, price: float | None, support: float | None, resistance: float | None,
                atr: float | None, trend_valid: bool, confidence: float) -> list[PriceZone]:
    if not price or not support or not resistance or resistance <= support:
        return []
    volatility = atr or (resistance - support) / 4
    invalidation = support - volatility * .7
    if price < invalidation:
        return [PriceZone(name="清仓警戒区", low=round(max(0, invalidation - volatility), 2), high=round(invalidation, 2),
                          action="已跌破失效线，先等待结构修复；不因更低价格自动补仓", tone="red")]
    add_low, add_high = max(0, support - volatility * .3), support + volatility * .3
    zones = [
        PriceZone(name="加仓区", low=round(add_low, 2), high=round(add_high, 2),
                  action="仅在趋势未失效且回踩后企稳时分批研究", tone="blue"),
        PriceZone(name="持有区", low=round(add_high, 2), high=round(max(add_high, resistance - volatility * .3), 2),
                  action="观察趋势和相对强度是否延续", tone="purple"),
        PriceZone(name="减仓区", low=round(max(add_high, resistance - volatility * .3), 2), high=round(resistance + volatility * .3, 2),
                  action="接近区间上沿且动量转弱时才触发减仓警戒", tone="orange"),
    ]
    if trend_valid and confidence >= 85:
        zones.insert(0, PriceZone(name="梭哈区", low=round(max(0, invalidation), 2), high=round(support, 2),
                                  action="仅当重新站回失效线并完成企稳确认后研究；不是越跌越买", tone="green"))
    return zones


def build_advice(*, price: float | None, pe: float | None, roe: float | None, score: float,
                 confidence: float, technical: TechnicalIndicators, is_holding: bool,
                 position_cost: float | None, core_complete: bool, asset_type: str = "stock") -> Advice:
    if asset_type == "etf":
        category = "C档情绪型"
        trend_valid = technical.trend in {"强势上涨", "上涨", "震荡"}
        action = "持有" if is_holding and trend_valid else "观望"
        summary = "ETF仅按趋势、量能、波动和相对基准分析，不套用个股 PE、财务和行业排名。"
        triggered = ["ETF趋势模型"] + ([f"知行指数 {score:.0f}"] if score >= 55 else [])
        unmet = ["等待 ETF 趋势与基准相对强度进一步确认"] if action == "观望" else []
        return Advice(
            action=action, category=category, summary=summary, risk_level="中",
            operations=["关注跟踪误差、成交活跃度和标的指数状态"],
            zones=build_zones(price=price, support=technical.support20, resistance=technical.resistance20,
                              atr=technical.atr14, trend_valid=trend_valid, confidence=confidence),
            triggered_conditions=triggered, unmet_conditions=unmet,
            invalidation_conditions=["收盘跌破 ETF 20 日区间下沿并无法收回"],
            data_confidence=confidence, review_after="下一个交易日收盘后",
        )
    if pe is not None and 0 < pe < 40 and roe is not None and roe > 5:
        category = "A档价值型"
    elif pe is not None and 0 < pe < 80:
        category = "B档成长型"
    else:
        category = "C档情绪型"

    triggered: list[str] = []
    unmet: list[str] = []
    operations: list[str] = []
    weak_trend = technical.trend in {"下跌", "快速下跌"}
    trend_valid = technical.trend in {"强势上涨", "上涨", "震荡"}
    weekly_weak = False
    # Weekly state is folded into the caller's core gate through the score; the
    # explicit condition remains visible in the returned explanation.
    if technical.trend in {"强势上涨", "上涨"}:
        triggered.append(f"日线{technical.trend}")
    else:
        unmet.append("日线尚未转强")
    if technical.macd and technical.macd.golden_cross:
        triggered.append("MACD 金叉")
    else:
        unmet.append("尚未出现新的 MACD 金叉确认")
    if technical.volume_ratio is not None and technical.volume_ratio >= 1:
        triggered.append("成交量不低于近期均值")
    else:
        unmet.append("量价确认不足")
    if confidence < 75:
        unmet.append(f"数据可信度仅 {confidence:.0f}%")
    if not core_complete:
        unmet.append("核心行情或日线数据不完整")

    if weak_trend and (price is None or technical.support20 is None or price < technical.support20):
        action, summary, risk = ("减仓警戒" if is_holding else "失效"), "结构已走弱或跌破区间下沿，等待重新站回失效线", "高"
        triggered.append("结构破坏")
    elif is_holding and trend_valid and score >= 50 and confidence >= 60:
        action, summary, risk = "持有", f"持仓复盘保持观察，成本价 {position_cost:.2f} 仅用于参考" if position_cost else "趋势尚未破坏，继续观察", "中"
        triggered.append("持仓状态下趋势未破坏")
    elif not is_holding and score >= 65 and confidence >= 75 and technical.trend in {"强势上涨", "上涨"} and core_complete:
        action, summary, risk = "建仓", "综合评分达到门槛且核心数据完整，可在确认后的支撑附近分批研究", "中"
        triggered.append(f"知行指数 {score:.0f} ≥ 65")
    elif not is_holding and score >= 55 and confidence >= 60 and technical.macd and technical.macd.golden_cross:
        action, summary, risk = "右侧确认", "评分和 MACD 初步改善，等待成交与相对强度继续确认", "中"
        triggered.append(f"知行指数 {score:.0f} ≥ 55")
    else:
        action, summary, risk = "观望", "数据或信号尚未形成一致方向，继续积累证据", "中"

    support, resistance = technical.support20, technical.resistance20
    if support:
        operations.append(f"关注20日区间下沿 {support:.2f}")
    if resistance:
        operations.append(f"关注20日区间上沿 {resistance:.2f}")
    if technical.macd and technical.macd.death_cross:
        operations.append("MACD 死叉，避免追涨")
    invalidation = support - (technical.atr14 or 0) * .7 if support else None
    invalidation_conditions = [f"收盘跌破失效线 {invalidation:.2f}" if invalidation else "跌破20日区间下沿并无法收回"]
    return Advice(
        action=action, category=category, summary=summary, risk_level=risk, operations=operations,
        zones=build_zones(price=price, support=support, resistance=resistance, atr=technical.atr14,
                           trend_valid=trend_valid, confidence=confidence),
        triggered_conditions=triggered, unmet_conditions=unmet,
        invalidation_conditions=invalidation_conditions, data_confidence=confidence,
        review_after="下一个交易日收盘后" if weak_trend or action in {"建仓", "右侧确认", "减仓警戒"} else "5个交易日内复核",
    )
