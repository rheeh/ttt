from datetime import date, datetime, timedelta, timezone
import io
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.analysis.models import DailyBar
from app.data_lake.history import DailyHistoryRouter, LakeTrainingProvider
from app.data_lake.jobs import CollectRequest, JobStore, LakeJobs, LakeSettings
from app.data_lake.reader import LakeReader, symbol_for
from app.market.daily_contract import BarSeries, daily_metadata
from app.market.trading_calendar import SHANGHAI

DAY = date(2026, 9, 24)


def publish(root, dataset, rows):
    pl = pytest.importorskip("polars")
    pytest.importorskip("cnequity")
    from cnequity.domain.schemas import DATASET_SCHEMAS
    from cnequity.domain.datasets import get_dataset
    from cnequity.domain.contracts import dataset_contract, contract_fingerprint
    from cnequity.storage import StagingWriter, compact_dataset
    from cnequity.storage.revisions import RevisionStore
    spec = get_dataset(dataset)
    target = root / ("derived" if dataset == "adj_factors" else "curated")
    run_id = uuid4().hex
    (root / "meta").mkdir(exist_ok=True)
    frame = pl.DataFrame([{**row, "source": "test-real-contract", "data_version": "test-v1",
                           "fetched_at": datetime.now(timezone.utc)} for row in rows],
                         schema=DATASET_SCHEMAS[dataset])
    StagingWriter(root / "staging").write_batch(dataset, run_id, "one", frame)
    changes = []
    compact_dataset(root / "staging", target, dataset, run_id, partition_col=spec.partition_col, changed_files=changes)
    return RevisionStore(root / "meta", root / "curated", root / "derived").commit(
        dataset, run_id=run_id, changed_files=changes, schema_version=dataset_contract(dataset)["schema_version"],
        contract_fingerprint=contract_fingerprint(dataset))


def raw(day, close=10):
    return {"symbol": "600519.SH", "trade_date": day, "open": close, "close": close, "high": close+1,
            "low": close-1, "volume": 1000, "amount": float(close*1000)}


@pytest.fixture
def lake(tmp_path, monkeypatch):
    monkeypatch.setattr("app.data_lake.reader.latest_session", lambda: DAY)
    return LakeReader(tmp_path)


def test_actual_cnequity_compaction_preserves_history_and_corrects_existing_key(lake):
    publish(lake.root, "daily_bars", [raw(DAY-timedelta(days=1)), raw(DAY)])
    first = lake.revisions(["daily_bars"])
    publish(lake.root, "daily_bars", [raw(DAY, 20)])
    from cnequity.query import load
    frame = load("daily_bars", data_root=lake.root).sort("trade_date")
    assert frame.height == 2 and frame["close"].to_list() == [10, 20]
    assert lake.revisions(["daily_bars"]) != first
    old = load("daily_bars", data_root=lake.root, revision_map=first).sort("trade_date")
    assert old["close"].to_list() == [10, 10]


def test_raw_equity_is_not_accepted_without_factors(lake):
    publish(lake.root, "daily_bars", [raw(DAY)])
    with pytest.raises(ValueError, match="adj_factors"):
        lake.bars("sh600519")


def test_reader_uses_exact_adjustment_separate_factors_and_pinned_revisions(lake):
    prior = DAY - timedelta(days=1)
    publish(lake.root, "daily_bars", [raw(prior, 20), raw(DAY, 10)])
    publish(lake.root, "adj_factors", [{"symbol":"600519.SH", "trade_date":day,"adjust_type":"hfq","factor":factor}
                                      for day,factor in [(prior,1.),(DAY,2.)]])
    bars = lake.bars("sh600519")
    assert [bar.close for bar in bars] == [10, 10]
    assert bars.source == "cnequity-local" and bars.volume_unit == "shares"
    assert set(daily_metadata(bars)["revisions"]) == {"daily_bars", "adj_factors"}


