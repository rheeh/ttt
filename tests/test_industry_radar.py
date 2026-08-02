import sys

from app.market.industry_radar import IndustryRadarProvider


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
        return FakeFrame([{"changepercent": "2.0"}, {"changepercent": "-1.0"}])


def test_radar_uses_sina_industry_snapshot(monkeypatch):
    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare)
    result = IndustryRadarProvider().fetch()
    assert result.scope == "all_industries"
    assert result.source == "sina-industry-radar"
    assert result.other[0].name == "示例行业"
    assert result.other[0].stage == "数据不足"
    assert result.other[0].up_count == 1
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
