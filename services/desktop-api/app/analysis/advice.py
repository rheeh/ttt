from __future__ import annotations

from app.analysis.models import Advice, PriceZone, TechnicalIndicators


def build_zones(*, price: float | None, support: float | None, resistance: float | None,
                prior_support: float | None = None, prior_resistance: float | None = None,
                atr: float | None, trend_valid: bool, confidence: float,
                action: str = "观望", is_holding: bool = False, trend_weak: bool = False,
                entry_route: str | None = None) -> list[PriceZone]:
    """Return zones consistent with the current conclusion.

    ``confidence`` is retained for API compatibility but deliberately does not
    unlock any high-position zone. Until outcomes are verified, the system
    never generates a 梭哈区.
    """
    if not price or not support or not resistance or resistance <= support:
        return []
    volatility = atr or (resistance - support) / 4
    reference_support = prior_support or support
    reference_resistance = prior_resistance or resistance
    invalidation = reference_support - volatility * .7
    if price < invalidation:
        return [PriceZone(name="清仓警戒区", low=round(max(0, invalidation - volatility), 2), high=round(invalidation, 2),
                          action="已跌破失效线，先等待结构修复；不因更低价格自动补仓", tone="red")]
    if action == "失效":
        return [PriceZone(name="结构修复观察区", low=round(max(0, reference_support), 2), high=round(reference_support + volatility * .3, 2),
                          action="重新站回失效线并完成企稳前，不生成入场建议", tone="red")]
    if trend_weak:
        return [PriceZone(name="企稳触发区", low=round(max(0, reference_support), 2), high=round(reference_support + volatility * .35, 2),
                          action="仅观察收盘企稳、量价改善和周线止跌", tone="blue")]
    if action == "建仓":
        if entry_route == "突破":
            return [PriceZone(name="突破建仓区", low=round(reference_resistance, 2), high=round(reference_resistance + volatility * .35, 2),
                              action="仅在收盘站上前20日上沿且量能、周线同时确认后研究", tone="green")]
        return [PriceZone(name="回踩建仓区", low=round(max(0, reference_support - volatility * .15), 2), high=round(reference_support + volatility * .35, 2),
                          action="仅在回踩支撑附近收盘企稳后分批研究", tone="green")]
    if action == "持有" and is_holding:
        return [PriceZone(name="持有观察区", low=round(max(0, reference_support + volatility * .25), 2), high=round(max(reference_support, reference_resistance - volatility * .35), 2),
                          action="趋势未破坏时观察，不自动生成加仓建议", tone="purple"),
                PriceZone(name="压力观察区", low=round(max(reference_support, reference_resistance - volatility * .35), 2), high=round(reference_resistance + volatility * .25, 2),
                          action="接近压力且动量转弱时复核持仓", tone="orange")]
    if action == "减仓警戒" and is_holding:
        return [PriceZone(name="减仓警戒区", low=round(max(reference_support, reference_resistance - volatility * .35), 2), high=round(reference_resistance + volatility * .25, 2),
                          action="持仓状态下接近压力且趋势转弱时复核，不作为非持仓卖出指令", tone="orange")]
    if action == "右侧确认":
        return [PriceZone(name="突破确认区", low=round(max(0, reference_resistance - volatility * .2), 2), high=round(reference_resistance + volatility * .35, 2),
                          action="等待收盘突破前20日上沿并完成量价确认", tone="blue")]
    return [PriceZone(name="观察区", low=round(max(0, reference_support), 2), high=round(reference_resistance, 2),
                      action="当前结论为观望，不生成加仓或高仓位区域", tone="purple")]


