from __future__ import annotations

from statistics import mean
from hashlib import sha256

from app.analysis.models import Diagnosis, FactorScore, RadarDimension, TechnicalIndicators


ZHIXING_ALGORITHM_VERSION = "1.1.0"
ZHIXING_RULE_FINGERPRINT = sha256(
    b"zhixing-10-factor-v1.1|neutral-unavailable=50|radar-six-dimensions|finance-industry-fund-flow"
).hexdigest()[:16]


def _score(key: str, label: str, value: float, reason: str, available: bool = True, source: str = "derived") -> FactorScore:
    return FactorScore(key=key, label=label, score=round(max(0, min(100, value)), 2), reason=reason, available=available, source=source)


def _clamp(value: float) -> float:
    return max(0, min(100, value))


def build_factors(*, price: float | None, change_pct: float | None, daily: TechnicalIndicators,
                  weekly: TechnicalIndicators, benchmark: TechnicalIndicators | None,
                  sector_rank: int | None,
                  fund_flow_ratio: float | None, revenue_growth: float | None) -> list[FactorScore]:
    factors: list[FactorScore] = []
    trend_score = {"强势上涨": 90, "上涨": 70, "震荡": 50, "下跌": 30, "快速下跌": 15}.get(daily.trend, 50)
    if price and daily.ma20 and price > daily.ma20:
        trend_score += 5
    if daily.ma20 and daily.ma60 and daily.ma20 > daily.ma60:
        trend_score += 5
    factors.append(_score("trend", "趋势", trend_score, f"日线{daily.trend}，均线{'多头' if trend_score >= 70 else '未形成多头'}"))
    if daily.volume_ratio is None and fund_flow_ratio is None:
        factors.append(_score("volume_fund", "量能资金", 50, "量比和主力资金均缺失", available=False))
    else:
        volume_score = 50 + ((daily.volume_ratio - 1) * 30 if daily.volume_ratio is not None else 0)
        fund_adjust = max(-20, min(20, fund_flow_ratio * 200)) if fund_flow_ratio is not None else 0
        source = f"量比 {daily.volume_ratio:.2f}" if daily.volume_ratio is not None else "量比缺失"
        source += f"，主力净流入占比 {fund_flow_ratio * 100:+.2f}%" if fund_flow_ratio is not None else "，主力资金缺失"
        factors.append(_score("volume_fund", "量能资金", volume_score + fund_adjust, source, source="volume+eastmoney-fflow"))
    if daily.rsi14 is None:
        factors.append(_score("momentum", "动量", 50, "RSI 缺失", available=False))
    else:
        rsi = daily.rsi14
        momentum_score = 80 if 55 <= rsi <= 70 else 65 if 45 <= rsi < 55 else 60 if 70 < rsi <= 78 else 40 if rsi > 78 else 35
        if daily.return_20d_pct is not None:
            momentum_score += max(-10, min(10, daily.return_20d_pct / 2))
        factors.append(_score("momentum", "动量", momentum_score, f"RSI14 {rsi:.1f}，20日收益 {daily.return_20d_pct:.1f}%" if daily.return_20d_pct is not None else f"RSI14 {rsi:.1f}"))
    if benchmark and daily.return_20d_pct is not None and benchmark.return_20d_pct is not None:
        relative = daily.return_20d_pct - benchmark.return_20d_pct
        factors.append(_score("relative_strength", "相对强度", 50 + relative * 4, f"相对上证20日超额 {relative:+.1f}%", source="stock-vs-sh000001"))
    else:
        factors.append(_score("relative_strength", "相对强度", 50, "基准指数数据不足", available=False, source="sh000001"))
    if daily.atr14 is None or not price:
        factors.append(_score("volatility", "波动状态", 50, "ATR 缺失", available=False))
    else:
        atr_pct = daily.atr14 / price * 100
        volatility_score = 70 if 1.5 <= atr_pct <= 4 else 55 if atr_pct < 1.5 else 45 if atr_pct <= 7 else 25
        factors.append(_score("volatility", "波动状态", volatility_score, f"ATR14 占价 {atr_pct:.2f}%"))
    if not price or not daily.resistance20 or not daily.support20:
        factors.append(_score("structure", "形态结构", 50, "支撑压力缺失", available=False))
    elif price >= daily.resistance20 * .995:
        factors.append(_score("structure", "形态结构", 85, "价格靠近20日压力，观察突破确认"))
    elif price <= daily.support20 * 1.05:
        factors.append(_score("structure", "形态结构", 70, "价格靠近20日支撑，观察回踩企稳"))
    else:
        factors.append(_score("structure", "形态结构", 50, "处于20日区间内部"))
    if not price or not daily.support20 or not daily.resistance20 or daily.resistance20 <= daily.support20:
        factors.append(_score("key_levels", "关键位置", 50, "关键位缺失", available=False))
    else:
        position = (price - daily.support20) / (daily.resistance20 - daily.support20)
        level_score = 75 if position <= .25 else 65 if position <= .5 else 50 if position < .85 else 35
        factors.append(_score("key_levels", "关键位置", level_score, f"处于20日区间 {position * 100:.0f}% 位置"))
    if daily.trend == "数据不足" or weekly.trend == "数据不足":
        factors.append(_score("cycle", "周期共振", 50, "日周线数据不足", available=False))
    elif daily.trend in {"强势上涨", "上涨"} and weekly.trend in {"强势上涨", "上涨"}:
        factors.append(_score("cycle", "周期共振", 85, "日线与周线同向偏强"))
    elif daily.trend in {"下跌", "快速下跌"} and weekly.trend in {"下跌", "快速下跌"}:
        factors.append(_score("cycle", "周期共振", 20, "日线与周线同向偏弱"))
    else:
        factors.append(_score("cycle", "周期共振", 45, "日线与周线方向不一致"))
    if sector_rank is None:
        factors.append(_score("industry", "行业热度", 50, "行业横截面尚未接入", available=False, source="pending"))
    else:
        industry_score = 95 if sector_rank <= 5 else 80 if sector_rank <= 10 else 60 if sector_rank <= 20 else 35
        factors.append(_score("industry", "行业热度", industry_score, f"行业排名第 {sector_rank}", source="eastmoney-industry"))
    if revenue_growth is None:
        factors.append(_score("finance", "财务增速", 50, "营收增速缺失", available=False, source="eastmoney-finance"))
    else:
        finance_score = 90 if revenue_growth > 30 else 75 if revenue_growth > 15 else 65 if revenue_growth > 5 else 50 if revenue_growth >= -5 else 35 if revenue_growth >= -15 else 20
        factors.append(_score("finance", "财务增速", finance_score, f"营收同比 {revenue_growth:+.1f}%", source="eastmoney-finance"))
    return factors


