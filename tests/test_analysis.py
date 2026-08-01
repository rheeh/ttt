from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.analysis.indicators import calculate_indicators
from app.analysis.data_sources import FinanceFacts, FundFlowFacts, IndustryFacts, NewsFacts, NewsItem
from app.analysis import data_sources
from app.analysis import service as analysis_service_module
from app.analysis.models import DailyBar
from app.analysis.service import IndividualAnalysisService
from app.database import CandidateRepository
from app.main import app
from app.market.scanner import StockPool
from app.models import QuoteSnapshot, StockPreset, WatchlistCreate


ROOT = Path(__file__).parents[1]
POOL = ROOT / "packages" / "stock-presets" / "group-original-pool.json"


def bars(count: int = 80) -> list[DailyBar]:
    return [DailyBar(
        trade_date=date(2026, 1, 1) + timedelta(days=index), open=10 + index * .1,
        close=10 + index * .1, high=10 + index * .1 + .2, low=10 + index * .1 - .1, volume=100 + index,
    ) for index in range(count)]


def test_indicators_calculate_macd_rsi_and_levels():
    result = calculate_indicators(bars())
    assert result.bar_count == 80
    assert result.ma20 is not None
    assert result.macd is not None
    assert result.rsi14 == 100
    assert result.support20 < result.resistance20


def test_eastmoney_fund_flow_and_finance_parsers(monkeypatch):
    payloads = [
        {"data": {"klines": [
            "2026-07-30,100000000,-146952272,-236328416,-17517488,400798176,5.00",
            "2026-07-31,383280688,-146952272,-236328416,-17517488,400798176,11.91",
        ]}},
        {"result": {"data": [{"NOTICE_DATE": "2026-07-31 00:00:00", "TOTALOPERATEREVE": 100, "TOTALOPERATEREVETZ": 12.5, "PARENTNETPROFIT": 20, "PARENTNETPROFITTZ": 18.0}]}},
    ]
    monkeypatch.setattr(data_sources, "_json_request", lambda *args, **kwargs: payloads.pop(0))
    flow = data_sources.EastmoneyFundFlowProvider().fetch("sz002432")
    finance = data_sources.EastmoneyFinanceProvider().fetch("sz002432")
    assert flow.status == "ok" and flow.main_inflow == 3.8328 and flow.main_flow_ratio == .1191
    assert flow.endpoint == "push2his.eastmoney.com"
    assert finance.status == "ok" and finance.revenue_yoy == 12.5 and finance.profit_yoy == 18


def test_fund_flow_tries_push2his_and_fallback_hosts(monkeypatch):
    calls = []

    def request(url, _timeout):
        calls.append(url)
        if "push2his.eastmoney.com" in url:
            raise OSError("blocked")
        return {"data": {"klines": ["2026-07-31,200000000,0,0,0,0,2.5"]}}

    monkeypatch.setattr(data_sources, "_json_request", request)
    result = data_sources.EastmoneyFundFlowProvider().fetch("sh600519")
    assert result.status == "ok" and result.trade_date == "2026-07-31"
    assert result.main_inflow == 2 and result.main_flow_ratio == .025
    assert "push2his.eastmoney.com" in calls[0]
    assert any("push2.eastmoney.com" in url for url in calls[1:])


def test_industry_tries_alternate_hosts(monkeypatch):
    calls = []

    def request(url, _timeout):
        calls.append(url)
        if "17.push2.eastmoney.com" in url:
            raise OSError("blocked")
        if "/api/qt/stock/get" in url:
            return {"data": {"f127": "白酒"}}
        return {"data": {"diff": {"1": {"f14": "白酒", "f3": "1.2", "f62": "100000000"}}}}

    monkeypatch.setattr(data_sources, "_json_request", request)
    provider = data_sources.EastmoneyIndustryProvider()
    provider._cache = None
    result = provider.fetch("sh600519")
    assert result.status == "ok" and result.name == "白酒" and result.rank == 1
    assert result.endpoint == "push2.eastmoney.com; push2.eastmoney.com"
    assert any("push2.eastmoney.com" in url for url in calls)