def test_index_does_not_require_stock_adjustment(lake):
    publish(lake.root, "index_bars", [{**raw(DAY),"symbol":"000001.SH","frequency":"1d"}])
    bars = lake.bars("sh000001")
    assert bars[0].close == 10 and bars.adjustment == "index_points"
    assert bars.volume_unit == "cnequity_index_native"


@pytest.mark.parametrize("code,volume,unit", [("sh600519",10000,"shares"),("sh000001",100,"tencent_index_native")])
def test_fallback_volume_units_survive_cache_reload(monkeypatch,tmp_path,code,volume,unit):
    monkeypatch.setattr("app.data_lake.history.latest_session", lambda: DAY)
    def missing(*a): raise ValueError("not collected")
    router = DailyHistoryRouter(SimpleNamespace(bars=missing), cache_path=tmp_path / "app.sqlite3")
    rows = [[DAY.isoformat(),10,10,11,9,100]]
    payload = {"code":0,"data":{code:{"day" if code == "sh000001" else "qfqday":rows}}}
    monkeypatch.setattr("app.data_lake.history.urlopen",lambda *a,**k:io.BytesIO(json.dumps(payload).encode()))
    first = router.fetch_bars(code,1)
    monkeypatch.setattr(router,"fetch_remote",lambda *a:pytest.fail("must reuse normalized cache"))
    cached = router.fetch_bars(code,1)
    assert first[0].volume == cached[0].volume == volume
    assert first.volume_unit == cached.volume_unit == unit
    assert first.adjustment == cached.adjustment


def test_financial_reader_maps_upstream_long_format_and_preserves_pit_limit(lake):
    publish(lake.root, "financial_statement_items", [{"symbol":"600519.SH","report_period":"2026Q2",
        "statement_type":"indicator","item_code":key,"item_value":value,"announce_date":date(2026,8,15)}
        for key,value in [("revenue_yoy",2.),("net_profit_yoy",3.),("roe",15.)]])
    result = lake.finance("sh600519")
    assert result.revenue_yoy == 2 and result.roe == 15
    assert result.report_date == "2026-06-30" and result.pit_quality == "reconstructed"


def history(day=DAY):
    bars = BarSeries([DailyBar(trade_date=day-timedelta(days=130-i),open=10,close=10,high=11,low=9,volume=100) for i in range(131)])
    bars.source = "cnequity-local"
    return bars


def test_router_local_first_never_calls_the_network(monkeypatch):
    monkeypatch.setattr("app.data_lake.history.latest_session", lambda: DAY)
    local = history()
    router = DailyHistoryRouter(SimpleNamespace(bars=lambda *a:local))
    monkeypatch.setattr(router,"fetch_remote",lambda *a: pytest.fail("network must not be called"))
    assert router.fetch_bars("sh600519") is local


def test_stale_lake_falls_back_without_writing_qfq_into_the_lake(monkeypatch,tmp_path):
    monkeypatch.setattr("app.data_lake.history.latest_session", lambda: DAY)
    local = history(DAY-timedelta(days=1))
    remote = history(); remote.source = "tencent-kline"
    router = DailyHistoryRouter(SimpleNamespace(bars=lambda *a:local), cache_path=tmp_path / "app.sqlite3")
    monkeypatch.setattr(router,"fetch_remote",lambda *a: remote)
    result = router.fetch_bars("sh600519",120)
    assert result.source == "tencent-kline" and "尚未更新" in result.fallback_reason
    assert local.source == "cnequity-local" and not local.error
    assert not (tmp_path / "curated").exists()


def test_failed_fallback_retains_stale_data_with_explicit_error(monkeypatch):
    monkeypatch.setattr("app.data_lake.history.latest_session", lambda: DAY)
    local = history(DAY-timedelta(days=1))
    router = DailyHistoryRouter(SimpleNamespace(bars=lambda *a:local))
    def fail(*a): raise OSError("network down")
    monkeypatch.setattr(router,"fetch_remote",fail)
    assert "network down" in router.fetch_bars("sh600519").error