def build_radar(factors: list[FactorScore]) -> list[RadarDimension]:
    groups = {
        "trend": ("趋势", ["trend", "cycle"]), "volume": ("量能资金", ["volume_fund", "volatility"]),
        "momentum": ("动量", ["momentum", "relative_strength"]),
        "relative": ("相对强度", ["relative_strength", "industry"]),
        "structure": ("形态", ["structure", "key_levels"]),
        "environment": ("环境", ["cycle", "industry", "finance"]),
    }
    by_key = {factor.key: factor for factor in factors}
    return [RadarDimension(key=key, label=label,
                           score=round(mean([by_key[item].score for item in keys]), 2),
                           factor_keys=keys) for key, (label, keys) in groups.items()]


def build_diagnosis(*, price: float | None, daily: TechnicalIndicators, weekly: TechnicalIndicators,
                    index_score: float) -> Diagnosis:
    positives: list[str] = []
    risks: list[str] = []
    conflicts: list[str] = []
    reassess: list[str] = []
    if daily.ma20 and price and price > daily.ma20:
        positives.append(f"价格位于 MA20 {daily.ma20:.2f} 上方")
    if daily.macd and (daily.macd.golden_cross or daily.macd.hist > 0):
        positives.append("MACD 处于多头或金叉状态")
    if daily.volume_ratio and daily.volume_ratio > 1.2:
        positives.append(f"量比 {daily.volume_ratio:.2f}，量能有所放大")
    if daily.rsi14 and daily.rsi14 > 78:
        risks.append(f"RSI14 {daily.rsi14:.1f}，短线偏热")
    if daily.volume_ratio and daily.volume_ratio < .8:
        risks.append("上涨缺少量能确认")
    if daily.resistance20 and price and price >= daily.resistance20 * .95:
        risks.append(f"接近20日区间上沿 {daily.resistance20:.2f}")
    if daily.trend in {"强势上涨", "上涨"} and weekly.trend in {"下跌", "快速下跌"}:
        conflicts.append("日线偏强、周线偏弱，短线存在周期分歧")
    if daily.trend in {"下跌", "快速下跌"} and weekly.trend in {"强势上涨", "上涨"}:
        conflicts.append("日线回落但周线尚未破坏，中短周期方向不一致")
    if daily.support20:
        reassess.append(f"放量跌破20日区间下沿 {daily.support20:.2f} 时重新评估")
    if daily.resistance20:
        reassess.append(f"放量突破20日区间上沿 {daily.resistance20:.2f} 后重新评估")
    if not positives:
        positives.append("当前没有足够的积极技术证据")
    if not risks:
        risks.append("暂未发现明确的短线风险信号")
    if conflicts:
        summary = f"日线{daily.trend}、周线{weekly.trend}，短线存在分歧，知行指数 {index_score:.0f}。"
    else:
        summary = f"日线{daily.trend}、周线{weekly.trend}，当前技术证据{'偏强' if index_score >= 60 else '中性或偏弱'}，知行指数 {index_score:.0f}。"
    if daily.trend in {"下跌", "快速下跌"}:
        position = "下行趋势"
    elif price and daily.resistance20 and price >= daily.resistance20 * .995:
        position = "突破"
    elif price and daily.support20 and price <= daily.support20 * 1.05:
        position = "回踩"
    elif daily.bar_count >= 20:
        position = "震荡区间"
    else:
        position = "数据不足"
    return Diagnosis(summary=summary, position=position, positive_evidence=positives, risk_evidence=risks,
                      conflicts=conflicts, reassess_conditions=reassess)
