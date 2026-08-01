from datetime import datetime, timezone
from pathlib import Path

from app.database import CandidateRepository
from app.market.scanner import MarketScanner, StockPool
from app.market.akshare import AkshareQuoteProvider, FallbackHistoryProvider, FallbackQuoteProvider
from app.market.tencent import TencentQuoteProvider
from app.market.tencent_daily import TencentDailyProvider
from app.models import DailyIndicators, QuoteSnapshot
from app.scoring import StrategyEngine


ROOT = Path(__file__).parents[1]
POOL = ROOT / "packages" / "stock-presets" / "group-original-pool.json"
STRATEGY = ROOT / "packages" / "strategy-spec" / "group-original-v1.json"


def tencent_line() -> str:
    fields = [""] * 87
    values = {
        0: "1", 1: "贵州茅台", 2: "600519", 3: "1350.60", 4: "1361.76", 5: "1330.03",
        6: "55128", 30: "20260731161450", 32: "-0.82", 33: "1355.72", 34: "1325.77",
        37: "737346", 38: "0.44", 39: "20.41", 43: "2.20", 46: "7.25",
    }
    for index, value in values.items():
        fields[index] = value
    return 'v_sh600519="' + "~".join(fields) + '";'


def test_full_group_pool_is_preserved():
    pool = StockPool(POOL)
    assert len(pool.stocks) == 66
    assert len(pool.etfs) == 11
    assert len({item.code for item in pool.stocks + pool.etfs}) == 77


def test_tencent_parser_normalizes_source_and_freshness():
    quote = TencentQuoteProvider.parse_response(tencent_line())["sh600519"]
    assert quote.stock_name == "贵州茅台"
    assert quote.price == 1350.60
    assert quote.amount == 7_373_460_000
    assert quote.trade_at.isoformat() == "2026-07-31T16:14:50+08:00"
    assert quote.status == "degraded"
    assert "main_flow_ratio" in quote.missing_fields


def test_daily_parser_builds_moving_averages():
    rows = [[f"2026-07-{day:02d}", "0", str(day), "0", "0", "0"] for day in range(1, 31)]
    indicators = TencentDailyProvider.parse_rows("sh600519", rows)
    assert indicators.status == "ok"
    assert indicators.bar_count == 30
    assert indicators.ma5 == 28
    assert indicators.ma10 == 25.5
    assert indicators.ma20 == 20.5


def test_akshare_quote_parser_and_fallback():
    preset = StockPool(POOL).stocks[0].model_copy(update={"code": "sh600519"})
    quote = AkshareQuoteProvider._parse(preset, {
        "代码": "600519", "名称": "贵州茅台", "最新价": 1500, "涨跌幅": 1.2,
        "换手率": 0.3, "振幅": 2.1, "市盈率-动态": 24, "市净率": 8,
    }, datetime.now(timezone.utc))
    assert quote.price == 1500 and quote.status == "degraded"

    class Primary:
        name = "primary"
        def fetch(self, presets):
            return [QuoteSnapshot(stock_code=presets[0].code, stock_name=presets[0].name, fetched_at=datetime.now(timezone.utc), source=self.name, status="error", error="unavailable")]

    class Backup:
        name = "backup"
        def fetch(self, presets):
            return [quote]

    merged = FallbackQuoteProvider(Primary(), Backup()).fetch([preset])[0]
    assert merged.price == 1500 and merged.source == "primary+akshare-spot-em"


def test_history_fallback_replaces_failed_primary():
    preset = StockPool(POOL).stocks[0]

    class Primary:
        name = "primary-history"
        def fetch(self, presets):
            return {item.code: DailyIndicators(stock_code=item.code, source=self.name, status="error", error="timeout") for item in presets}

    class Backup:
        name = "backup-history"
        def fetch(self, presets):
            return {item.code: DailyIndicators(stock_code=item.code, ma5=1, ma10=1, ma20=1, bar_count=30, source=self.name, status="ok") for item in presets}

    result = FallbackHistoryProvider(Primary(), Backup()).fetch([preset])
    assert result[preset.code].source == "backup-history" and result[preset.code].status == "ok"


class FakeProvider:
    name = "fixture"

    def fetch(self, presets):
        now = datetime.now(timezone.utc)
        return [QuoteSnapshot(
            stock_code=item.code, stock_name=item.name, price=10 + index,
            previous_close=10, open=10, high=11, low=9,
            change_pct=float(index + 1), turnover_pct=2, amplitude_pct=3,
            pe=10 + index * 5, pb=1 + index, fetched_at=now, trade_at=now,
            source=self.name, status="degraded",
            missing_fields=["main_flow_ratio", "quality_score", "ma5", "ma10", "ma20"],
        ) for index, item in enumerate(presets)]


class FakeHistoryProvider:
    name = "fixture-history"

    def fetch(self, presets):
        return {item.code: DailyIndicators(
            stock_code=item.code, ma5=9, ma10=8, ma20=7, bar_count=30,
            latest_trade_date="2026-07-31", source=self.name, status="ok",
        ) for item in presets}


def test_scanner_scores_and_sorts_fixture_quotes():
    scanner = MarketScanner(StockPool(POOL), FakeProvider(), StrategyEngine(STRATEGY))
    result = scanner.scan(limit=4)
    assert result.total == 4
    assert result.succeeded == 4
    assert result.degraded == 4
    assert result.failed == 0
    assert all(item.score is not None for item in result.items)
    assert result.scoreable == 4
    assert result.rotation_pool_codes
    assert any(item.score_input and item.score_input.in_rotation_pool for item in result.items)
    scores = [item.score.total_score for item in result.items]
    assert scores == sorted(scores, reverse=True)


def test_scanner_merges_daily_indicators_into_trend_score():
    scanner = MarketScanner(
        StockPool(POOL), FakeProvider(), StrategyEngine(STRATEGY), FakeHistoryProvider(),
    )
    result = scanner.scan(limit=2)
    assert result.source == "fixture+fixture-history"
    assert all(item.quote.ma20 == 7 for item in result.items)
    assert all("ma20" not in item.quote.missing_fields for item in result.items)
    assert all(next(part for part in item.score.dimensions if part.name == "trend").score == 3 for item in result.items)


def test_quote_snapshots_are_upserted(tmp_path):
    quote = TencentQuoteProvider.parse_response(tencent_line())["sh600519"]
    repo = CandidateRepository(tmp_path / "research.sqlite3")
    repo.save_quotes([quote])
    repo.save_quotes([quote.model_copy(update={"price": 1351.0})])
    cached = repo.list_quote_snapshots()
    assert len(cached) == 1
    assert cached[0].price == 1351.0


def test_market_review_summarizes_latest_scan(tmp_path):
    repo = CandidateRepository(tmp_path / "research.sqlite3")
    result = MarketScanner(StockPool(POOL), FakeProvider(), StrategyEngine(STRATEGY)).scan(limit=4)
    run_id = repo.save_scan(result)
    review = repo.market_review()
    assert review.run_id == run_id
    assert review.total == 4 and review.up_count == 4
    assert review.top_scores and review.sectors
