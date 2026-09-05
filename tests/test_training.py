import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.training.service import TrainingError, TrainingService, affordable, valid_bars


def bars(count=80):
    result = []
    day = date(2021, 1, 4)
    for index in range(count):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        price = 10 + index * .05
        result.append(dict(trade_date=day.isoformat(), open=price, close=price + .02, high=price + .10, low=price - .10, volume=1000))
        day += timedelta(days=1)
    return result


class Provider:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else bars()
        self.calls = 0

    def fetch(self, code):
        self.calls += 1
        return self.rows


def stock(code="sh600036", name="样例主板股", asset_type="stock"):
    return SimpleNamespace(code=code, name=name, asset_type=asset_type)


@pytest.fixture
def service(tmp_path):
    return TrainingService(tmp_path / 'training.sqlite3', SimpleNamespace(stocks=[stock()]), lambda: [], Provider())


def action(service, session, name, fraction=1, note=""):
    return service.act(session["id"], session["revision"], name, fraction, note)


def test_blind_payload_and_step_use_only_revealed_bars(service):
    session = service.create("reference", 20)
    assert session["step"] == 0 and len(session["bars"]) == 60
    serialized = json.dumps(session, ensure_ascii=False)
    for secret in ("sh600036", "样例主板股", "2021-01-04", "trade_date", "start_date", "fetched_at"):
        assert secret not in serialized
    assert session["reveal"] is None
    future_close = bars()[60]["close"]
    assert all(bar["close"] != future_close for bar in session["bars"])
    next_session = action(service, session, 'hold')
    assert len(next_session["bars"]) == 61
    assert next_session["bars"][-1]["close"] == future_close
    assert next_session["revision"] == 1


def test_next_open_lots_fees_and_t_plus_one(service):
    first = service.create("reference", 20)
    bought = action(service, first, 'buy', .5, '缩量回踩，试仓')
    trade = bought["actions"][-1]
    assert trade["price"] == bars()[60]["open"]
    assert trade["shares"] % 100 == 0 and trade["shares"] > 0
    assert trade["shares"] * trade["price"] + trade["fee"] <= 50000
    assert trade["note"] == '缩量回踩，试仓'
    sold = action(service, bought, 'sell')
    assert sold["step"] == 2 and sold["shares"] == 0
    sale = sold["actions"][-1]
    assert sale["price"] == bars()[61]["open"]
    gross = sale["price"] * sale["shares"]
    assert sale["fee"] == 39.68  # 14.88 commission + 24.80 stamp duty, rounded separately.
    assert sold["cash"] == round(bought["cash"] + gross - sale["fee"], 2)
    assert sold["metrics"]["equity"] == sold["cash"]


def test_same_revision_is_not_replayed_and_concurrent_steps_are_atomic(service):
    session = service.create("reference", 20)
    def submit():
        try:
            return action(service, session, 'buy')
        except TrainingError as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 409 in results
    saved = service.get(session["id"])
    assert saved["step"] == 1 and len(saved["actions"]) == 1


def test_only_one_active_and_resume_survives_service_restart(service):
    session = action(service, service.create("reference", 20), 'buy')
    with pytest.raises(TrainingError, match="继续或结束"):
        service.create("reference", 20)
    restarted = TrainingService(service.path, service.pool, service.watchlist, Provider())
    assert restarted.get(session["id"]) == session
    assert restarted.overview()["active_id"] == session["id"]
    assert restarted.overview()["history"][0]["stock_name"] == '未揭晓的训练'


def test_completed_reveal_benchmark_and_history(service):
    session = service.create("reference", 20)
    session = action(service, session, 'buy')
    for _ in range(19):
        session = action(service, session, 'hold')
    assert session["status"] == "completed" and session["step"] == 20
    assert session["reveal"]["stock_code"] == "sh600036"
    assert session["reveal"]["end_date"] == bars()[-1]["trade_date"]
    assert session["metrics"]["return_pct"] == session["metrics"]["benchmark_pct"]
    assert session["metrics"]["excess_pct"] == 0
    assert session["shares"] > 0  # Mark to market; no fictitious forced liquidation.
    assert session["metrics"]["trades"] == 1
    summary = service.overview()
    assert summary["summary"]["completed"] == 1 and summary["active_id"] is None
    assert summary["summary"]["win_rate"] == 100
    with pytest.raises(TrainingError):
        action(service, session, 'buy')


def test_abandon_preserves_actions_and_excludes_summary(service):
    session = action(service, service.create("reference", 20), 'buy')
    abandoned = action(service, session, 'finish')
    assert abandoned["status"] == "abandoned" and abandoned["step"] == 1
    assert abandoned["shares"] == session["shares"]
    assert len(abandoned["bars"]) == 61
    assert service.overview()["summary"]["completed"] == 0
    assert service.overview()["summary"]["win_rate"] is None
    assert len(service.overview()["history"]) == 1
    assert service.create("reference", 20)["status"] == "active"


