from app.market.industry_scheduler import IndustryRadarScheduler


def test_scheduler_run_now_records_success():
    calls = []
    scheduler = IndustryRadarScheduler(lambda: calls.append("refresh") or {"ok": True})
    result = scheduler.run_now()
    assert result == {"ok": True}
    assert calls == ["refresh"]
    assert scheduler.last_success_at is not None
    assert scheduler.last_run_date is not None
    assert scheduler.last_error is None


def test_scheduler_preserves_error_status():
    scheduler = IndustryRadarScheduler(lambda: (_ for _ in ()).throw(RuntimeError("upstream down")))
    try:
        scheduler.run_now()
    except RuntimeError:
        pass
    assert scheduler.last_success_at is None
    assert scheduler.last_error == "upstream down"