def test_eastmoney_news_jsonp_parser(monkeypatch):
    provider = data_sources.EastmoneyNewsProvider()
    monkeypatch.setattr(provider, "_request_text", lambda url: 'jQuery({"result":{"cmsArticleWebOld":[{"title":"公司业绩增长超预期","mediaName":"财经","date":"2026-07-31","url":"https://example.test"}]}})')
    result = provider.fetch("九安医疗")
    assert result.status == "ok" and result.items[0].sentiment == "bull"


def test_source_cache_returns_stale_snapshot(tmp_path):
    repo = CandidateRepository(tmp_path / "research.sqlite3")
    service = IndividualAnalysisService(StockPool(POOL), FakeQuoteProvider(), cache=repo)
    fresh = FundFlowFacts(trade_date="2026-07-31", main_inflow=1.2, main_flow_ratio=.03, status="ok")
    repo.save_source_cache("sz002432", fresh.source, fresh.fetched_at.isoformat(), fresh.model_dump(mode="json"))
    stale = service._with_cache("sz002432", FundFlowFacts(status="error", error="remote closed"), FundFlowFacts)
    assert stale.status == "stale" and stale.cache_used is True and stale.main_flow_ratio == .03


def test_source_cache_does_not_use_expired_snapshot(tmp_path):
    repo = CandidateRepository(tmp_path / "research.sqlite3")
    service = IndividualAnalysisService(StockPool(POOL), FakeQuoteProvider(), cache=repo)
    old = datetime.now(timezone.utc) - timedelta(days=10)
    cached = FundFlowFacts(trade_date="2026-07-21", main_inflow=1.2, main_flow_ratio=.03, status="ok", fetched_at=old)
    repo.save_source_cache("sz002432", cached.source, old.isoformat(), cached.model_dump(mode="json"))
    expired = service._with_cache("sz002432", FundFlowFacts(status="error", error="remote closed"), FundFlowFacts)
    assert expired.status == "error" and expired.cache_expired is True and expired.main_flow_ratio is None


class FakeQuoteProvider:
    def fetch(self, presets):
        now = datetime(2026, 7, 31, 8, tzinfo=timezone.utc)
        return [QuoteSnapshot(
            stock_code=item.code, stock_name=item.name, price=100, pe=20, pb=2,
            change_pct=2, turnover_pct=3, amplitude_pct=4, trade_at=now, fetched_at=now,
            source="fixture", status="degraded", missing_fields=["main_flow_ratio", "quality_score"],
        ) for item in presets]


class FakeAnalysisService(IndividualAnalysisService):
    def fetch_bars(self, code, days=252):
        return bars()

    def fetch_supplementary(self, code, name):
        return (
            FundFlowFacts(trade_date="2026-07-31", main_inflow=1.2, main_flow_ratio=0.03, status="ok"),
            FinanceFacts(report_date="2026-06-30", revenue=100, revenue_yoy=12, profit=20, profit_yoy=18, status="ok"),
            IndustryFacts(name="白酒", rank=8, total=100, change_pct=1.5, main_inflow=3.2, status="ok"),
            NewsFacts(items=[NewsItem(title="业绩增长", sentiment="bull")], status="ok"),
        )


