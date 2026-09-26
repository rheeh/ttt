import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from app.analysis.models import DailyBar
from app.market.industry_radar import IndustryRadarProvider
from app.market.constituent_history import build_equal_weighted_industry_series
from app.analysis.industry_stage import classify_stage
from app.database import CandidateRepository


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, _orient):
        return self.rows


class FakeAkshare:
    @staticmethod
    def stock_sector_spot(indicator):
        assert indicator == "新浪行业"
        return FakeFrame([{"label": "hangye_1", "板块": "示例行业", "涨跌幅": "1.2", "公司家数": 2}])

    @staticmethod
    def stock_sector_detail(sector):
        assert sector == "hangye_1"
        return FakeFrame([
            {"symbol": "600001", "name": "示例甲", "changepercent": "2.0"},
            {"symbol": "600002", "name": "示例乙", "changepercent": "-1.0"},
        ])


def test_radar_uses_sina_industry_snapshot(monkeypatch):
    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare)
    result = IndustryRadarProvider().fetch()
    assert result.scope == "all_industries"
    assert result.source == "sina-industry-radar"
    assert result.other[0].name == "示例行业"
    assert result.other[0].stage == "数据不足"
    assert result.other[0].up_count == 1
    assert result.other[0].constituents[0].code == "600001"
    assert result.detail_board_count == 1 and result.detail_constituent_observed == 2
    assert "历史K线" in result.degraded_reasons[0]


def test_radar_does_not_call_eastmoney_fallback(monkeypatch):
    class NoDataAkshare:
        @staticmethod
        def stock_sector_spot(indicator):
            raise OSError("sina unavailable")

    monkeypatch.setitem(sys.modules, "akshare", NoDataAkshare)
    result = IndustryRadarProvider().fetch()
    assert result.data_status == "error"
    assert "新浪行业数据暂时不可用" in result.degraded_reasons[0]
    assert "eastmoney" not in result.source


def test_stage_rule_stays_data_insufficient_before_60_days():
    result = classify_stage(
        close=10, history_closes=[9.5] * 20, return_5d_pct=2, return_20d_pct=4,
        relative_return_20d_pct=1, breadth_ma20_pct=60, volume_ratio=1.4,
    )
    assert result.stage == "数据不足"
    assert "60" in result.evidence[0]


def test_industry_signal_verification_calculates_mfe_mae(tmp_path):
    repo = CandidateRepository(Path(tmp_path) / "research.sqlite")
    start = date(2026, 1, 1)
    with repo._connect() as connection:
        connection.execute("INSERT INTO industry_master(industry_id, name, taxonomy, source, updated_at) VALUES ('industry:test', '测试行业', 'industry', 'test', '2026-01-01T00:00:00Z')")
        for index, close in enumerate([100, 110, 95, 120, 115, 130, 125]):
            trade_date = start + timedelta(days=index)
            connection.execute("INSERT INTO industry_daily(industry_id, trade_date, close, payload_json) VALUES ('industry:test', ?, ?, '{}')", (trade_date.isoformat(), close))
            connection.execute("INSERT INTO industry_benchmark_daily(benchmark_code, trade_date, close) VALUES ('sh000300', ?, ?)", (trade_date.isoformat(), 100 + index))
        connection.execute("INSERT INTO industry_signals(industry_id, trade_date, stage, score, rule_version, evidence_json, risk_json, signal_direction, confirmation_days) VALUES ('industry:test', ?, '底部改善', 65, 'test-v1', '[]', '[]', 'improving', 2)", (start.isoformat(),))
    result = repo.verify_industry_signals(start + timedelta(days=6))
    one_day = next(item for item in result.outcomes if item.horizon == "1d")
    assert one_day.status == "verified"
    assert one_day.execution_date == start + timedelta(days=1)
    assert one_day.return_pct == 0
    five_day = next(item for item in result.outcomes if item.horizon == "5d")
    assert five_day.return_pct == round((130 / 110 - 1) * 100, 4)
    assert five_day.mfe_pct == round((130 / 110 - 1) * 100, 4)
    assert five_day.mae_pct == round((95 / 110 - 1) * 100, 4)


def test_derived_industry_series_uses_true_ma_breadth_and_trade_dates():
    histories = {}
    start = date(2026, 1, 1)
    for index, code in enumerate(("a", "b", "c", "d", "e")):
        bars = []
        for day in range(120):
            close = 100 + day if code in {"a", "d"} else 220 - day if code in {"b", "e"} else 100
            bars.append(DailyBar(trade_date=start + timedelta(days=day), open=close, close=close, high=close, low=close, volume=100 + index))
        histories[code] = bars
    rows = build_equal_weighted_industry_series(list(histories), histories)
    assert len(rows) == 120
    assert rows[-1]["trade_date"] == start + timedelta(days=119)
    assert rows[-1]["breadth_ma20_pct"] == 40
    assert rows[-1]["breadth_ma60_pct"] == 40
    assert rows[-1]["coverage_pct"] == 100


def test_stage_change_requires_two_consecutive_candidates(monkeypatch):
    def fake_classify(*, close, **_kwargs):
        return SimpleNamespace(stage="下跌中" if close == 100 else "底部改善")

    monkeypatch.setattr("app.market.industry_radar.classify_stage", fake_classify)
    series = [{"trade_date": date(2026, 1, 1) + timedelta(days=index), "close": 100 if index < 62 else 200, "breadth_ma20_pct": 40, "breadth_ma60_pct": 40, "volume_ratio": 1.0, "advance_ratio_pct": 50, "new_high_ratio_pct": 0, "coverage_pct": 100, "volume": 100} for index in range(64)]
    item = IndustryRadarProvider._apply_index_series(IndustryRadarProvider()._item("测试行业", datetime.now(timezone.utc), industry_key="industry:test"), series)
    assert item.stage == "底部改善"
    assert item.stage_confirmation_days == 2
    assert item.previous_stage == "下跌中"
    assert item.stage_changed is True
