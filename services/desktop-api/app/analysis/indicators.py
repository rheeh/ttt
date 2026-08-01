from __future__ import annotations

from statistics import mean

from app.analysis.models import DailyBar, MacdIndicator, TechnicalIndicators


def _ma(values: list[float], period: int) -> float | None:
    return round(mean(values[-period:]), 4) if len(values) >= period else None


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * alpha + result[-1] * (1 - alpha))
    return result


def calculate_rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for index in range(len(values) - period, len(values)):
        delta = values[index] - values[index - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    average_gain, average_loss = mean(gains), mean(losses)
    if average_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + average_gain / average_loss), 2)


def calculate_macd(values: list[float]) -> MacdIndicator | None:
    if len(values) < 35:
        return None
    dif_series = [a - b for a, b in zip(_ema(values, 12), _ema(values, 26))]
    dea_series = _ema(dif_series, 9)
    hist_series = [(dif - dea) * 2 for dif, dea in zip(dif_series, dea_series)]
    index, previous = -1, -2
    return MacdIndicator(
        dif=round(dif_series[index], 4), dea=round(dea_series[index], 4), hist=round(hist_series[index], 4),
        golden_cross=dif_series[index] > dea_series[index] and dif_series[previous] <= dea_series[previous],
        death_cross=dif_series[index] < dea_series[index] and dif_series[previous] >= dea_series[previous],
    )


def calculate_indicators(bars: list[DailyBar]) -> TechnicalIndicators:
    closes = [bar.close for bar in bars]
    if not closes:
        return TechnicalIndicators()
    recent = bars[-20:]
    current_volume = bars[-1].volume
    previous_volumes = [bar.volume for bar in bars[-6:-1] if bar.volume > 0]
    volume_ratio = round(current_volume / mean(previous_volumes), 4) if previous_volumes and current_volume >= 0 else None
    ma5, ma10, ma20, ma60 = (_ma(closes, period) for period in (5, 10, 20, 60))
    last = closes[-1]
    if ma5 is None or ma10 is None:
        trend = "数据不足"
    elif last > ma5 > ma10 and (ma20 is None or ma10 > ma20):
        trend = "强势上涨"
    elif last > ma5:
        trend = "上涨"
    elif ma5 < ma10 and (ma20 is None or last < ma20):
        trend = "快速下跌" if ma20 is not None and last < ma20 else "下跌"
    else:
        trend = "震荡"
    return TechnicalIndicators(
        ma5=ma5, ma10=ma10, ma20=ma20, ma60=ma60, rsi14=calculate_rsi(closes),
        macd=calculate_macd(closes), support20=round(min(bar.low for bar in recent), 4) if recent else None,
        resistance20=round(max(bar.high for bar in recent), 4) if recent else None,
        high52w=round(max(bar.high for bar in bars[-252:]), 4), low52w=round(min(bar.low for bar in bars[-252:]), 4),
        volume_ratio=volume_ratio, trend=trend, bar_count=len(bars),
    )