def test_training_accepts_saved_history_without_requiring_today(monkeypatch):
    local = history(DAY-timedelta(days=30))
    router = DailyHistoryRouter(SimpleNamespace(bars=lambda *a:local))
    monkeypatch.setattr(router,"fetch_remote",lambda *a: pytest.fail("must use saved history"))
    assert len(LakeTrainingProvider(router).fetch("sh600519")) == 131


def test_training_prefers_lake_over_old_cache_and_records_real_source(tmp_path):
    from app.training.service import TrainingService
    local = history(DAY-timedelta(days=30))
    provider = LakeTrainingProvider(DailyHistoryRouter(SimpleNamespace(bars=lambda *a:local)))
    provider.preferred_codes = lambda: {"sh600519"}
    stock = SimpleNamespace(code="sh600519",name="样例",asset_type="stock")
    pool = SimpleNamespace(stocks=[stock])
    service = TrainingService(tmp_path / "training.sqlite3",pool,lambda:[],provider)
    old = [dict(bar.model_dump(mode="json"),open=20,close=20,high=21,low=19) for bar in local]
    with service.connect() as db:
        db.execute("INSERT INTO kline_history VALUES (?,?,?)",("sh600519","old",json.dumps(old)))
    session = service.create("reference",20)
    assert all(bar["close"] == 10 for bar in session["bars"])
    assert session["data_source"] == "CNEquity 前复权日线 · 本地数据湖"
    assert "sh600519" not in json.dumps(session)  # The source label must not reveal identity.
    restarted = TrainingService(service.path,pool,lambda:[],provider)
    assert restarted.get(session["id"])["data_source"] == session["data_source"]
    with service.connect() as db:
        assert db.execute("SELECT fetched_at FROM kline_history").fetchone()[0] == "old"


def test_symbol_normalization_and_validation():
    assert symbol_for("sh600519") == "600519.SH"
    assert symbol_for("000001.sz") == "000001.SZ"
    with pytest.raises(ValueError): symbol_for("../../etc/passwd")
    with pytest.raises(ValueError): LakeSettings(symbols=[])


def test_jobs_have_cross_instance_single_flight_and_settings_persist(tmp_path):
    a, b = JobStore(tmp_path / "jobs.sqlite3"), JobStore(tmp_path / "jobs.sqlite3")
    a.configure(LakeSettings(symbols=["sh600519"],auto_update=False))
    assert b.settings().symbols == ["600519.SH"] and not b.settings().auto_update
    job = a.create(CollectRequest())
    with pytest.raises(ValueError, match="运行中"): b.create(CollectRequest())
    job["status"] = "partial"; a.save(job)
    assert b.create(CollectRequest())["id"] != job["id"]


def test_scheduler_does_not_refetch_completed_session_on_holiday(tmp_path):
    manager = LakeJobs(tmp_path / "lake",tmp_path / "app.sqlite3")
    now = datetime(2026,9,25,17,tzinfo=SHANGHAI)
    assert manager.next_request(now) is None
    job = manager.store.create(CollectRequest())
    job.update(status="success",trade_date="2026-09-24")
    manager.store.save(job)
    assert manager.next_request(now) is None
    assert manager.next_request(datetime(2026,9,28,17,tzinfo=SHANGHAI)).mode == "update"
    assert manager.next_request(datetime(2027,1,4,17,tzinfo=SHANGHAI)) is None


def test_empty_status_and_records_do_not_trigger_collection(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("STOCK_RESEARCH_DATA_DIR",str(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/data-lake/status")
        assert response.status_code == 200 and response.json()["jobs"] == []
        assert not (tmp_path / "cnequity").exists()
        assert client.get('/api/data-lake/records/daily_bars?code=sh600519').status_code == 503
        assert client.get('/api/data-lake/records/not_allowed').status_code == 404
        assert client.put('/api/data-lake/settings',json={"symbols":["../bad"]}).status_code == 422
