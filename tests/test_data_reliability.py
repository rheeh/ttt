"""Regression checks for price semantics, coverage and recoverable ingestion."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace
import sqlite3

import pytest

from app.analysis.models import DailyBar
from app.analysis.service import IndividualAnalysisService
from app.market.constituent_history import TencentConstituentHistoryProvider, build_equal_weighted_industry_series
from app.market.daily_contract import BarSeries, DailyDataError, daily_metadata, parse_tencent_daily
from app.market.history_cache import HistoryCache
from app.market.industry_radar import IndustryRadarProvider
from app.market.industry_scheduler import IndustryRadarScheduler
from app.market.trading_calendar import SHANGHAI, is_session, latest_session


def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=SHANGHAI)


NOW = at("2026-09-24T16:30:00")
ROW = ["2026-09-24", "10", "11", "12", "9", "0"]


def payload(rows, *, key="qfqday", code="sh600519"):
    return {"code": 0, "data": {code: {key: rows}}}


def history(count=150):
    start = date(2026, 9, 24) - timedelta(days=count - 1)
    return BarSeries([DailyBar(trade_date=start + timedelta(days=i), open=10+i/100,
                              close=10+i/100, high=11+i/100, low=9+i/100, volume=100)
                      for i in range(count)])


@pytest.mark.parametrize("stamp,expected", [
    ("2026-09-25T16:30:00", "2026-09-24"),
    ("2026-09-28T10:00:00", "2026-09-24"),
    ("2026-09-28T15:09:00", "2026-09-24"),
    ("2026-09-28T15:10:00", "2026-09-28"),
    ("2026-10-07T17:00:00", "2026-09-30"),
    ("2026-02-23T17:00:00", "2026-02-13"),
    ("2025-10-08T17:00:00", "2025-09-30"),
])
def test_completed_session_obeys_exchange_holidays_and_close(stamp, expected):
    assert latest_session(at(stamp)).isoformat() == expected


def test_unknown_year_and_makeup_weekend_are_not_assumed_open():
    assert is_session(date(2026, 10, 10)) is False
    assert is_session(date(2027, 1, 4)) is None
    assert latest_session(at("2027-01-04T17:00:00")) is None
    assert latest_session(at("2026-09-28T10:00:00"), completed=False) == date(2026, 9, 28)


def test_raw_equity_fails_but_explicit_index_uses_index_points():
    with pytest.raises(DailyDataError, match="qfqday"):
        parse_tencent_daily(payload([ROW], key="day"), "sh600519", now=NOW)
    index = parse_tencent_daily(payload([ROW], key="day", code="sh000001"), "sh000001", now=NOW)
    assert index[0].close == 11 and index.adjustment == "index_points"


@pytest.mark.parametrize("rows", [
    [ROW, ROW], [ROW, ["2026-09-23", 10, 10, 10, 10, 1]],
    [["2026-09-24", 10, "nan", 12, 9, 1]], [["2026-09-24", 10, 11, 10, 9, 1]],
    [["2026-09-24", 10, 11, 12, 9, -1]], [["2026-09-24", 10]],
    [["2026-09-28", 10, 11, 12, 9, 1]],
])
def test_bad_rows_reject_the_whole_response(rows):
    with pytest.raises(DailyDataError):
        parse_tencent_daily(payload(rows), "sh600519", now=NOW)


def test_zero_volume_survives_and_unfinished_bar_is_excluded():
    bars = parse_tencent_daily(payload([ROW]), "sh600519", now=NOW)
    assert bars[0].volume == 0
    assert not parse_tencent_daily(payload([ROW]), "sh600519", now=at("2026-09-24T10:00:00"))
    first = daily_metadata(bars)
    assert first["adjustment_anchor"] == "vendor_current"
    assert first["content_sha256"] == daily_metadata(BarSeries(bars))["content_sha256"]
    corrected = BarSeries([bars[0].model_copy(update={"close": 10.5})])
    assert daily_metadata(corrected)["content_sha256"] != first["content_sha256"]


def test_freshness_checks_dates_not_presence_and_keeps_failure_reason():
    bars = parse_tencent_daily(payload([ROW]), "sh600519", now=NOW)
    assert IndividualAnalysisService._daily_freshness(bars, now=at("2026-09-26T12:00:00"))["state"] == "fresh"
    assert IndividualAnalysisService._daily_freshness(bars, now=at("2026-09-28T17:00:00"))["state"] == "warning"
    assert IndividualAnalysisService._daily_freshness(bars, now=at("2027-01-04T17:00:00"))["state"] == "unknown"
    assert IndividualAnalysisService._daily_freshness(BarSeries(error="缺少qfqday"), now=NOW)["note"] == "缺少qfqday"


def test_industry_coverage_uses_all_requested_members_and_blocks_stage():
    codes = [f"test{i}" for i in range(10)]
    rows = build_equal_weighted_industry_series(codes, {code: history() for code in codes[:5]})
    assert rows[-1]["coverage_pct"] == 50
    assert rows[-1]["member_count"] == 10
    assert rows[-1]["missing_members"] == codes[5:]
    item = IndustryRadarProvider()._item("样例行业", NOW, industry_key="industry:test")
    result = IndustryRadarProvider._apply_index_series(item, rows)
    assert result.stage == "数据不足" and not result.stage_changed
    assert result.history_coverage_pct == 50
    assert any("80%" in risk for risk in result.risks)


def test_industry_stale_series_cannot_confirm_a_signal(monkeypatch):
    monkeypatch.setattr("app.market.industry_radar.classify_stage", lambda **_: SimpleNamespace(stage="底部改善"))
    codes = list("abcde")
    rows = build_equal_weighted_industry_series(codes, {code: history() for code in codes})
    item = IndustryRadarProvider()._item("样例行业", NOW, industry_key="industry:test")
    result = IndustryRadarProvider._apply_index_series(item, rows, expected_trade_date=date(2026, 9, 28))
    assert result.stage == "数据不足" and not result.stage_changed


def test_partial_fetch_retries_only_failed_symbols_after_restart(tmp_path, monkeypatch):
    path = tmp_path / "research.sqlite3"
    monkeypatch.setattr("app.market.constituent_history.latest_session", lambda: date(2026, 9, 24))
    provider = TencentConstituentHistoryProvider(cache_path=path)
    def fetch(code):
        if code == "bad":
            raise OSError("upstream down")
        return history()
    monkeypatch.setattr(provider, "_fetch_one", fetch)
    first = provider.fetch(["good", "bad"])
    assert list(first) == ["good"] and first.failures == {"bad": "upstream down"}
    restarted = TencentConstituentHistoryProvider(cache_path=path)
    calls = []
    monkeypatch.setattr(restarted, "_fetch_one", lambda code: calls.append(code) or history())
    second = restarted.fetch(["good", "bad"])
    assert calls == ["bad"] and second.cache_hits == ["good"]
    assert not second.failures
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT status, attempts FROM constituent_fetch_receipts WHERE code='bad'").fetchone() == ("ok", 2)


def test_cache_replaces_whole_qfq_window_and_detects_corruption(tmp_path):
    cache = HistoryCache(tmp_path / "cache.sqlite3")
    cache.save("a", history())
    changed = BarSeries([bar.model_copy(update={key: getattr(bar, key) / 2 for key in ("open", "close", "high", "low")}) for bar in history()])
    cache.save("a", changed)
    got = cache.get("a", date(2026, 9, 24), 150)
    assert len(got) == 150 and got[0].close == changed[0].close
    assert cache.get("a", date(2026, 9, 28), 150) is None
    with sqlite3.connect(cache.path) as db:
        db.execute("UPDATE constituent_history_cache SET bars_json='[]'")
    assert cache.get("a", date(2026, 9, 24), 150) is None


def test_scheduler_holiday_backoff_restart_and_retry_budget(tmp_path):
    current = [NOW]
    def fail():
        raise RuntimeError("partial batch")
    path = tmp_path / "tasks.sqlite3"
    scheduler = IndustryRadarScheduler(fail, state_path=path, clock=lambda: current[0])
    assert scheduler.due()
    with pytest.raises(RuntimeError, match="partial batch"):
        scheduler.run_now()
    assert not scheduler.due()
    restarted = IndustryRadarScheduler(fail, state_path=path, clock=lambda: current[0])
    assert restarted.last_error == "partial batch" and restarted.attempts_today == 1
    for minutes in (5, 15):
        current[0] = NOW + timedelta(minutes=minutes)
        assert restarted.due()
        with pytest.raises(RuntimeError):
            restarted.run_now()
    current[0] = NOW + timedelta(hours=2)
    assert not restarted.due()
    assert not restarted.due(at("2026-09-25T17:00:00"))
    assert restarted.due(at("2026-09-28T17:00:00"))
    assert not restarted.due(at("2027-01-04T17:00:00"))


def test_scheduler_success_is_persistent_and_does_not_repeat(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    task = IndustryRadarScheduler(lambda: "done", state_path=path, clock=lambda: NOW)
    assert task.run_now() == "done"
    restarted = IndustryRadarScheduler(lambda: None, state_path=path, clock=lambda: NOW)
    assert not restarted.due() and restarted.last_error is None
    assert restarted.last_success_at == NOW and not restarted.status()["running"]


def test_failed_refresh_does_not_masquerade_as_cached_success(tmp_path):
    from app.main import _refresh_industry_snapshot
    from app.database import CandidateRepository
    from app.models import IndustryRadarResponse
    raw = IndustryRadarResponse(snapshot_at=NOW, source="test", data_status="error",
                               coverage_count=0, coverage_total=0, degraded_reasons=["upstream down"])
    provider = SimpleNamespace(fetch=lambda **_: raw)
    with pytest.raises(RuntimeError, match="upstream down"):
        _refresh_industry_snapshot(CandidateRepository(tmp_path / "research.sqlite3"), provider,
                                   include_history=True, require_complete=True)


def test_industry_get_never_fetches_or_writes_on_an_empty_lake(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("STOCK_RESEARCH_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        def unexpected_fetch(**_):
            raise AssertionError("GET must not fetch")
        client.app.state.industry_radar.fetch = unexpected_fetch
        response = client.get("/api/market/industry-radar")
        assert response.status_code == 200
        assert response.json()["coverage_count"] == 0
        assert response.json()["last_success_trade_date"] is None
        assert client.app.state.candidates.list_industry_history() == []


def test_manual_refresh_failure_keeps_cache_but_reports_the_failure(tmp_path):
    from app.main import _refresh_industry_snapshot
    from app.database import CandidateRepository
    from app.models import IndustryRadarResponse
    repo = CandidateRepository(tmp_path / "research.sqlite3")
    old = IndustryRadarResponse(snapshot_at=NOW, source="sina-industry-radar", data_status="ok",
                               coverage_count=1, coverage_total=1)
    repo.save_industry_snapshot(old)
    failed = old.model_copy(update={"data_status": "error", "degraded_reasons": ["upstream down"]})
    result = _refresh_industry_snapshot(repo, SimpleNamespace(fetch=lambda **_: failed))
    assert result.data_status == "degraded" and "upstream down" in result.degraded_reasons
    assert result.snapshot_at == old.snapshot_at and result.coverage_count == 1
    assert repo.latest_industry_snapshot().data_status == "ok"


def test_snapshot_fetch_date_is_not_invented_as_trade_date(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("STOCK_RESEARCH_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        item = IndustryRadarProvider()._item("样例行业", NOW, industry_key="industry:test")
        snapshot = IndustryRadarProvider._response([item], NOW, [])
        client.app.state.candidates.save_industry_snapshot(snapshot)
        response = client.get("/api/market/industry-radar")
        assert response.json()["last_success_trade_date"] is None
