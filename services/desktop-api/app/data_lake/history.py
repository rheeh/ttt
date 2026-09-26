from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.market.daily_contract import BarSeries, INDEX_SYMBOLS, parse_tencent_daily
from app.market.trading_calendar import latest_session
from .reader import LakeReader


class DailyHistoryRouter:
    """Prefer validated lake data; never write a qfq fallback into raw history."""
    def __init__(self, lake: LakeReader, timeout: float = 8, cache_path=None):
        self.lake = lake
        self.timeout = timeout
        from app.market.history_cache import HistoryCache
        self.cache = HistoryCache(cache_path) if cache_path else None

    def fetch_bars(self, code: str, days: int = 252, *, require_fresh: bool = True) -> BarSeries:
        local = None
        reason = None
        try:
            local = self.lake.bars(code, days)
            if len(local) < min(days, 120):
                raise ValueError(f"本地样本不足：{len(local)}根")
            if require_fresh and local[-1].trade_date != latest_session():
                raise ValueError(f"本地日线尚未更新：{local[-1].trade_date}")
            return local
        except (ImportError, ValueError, OSError, RuntimeError) as exc:
            reason = str(exc)
        try:
            # Do not reuse the earlier cache whose equity volumes were in lots.
            cache_key = f"lake-router-v2:{code}:{days}"
            cached = self.cache.get(cache_key, latest_session(), days) if self.cache else None
            if cached:
                self._remote_metadata(cached, code)
                cached.fallback_reason = reason
                return cached
            remote = self.fetch_remote(code, days)
            remote.fallback_reason = reason
            if self.cache and remote:
                self.cache.save(cache_key, remote)
            return remote
        except (OSError, ValueError, RuntimeError) as exc:
            error = f"本地数据不可用：{reason}；腾讯备用源失败：{exc}"
            if local:
                local.error = error
                return local
            return BarSeries(error=error)

    def fetch_remote(self, code: str, days: int):
        query = urlencode({"param": f"{code},day,,,{days},qfq"})
        request = Request("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + query,
                          headers={"User-Agent": "Mozilla/5.0 ZhixingStockResearch", "Referer": "https://gu.qq.com/"})
        with urlopen(request, timeout=self.timeout) as response:
            bars = parse_tencent_daily(json.loads(response.read().decode()), code)
        if code not in INDEX_SYMBOLS:
            for bar in bars:
                bar.volume *= 100  # Tencent equity lots -> CNEquity shares.
        self._remote_metadata(bars, code)
        return bars

    @staticmethod
    def _remote_metadata(bars, code):
        index = code in INDEX_SYMBOLS
        bars.adjustment = "index_points" if index else "qfq"
        bars.volume_unit = "tencent_index_native" if index else "shares"
        bars.contract_version = "tencent-completed-daily-router-v2"


class LakeFinanceProvider:
    def __init__(self, lake, fallback):
        self.lake, self.fallback = lake, fallback

    def fetch(self, code):
        try:
            result = self.lake.finance(code)
            from app.market.trading_calendar import market_now
            if (market_now() - result.fetched_at).total_seconds() > 7 * 86400:
                raise ValueError("本地财务采集超过7天，尝试最新来源")
            return result
        except (ImportError, ValueError, OSError, RuntimeError):
            return self.fallback.fetch(code)


class TrainingRows(list):
    def __init__(self, bars):
        from app.training.service import valid_bars
        super().__init__(valid_bars([bar.model_dump(mode="json") for bar in bars]))
        self.source = bars.source
        self.fetched_at = bars.fetched_at


class LakeTrainingProvider:
    def __init__(self, history):
        self.history = history

    def fetch(self, code):
        bars = self.history.fetch_bars(code, 640, require_fresh=False)
        if not bars:
            raise ValueError(bars.error or "历史数据不可用")
        return TrainingRows(bars)

    def preferred_codes(self):
        try:
            self.history.lake._require()
            frame = self.history.lake._load("daily_bars")
            return {f"{value[-2:].lower()}{value[:6]}" for value in frame["symbol"].unique().to_list()}
        except (ImportError, ValueError, OSError, RuntimeError):
            return set()

    def fetch_local(self, code):
        try:
            bars = self.history.lake.bars(code, 640)
            return TrainingRows(bars)
        except (ImportError, ValueError, OSError, RuntimeError):
            return []
