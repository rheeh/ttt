from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.analysis.indicators import calculate_indicators
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
        assert payload["rocket"]["dimensions"] and payload["status"] == "degraded"
        stored = client.get(f"/api/analysis/{payload['report_id']}")
        assert stored.status_code == 200
        assert stored.json()["stock_code"] == "sh600519"


def test_name_resolution_can_fall_back_outside_fixed_pool(monkeypatch):
    service = IndividualAnalysisService(StockPool(POOL), FakeQuoteProvider())
    monkeypatch.setattr(service, "_search_name", lambda value: StockPreset(secid="sz002432", code="sz002432", name=value, sector="其他"))
    resolved = service.resolve("九安医疗")
    assert resolved.name == "九安医疗"
    assert resolved.code == "sz002432"


def test_watchlist_is_user_managed(tmp_path):
    repo = CandidateRepository(tmp_path / "research.sqlite3")
    saved = repo.add_watchlist(WatchlistCreate(code="sz002432", name="九安医疗"))
    assert saved.code == "sz002432"
    assert repo.list_watchlist()[0].name == "九安医疗"
    assert repo.delete_watchlist("sz002432") is True
    assert repo.list_watchlist() == []