def build_advice(*, price: float | None, pe: float | None, roe: float | None, score: float,
                 confidence: float, technical: TechnicalIndicators, is_holding: bool,
                 position_cost: float | None, core_complete: bool, asset_type: str = "stock",
                 weekly: TechnicalIndicators | None = None) -> Advice:
    weekly = weekly or technical
    data_completeness = confidence
    if asset_type == "etf":
        category = "C档情绪型"
        trend_valid = technical.trend in {"强势上涨", "上涨", "震荡"}
        action = "持有" if is_holding and trend_valid else "观望"
        summary = "ETF仅按趋势、量能、波动和相对基准分析，不套用个股 PE、财务和行业排名。"
        triggered = ["ETF趋势模型"] + ([f"知行指数 {score:.0f}"] if score >= 55 else [])
        unmet = ["等待 ETF 趋势与基准相对强度进一步确认"] if action == "观望" else []
        unmet.append("高仓位条件尚未通过历史验证，暂不生成")
        return Advice(
            action=action, category=category, summary=summary, risk_level="中",
            operations=["关注跟踪误差、成交活跃度和标的指数状态"],
            zones=build_zones(price=price, support=technical.support20, resistance=technical.resistance20,
                              prior_support=technical.prior_support20, prior_resistance=technical.prior_resistance20,
                              atr=technical.atr14, trend_valid=trend_valid, confidence=data_completeness,
                              action=action, is_holding=is_holding, trend_weak=technical.trend in {"下跌", "快速下跌"}),
            triggered_conditions=triggered, unmet_conditions=unmet,
            invalidation_conditions=["收盘跌破 ETF 前20日区间下沿并无法收回"],
            data_confidence=data_completeness, data_completeness=data_completeness, review_after="下一个交易日收盘后",
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
    weekly_weak = weekly.trend in {"下跌", "快速下跌"}
    weekly_confirmed = weekly.trend in {"强势上涨", "上涨"}
    if technical.trend in {"强势上涨", "上涨"}:
        triggered.append(f"日线{technical.trend}")
    else:
        unmet.append("日线尚未转强")
    if weekly_weak:
        unmet.append(f"周线{weekly.trend}，不直接建仓")
    elif weekly_confirmed:
        triggered.append(f"周线{weekly.trend}")
    if technical.macd and technical.macd.golden_cross:
        triggered.append("MACD 金叉")
    else:
        unmet.append("尚未出现新的 MACD 金叉确认")
    if technical.volume_ratio is not None and technical.volume_ratio >= 1:
        triggered.append("成交量不低于近期均值")
    else:
        unmet.append("量价确认不足")
    if data_completeness < 75:
        unmet.append(f"数据完整度仅 {data_completeness:.0f}%")
    if not core_complete:
        unmet.append("核心行情或日线数据不完整")
    unmet.append("高仓位条件尚未通过历史验证，暂不生成")

    reference_support = technical.prior_support20 or technical.support20
    reference_resistance = technical.prior_resistance20 or technical.resistance20
    range_width = reference_resistance - reference_support if reference_support and reference_resistance and reference_resistance > reference_support else None
    position_ratio = (price - reference_support) / range_width if price is not None and reference_support and range_width else None
    near_support = position_ratio is not None and position_ratio <= .45
    near_resistance = position_ratio is not None and position_ratio >= .78
    volatility = technical.atr14 or (range_width / 4 if range_width else None)
    pullback_confirmed = bool(price is not None and reference_support and price >= reference_support and near_support and trend_valid and not weekly_weak and
                              technical.macd and not technical.macd.death_cross and (technical.macd.golden_cross or technical.macd.hist > 0) and
                              technical.volume_ratio is not None and technical.volume_ratio >= .9)
    breakout_confirmed = bool(price is not None and reference_resistance and price >= reference_resistance and technical.trend in {"强势上涨", "上涨"} and
                              weekly_confirmed and technical.volume_ratio is not None and technical.volume_ratio >= 1)
    entry_route: str | None = None

    if weak_trend and (price is None or reference_support is None or price < reference_support):
        action, summary, risk = ("减仓警戒" if is_holding else "失效"), "结构已走弱或跌破区间下沿，等待重新站回失效线", "高"
        triggered.append("结构破坏")
    elif is_holding and trend_valid and score >= 50 and data_completeness >= 60 and not weekly_weak:
        action, summary, risk = "持有", f"持仓复盘保持观察，成本价 {position_cost:.2f} 仅用于参考" if position_cost else "趋势尚未破坏，继续观察", "中"
        triggered.append("持仓状态下趋势未破坏")
    elif not is_holding and score >= 65 and data_completeness >= 75 and core_complete and not weekly_weak and (pullback_confirmed or breakout_confirmed):
        entry_route = "突破" if breakout_confirmed else "回踩"
        action, summary, risk = "建仓", f"{entry_route}条件已确认，可在对应区域分批研究；不生成高仓位结论", "中"
        triggered.extend([f"知行指数 {score:.0f} ≥ 65", f"{entry_route}路径确认"])
    elif not is_holding and score >= 55 and data_completeness >= 60 and technical.macd and technical.macd.golden_cross and trend_valid and not weekly_weak:
        action, summary, risk = "右侧确认", "评分和 MACD 初步改善，等待收盘位置、成交与相对强度继续确认", "中"
        triggered.append(f"知行指数 {score:.0f} ≥ 55")
    else:
        action, summary, risk = "观望", "数据或信号尚未形成一致方向，继续积累证据", "中"
    if near_resistance and action == "建仓" and not breakout_confirmed:
        action, summary = "观望", "当前位置接近前20日压力，尚未满足回踩或突破建仓路径"
        unmet.append("当前位置接近压力，等待回踩企稳或收盘突破")

    support, resistance = reference_support, reference_resistance
    if support:
        operations.append(f"关注前20日区间下沿 {support:.2f}")
    if resistance:
        operations.append(f"关注前20日区间上沿 {resistance:.2f}")
    if technical.macd and technical.macd.death_cross:
        operations.append("MACD 死叉，避免追涨")
    invalidation = support - (volatility or 0) * .7 if support else None
    invalidation_conditions = [f"收盘跌破失效线 {invalidation:.2f}" if invalidation else "跌破前20日区间下沿并无法收回"]
    return Advice(
        action=action, category=category, summary=summary, risk_level=risk, operations=operations,
        zones=build_zones(price=price, support=technical.support20, resistance=technical.resistance20,
                           prior_support=technical.prior_support20, prior_resistance=technical.prior_resistance20,
                           atr=technical.atr14, trend_valid=trend_valid, confidence=data_completeness,
                           action=action, is_holding=is_holding, trend_weak=weak_trend,
                           entry_route=entry_route if action == "建仓" else None),
        triggered_conditions=triggered, unmet_conditions=unmet,
        invalidation_conditions=invalidation_conditions, data_confidence=data_completeness,
        data_completeness=data_completeness,
        review_after="下一个交易日收盘后" if weak_trend or action in {"建仓", "右侧确认", "减仓警戒"} else "5个交易日内复核",
    )
