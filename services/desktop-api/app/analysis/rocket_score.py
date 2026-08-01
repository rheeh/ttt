from __future__ import annotations

from app.analysis.models import MacdIndicator, RocketDimension, RocketScore


def _dimension(key: str, label: str, score: float, *reasons: str, available: bool = True) -> RocketDimension:
    return RocketDimension(key=key, label=label, score=score, reasons=[reason for reason in reasons if reason], available=available)


def calculate_rocket_score(
    *, change_pct: float | None, pe: float | None, main_flow_ratio: float | None,
    sector_rank: int | None, volume_ratio: float | None, inout_ratio: float | None,
    macd: MacdIndicator | None, revenue_growth: float | None,
) -> RocketScore:
    dimensions: list[RocketDimension] = []
    missing: list[str] = []
    if change_pct is None:
        dimensions.append(_dimension("trend", "当日趋势", 0, "缺少当日涨跌幅", available=False)); missing.append("change_pct")
    elif change_pct > 5:
        dimensions.append(_dimension("trend", "当日趋势", 12.5, "强势上涨"))
    elif change_pct > 3:
        dimensions.append(_dimension("trend", "当日趋势", 8, "上涨偏强"))
    elif change_pct > 1:
        dimensions.append(_dimension("trend", "当日趋势", 4, "温和上涨"))
    elif change_pct < -3:
        dimensions.append(_dimension("trend", "当日趋势", -8, "下跌压力"))
    elif change_pct < -1:
        dimensions.append(_dimension("trend", "当日趋势", -4, "小幅走弱"))
    else:
        dimensions.append(_dimension("trend", "当日趋势", 0, "横盘或小幅波动"))
    if pe is None:
        dimensions.append(_dimension("pe", "PE估值", 0, "缺少 PE", available=False)); missing.append("pe")
    elif pe <= 0:
        dimensions.append(_dimension("pe", "PE估值", -6, "亏损或 PE 无效"))
    elif pe < 15:
        dimensions.append(_dimension("pe", "PE估值", 12.5, "低 PE"))
    elif pe <= 30:
        dimensions.append(_dimension("pe", "PE估值", 8, "估值合理"))
    elif pe <= 60:
        dimensions.append(_dimension("pe", "PE估值", 4, "估值偏高"))
    else:
        dimensions.append(_dimension("pe", "PE估值", -4, "高 PE"))
    if main_flow_ratio is None:
        dimensions.append(_dimension("fund", "主力资金", 0, "资金数据未接入", available=False)); missing.append("main_flow_ratio")
    elif main_flow_ratio > .05:
        dimensions.append(_dimension("fund", "主力资金", 12.5, "主力流入强"))
    elif main_flow_ratio > .02:
        dimensions.append(_dimension("fund", "主力资金", 6, "主力资金偏正"))
    elif main_flow_ratio < -.05:
        dimensions.append(_dimension("fund", "主力资金", -10, "主力流出强"))
    elif main_flow_ratio < -.02:
        dimensions.append(_dimension("fund", "主力资金", -5, "主力资金偏弱"))
    else:
        dimensions.append(_dimension("fund", "主力资金", 0, "资金中性"))
    if sector_rank is None:
        dimensions.append(_dimension("sector", "板块排名", 0, "板块横截面未接入", available=False)); missing.append("sector_rank")
    elif sector_rank <= 5:
        dimensions.append(_dimension("sector", "板块排名", 12.5, "板块前 5"))
    elif sector_rank <= 10:
        dimensions.append(_dimension("sector", "板块排名", 8, "板块前 10"))
    elif sector_rank <= 20:
        dimensions.append(_dimension("sector", "板块排名", 4, "板块中游"))
    elif sector_rank > 30:
        dimensions.append(_dimension("sector", "板块排名", -6, "板块排名靠后"))
    else:
        dimensions.append(_dimension("sector", "板块排名", -3, "板块偏弱"))
    if volume_ratio is None:
        dimensions.append(_dimension("volume", "量比", 0, "成交量不足", available=False)); missing.append("volume_ratio")
    elif volume_ratio > 2.5:
        dimensions.append(_dimension("volume", "量比", 12.5, "显著放量"))
    elif volume_ratio > 1.8:
        dimensions.append(_dimension("volume", "量比", 8, "放量"))
    elif volume_ratio > 1.2:
        dimensions.append(_dimension("volume", "量比", 4, "温和放量"))
    elif volume_ratio < .8:
        dimensions.append(_dimension("volume", "量比", -4, "缩量"))
    else:
        dimensions.append(_dimension("volume", "量比", 0, "量比正常"))
    if inout_ratio is None:
        dimensions.append(_dimension("inout", "内外盘", 0, "内外盘数据未接入", available=False)); missing.append("inout_ratio")
    elif change_pct is not None and change_pct > 0 and inout_ratio >= 65:
        dimensions.append(_dimension("inout", "内外盘", 12.5, "上涨且外盘强"))
    elif change_pct is not None and change_pct < 0 and inout_ratio <= 35:
        dimensions.append(_dimension("inout", "内外盘", -8, "下跌且内盘强"))
    else:
        dimensions.append(_dimension("inout", "内外盘", 0, "内外盘中性"))
    if macd is None:
        dimensions.append(_dimension("macd", "MACD", 0, "K线不足", available=False)); missing.append("macd")
    elif macd.golden_cross:
        dimensions.append(_dimension("macd", "MACD", 12.5, "MACD 金叉"))
    elif macd.death_cross:
        dimensions.append(_dimension("macd", "MACD", -12.5, "MACD 死叉"))
    elif macd.hist > 0:
        dimensions.append(_dimension("macd", "MACD", 4, "MACD 多头"))
    else:
        dimensions.append(_dimension("macd", "MACD", -4, "MACD 空头"))
    if revenue_growth is None:
        dimensions.append(_dimension("revenue", "营收增速", 0, "财务数据未接入", available=False)); missing.append("revenue_growth")
    elif revenue_growth > 30:
        dimensions.append(_dimension("revenue", "营收增速", 12.5, "营收增长超过 30%"))
    elif revenue_growth > 15:
        dimensions.append(_dimension("revenue", "营收增速", 8, "营收增长超过 15%"))
    elif revenue_growth > 5:
        dimensions.append(_dimension("revenue", "营收增速", 4, "营收保持增长"))
    elif revenue_growth < -15:
        dimensions.append(_dimension("revenue", "营收增速", -8, "营收明显下滑"))
    elif revenue_growth < -5:
        dimensions.append(_dimension("revenue", "营收增速", -4, "营收小幅下滑"))
    else:
        dimensions.append(_dimension("revenue", "营收增速", 0, "营收基本稳定"))
    score = round(max(0, min(100, sum(item.score for item in dimensions))), 2)
    level = "极强" if score >= 80 else "偏强" if score >= 60 else "中性" if score >= 40 else "偏弱" if score >= 20 else "弱势"
    return RocketScore(score=score, level=level, dimensions=dimensions, missing_fields=sorted(set(missing)))