def test_analysis_api_saves_report_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCK_RESEARCH_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.app.state.analysis_service = FakeAnalysisService(
            client.app.state.pool, FakeQuoteProvider(),
        )
        response = client.post("/api/analysis", json={"stock": "600519"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["report_id"] == 1
        assert payload["technical"]["ma20"] is not None
        assert payload["rocket"]["dimensions"] and payload["status"] == "ok"
        assert payload["core_status"] == "ok"
        assert payload["legacy_score_status"] == "degraded"
        assert payload["zhixing_index"] >= 0
        assert len(payload["factors"]) == 10
        assert payload["factor_coverage"] == "10/10"
        assert payload["zhixing_confidence"] == 100
        assert payload["raw_score"] == payload["zhixing_index"]
        assert payload["freshness"]["quote"]["state"] in {"fresh", "warning"}
        assert payload["freshness"]["daily_bars"]["latest_trade_date"]
        assert len(payload["radar"]) == 6
        assert payload["fund_flow"]["status"] == "ok"
        assert payload["finance"]["revenue_yoy"] == 12
        assert payload["industry"]["rank"] == 8
        assert payload["news"]["items"][0]["sentiment"] == "bull"
        assert payload["weekly"]["bar_count"] > 0
        assert payload["diagnosis"]["summary"]
        stored = client.get(f"/api/analysis/{payload['report_id']}")
        assert stored.status_code == 200
        assert stored.json()["stock_code"] == "sh600519"
        history = client.get("/api/analysis?limit=5")
        assert history.status_code == 200 and history.json()[0]["report_id"] == payload["report_id"]
        with client.app.state.candidates._connect() as connection:
            fact_types = {row[0] for row in connection.execute("SELECT fact_type FROM analysis_facts WHERE report_id = ?", (payload["report_id"],))}
        assert {"fund_flow", "finance", "industry", "news"}.issubset(fact_types)


def test_compare_api_analyzes_two_stocks_in_parallel(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCK_RESEARCH_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        client.app.state.analysis_service = FakeAnalysisService(client.app.state.pool, FakeQuoteProvider())
        response = client.post("/api/analysis/compare", json={"stocks": ["sh603501", "sz002371"]})
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["reports"]) == 2
        assert payload["errors"] == {}
        assert {item["stock_code"] for item in payload["reports"]} == {"sh603501", "sz002371"}


def test_name_resolution_can_fall_back_outside_fixed_pool(monkeypatch):
    service = IndividualAnalysisService(StockPool(POOL), FakeQuoteProvider())
    monkeypatch.setattr(service, "_search_name", lambda value: StockPreset(secid="sz002432", code="sz002432", name=value, sector="其他"))
    resolved = service.resolve("九安医疗")
    assert resolved.name == "九安医疗"
    assert resolved.code == "sz002432"


def test_remote_search_requests_multiple_candidates_and_handles_empty_data(monkeypatch):
    service = IndividualAnalysisService(StockPool(POOL), FakeQuoteProvider())
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return '{"QuotationCodeTable":{"Data":[{"Code":"000538","Name":"云南白药","SecurityTypeName":"深A"},{"Code":"000878","Name":"云南铜业","SecurityTypeName":"深A"}]}}'.encode()

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return Response()

    monkeypatch.setattr(analysis_service_module, "urlopen", fake_urlopen)
    rows = service._search_remote("云南", limit=20)
    assert [row.name for row in rows] == ["云南白药", "云南铜业"]
    assert "count=80" in calls[0]

    monkeypatch.setattr(analysis_service_module, "urlopen", lambda *_args, **_kwargs: type("R", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_: False, "read": lambda self: b'{"QuotationCodeTable":{"Data":null}}'})())
    assert service._search_remote("不存在", limit=20) == []


def test_prefixed_code_resolves_without_remote_search(monkeypatch):
    service = IndividualAnalysisService(StockPool(POOL), FakeQuoteProvider())
    monkeypatch.setattr(service, "_search_name", lambda _value: (_ for _ in ()).throw(AssertionError("should not search remote")))
    assert service.resolve("sz002428").code == "sz002428"


def test_watchlist_is_user_managed(tmp_path):
    repo = CandidateRepository(tmp_path / "research.sqlite3")
    saved = repo.add_watchlist(WatchlistCreate(code="sz002432", name="九安医疗"))
    assert saved.code == "sz002432"
    assert repo.list_watchlist()[0].name == "九安医疗"
    assert repo.delete_watchlist("sz002432") is True
    assert repo.list_watchlist() == []
