import sys
from datetime import datetime, timezone

from app.market.industry_radar import IndustryRadarProvider


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, _orient):
        return self.rows


class FakeAkshare:
    @staticmethod
    def stock_board_industry_name_em():
        return FakeFrame([{"板块名称": "示例行业", "涨跌幅": "1.2"}])

    @staticmethod
    def stock_board_industry_hist_em(**_kwargs):
        raise OSError("history unavailable")


def test_radar_does_not_fallback_to_legacy_pool(monkeypatch):
    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare)
    result = IndustryRadarProvider().fetch()
    assert result.scope == "all_industries"
    assert result.coverage_count == 0
    assert result.data_status == "error"
    assert result.other[0].risks == ["历史行情不可用：history unavailable"]


def test_radar_error_item_is_explicitly_unscored():
    item = IndustryRadarProvider._error_item("示例行业", datetime.now(timezone.utc), "no data")
    assert item.score is None
    assert item.status == "error"
    assert item.stage == "下跌中"
