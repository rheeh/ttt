from pathlib import Path

from app.database import CandidateRepository
from datetime import datetime, timedelta, timezone

from app.models import CandidateCreate, CandidateUpdate, DataSourceHealth, IndustryRadarResponse, QuoteSnapshot, ScoreInput
from app.scoring import StrategyEngine


ROOT = Path(__file__).parents[1]
STRATEGY = ROOT / "packages" / "strategy-spec" / "group-original-v1.json"


def payload() -> CandidateCreate:
    return CandidateCreate(score_input=ScoreInput(
        stock_code="sh600519", stock_name="贵州茅台", sector="食品", price=1500,
        pe=24, pb=8, pe_percentile=.4, pb_percentile=.7, change_pct=1,
        turnover_pct=.3, amplitude_pct=2, main_flow_ratio=.03,
    ), note="等待确认")


def test_candidate_survives_repository_restart(tmp_path):
    db_path = tmp_path / "research.sqlite3"
    request = payload()
    result = StrategyEngine(STRATEGY).score(request.score_input)
    created = CandidateRepository(db_path).create(request, result)
    reopened = CandidateRepository(db_path)
    stored = reopened.get(created.id)
    assert stored.stock_code == "sh600519"
    assert stored.note == "等待确认"
    assert stored.dimensions
    assert [item.horizon for item in stored.performance] == ["1d", "5d", "20d", "60d"]


def test_candidate_status_can_be_updated(tmp_path):
    repo = CandidateRepository(tmp_path / "research.sqlite3")
    request = payload()
    created = repo.create(request, StrategyEngine(STRATEGY).score(request.score_input))
    updated = repo.update(created.id, CandidateUpdate(status="watching"))
    assert updated.status == "watching"


def test_candidate_performance_is_verified_from_later_snapshot(tmp_path):
    repo = CandidateRepository(tmp_path / "research.sqlite3")
    request = payload()
    created = repo.create(request, StrategyEngine(STRATEGY).score(request.score_input))
    one_day = repo.list_performance(created.id)[0]
    actual_trade_date = one_day.due_date + timedelta(days=1)
    while actual_trade_date.weekday() >= 5:
        actual_trade_date += timedelta(days=1)
    trade_at = datetime.combine(actual_trade_date, datetime.min.time(), tzinfo=timezone.utc)
    repo.save_quotes([QuoteSnapshot(
        stock_code=created.stock_code, stock_name=created.stock_name, price=1650,
        trade_at=trade_at, fetched_at=trade_at, source="fixture", status="ok",
    ), QuoteSnapshot(
        stock_code="sh000300", stock_name="沪深300", price=100,
        trade_at=created.selected_at - timedelta(days=1), fetched_at=created.selected_at,
        source="fixture", status="ok",
    ), QuoteSnapshot(
        stock_code="sh000300", stock_name="沪深300", price=110,
        trade_at=trade_at, fetched_at=trade_at, source="fixture", status="ok",
    )])
    outcomes = repo.verify_performance(actual_trade_date)
    verified = next(item for item in outcomes if item.horizon == "1d")
    assert verified.status == "verified"
    assert verified.return_pct == 10.0
    assert verified.realized_trade_date == actual_trade_date
    assert verified.benchmark_code == "sh000300"
    assert verified.relative_return_pct == 0
    summary = repo.performance_summary(one_day.due_date)
    one_day_summary = next(item for item in summary["horizon_summary"] if item.horizon == "1d")
    assert one_day_summary.verified == 1 and one_day_summary.win_rate_pct == 100
    assert one_day_summary.median_return_pct == 10 and one_day_summary.average_relative_return_pct == 0


def test_source_health_is_persisted(tmp_path):
    repo = CandidateRepository(tmp_path / "research.sqlite3")
    checked = datetime.now(timezone.utc)
    repo.save_source_health(DataSourceHealth(
        source="fixture", category="test", installed=True, accessible=True, valid=True,
        status="ok", checked_at=checked, response_ms=12, last_success_at=checked,
    ))
    stored = repo.list_source_health()
    assert stored[0].source == "fixture" and stored[0].response_ms == 12


def test_industry_snapshots_are_upserted_by_trade_day(tmp_path):
    repo = CandidateRepository(tmp_path / "research.sqlite3")
    snapshot = IndustryRadarResponse(
        snapshot_at=datetime(2026, 8, 2, 8, tzinfo=timezone.utc), source="fixture",
        data_status="degraded", coverage_count=0, coverage_total=1,
    )
    assert repo.save_industry_snapshot(snapshot) == 1
    assert repo.save_industry_snapshot(snapshot.model_copy(update={"snapshot_at": datetime(2026, 8, 2, 9, tzinfo=timezone.utc)})) == 1