@pytest.mark.parametrize('direction,trade_action', [(1, 'buy'), (-1, 'sell')])
def test_single_price_limit_like_days_are_conservatively_unfilled(service, direction, trade_action):
    rows = bars()
    target = 60 if trade_action == 'buy' else 61
    price = rows[target - 1]['close'] * (1 + .1 * direction)
    rows[target].update(open=price, close=price, high=price, low=price)
    service.provider = Provider(rows)
    session = service.create("reference", 20)
    if trade_action == 'sell':
        session = action(service, session, 'buy')
    before_cash, before_shares = session['cash'], session['shares']
    session = action(service, session, trade_action)
    assert session['actions'][-1]['status'] == 'rejected'
    assert session['cash'] == before_cash and session['shares'] == before_shares
    assert session['actions'][-1]['fee'] == 0
    assert session['step'] == (1 if trade_action == 'buy' else 2)


def test_zero_volume_and_insufficient_cash(service):
    rows = bars()
    rows[60]['volume'] = 0
    service.provider = Provider(rows)
    session = action(service, service.create('reference', 20), 'buy')
    assert session['shares'] == 0 and session['metrics']['fees'] == 0
    assert session['metrics']['benchmark_pct'] == 0
    assert affordable(1000, 10) == 0
    assert affordable(1005, 10) == 100
    assert affordable(4000, 10, .25) == 0
    assert affordable(100_000, 2000) == 0


def test_empty_watchlist_and_mainboard_scope(service):
    service.pool.stocks += [stock('sz300750'), stock('sh688001'), stock('sh510300', asset_type='etf'), stock('sh600001', name='*ST样本')]
    assert len(service.stocks('reference')) == 1
    with pytest.raises(TrainingError, match='暂无可用'):
        service.create('watchlist', 20)
    assert service.provider.calls == 0


def test_offline_cache_and_no_synthetic_fallback(service):
    first = service.create('reference', 20)
    action(service, first, 'finish')
    def failed(_):
        raise OSError('offline')
    service.provider.fetch = failed
    cached = service.create('reference', 20)
    assert cached['cache_used'] and len(cached['bars']) == 60
    action(service, cached, 'finish')
    with service.connect() as db:
        db.execute('DELETE FROM kline_history')
    with pytest.raises(TrainingError, match='真实历史行情') as exc:
        service.create('reference', 20)
    assert exc.value.status == 503


def test_bad_data_never_creates_session(service):
    service.provider = Provider(bars(30))
    with pytest.raises(TrainingError):
        service.create('reference', 20)
    assert service.overview()['history'] == []
    rows = bars()
    rows[10]['high'] = rows[10]['low'] - 1
    with pytest.raises(ValueError):
        valid_bars(rows)
    rows = bars()
    rows[10]['open'] = math.nan
    with pytest.raises(ValueError):
        valid_bars(rows)
    with pytest.raises(ValueError):
        valid_bars(bars()[::-1])
    today = dict(bars()[0], trade_date=date.today().isoformat())
    assert valid_bars([today]) == []


def test_drawdown_uses_equity_peak_not_stock_price(service):
    rows = bars()
    rows[61].update(open=10, close=10, high=10.5, low=9.5)
    service.provider = Provider(rows)
    first = action(service, service.create('reference', 20), 'buy', .5)
    second = action(service, first, 'hold')
    peak = max(100000, first['metrics']['equity'])
    expected = round((peak - second['metrics']['equity']) / peak * 100, 2)
    assert second['metrics']['max_drawdown_pct'] == expected


def test_http_validation_errors_and_private_session_payload(tmp_path, monkeypatch):
    monkeypatch.setenv('STOCK_RESEARCH_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        app.state.training.provider = Provider()
        assert client.get('/api/training').status_code == 200
        assert client.post('/api/training/sessions', json={'steps':21}).status_code == 422
        response = client.post('/api/training/sessions', json={'steps':20})
        assert response.status_code == 200
        session = response.json()
        url = f"/api/training/sessions/{session['id']}"
        assert client.get(url).json()['reveal'] is None
        assert client.post(url + '/actions', json={'revision':0, 'action':'buy', 'fraction':2}).status_code == 422
        result = client.post(url + '/actions', json={'revision':0, 'action':'buy'})
        assert result.status_code == 200 and result.json()['step'] == 1
        assert client.post(url + '/actions', json={'revision':0, 'action':'buy'}).status_code == 409
        assert client.get('/api/training/sessions/not-a-session').status_code == 404
