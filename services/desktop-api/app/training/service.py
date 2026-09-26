from __future__ import annotations

import json
import math
import random
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4
from app.market.daily_contract import parse_tencent_daily
from app.market.trading_calendar import market_now

INITIAL_CASH = 100_000.0
WARMUP = 60
RULES_VERSION = "a-mainboard-next-open-v1"


class TrainingError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.status = status
        super().__init__(message)


def mainboard(code: str) -> bool:
    return len(code) == 8 and code[2:].isdigit() and code.startswith(("sh600", "sh601", "sh603", "sh605", "sz000", "sz001", "sz002", "sz003"))


def valid_bars(rows: list[dict]) -> list[dict]:
    """Reject corrupt sequences, OHLC and unfinished daily candles as a whole."""
    result = []
    previous = ""
    for row in rows:
        day = str(row["trade_date"])
        parsed = date.fromisoformat(day)
        if day <= previous:
            raise ValueError("历史行情日期重复或未按时间递增")
        previous = day
        if parsed >= market_now().date():
            continue
        numbers = {key: float(row[key]) for key in ("open", "close", "high", "low", "volume")}
        if not all(math.isfinite(value) for value in numbers.values()):
            raise ValueError("历史行情包含无效数值")
        if numbers["low"] <= 0 or numbers["volume"] < 0 or not (numbers["low"] <= min(numbers["open"], numbers["close"]) <= max(numbers["open"], numbers["close"]) <= numbers["high"]):
            raise ValueError("历史行情 OHLC 不完整")
        result.append({"trade_date": day, **numbers})
    return result


class TrainingHistoryProvider:
    """Use the project's Tencent history source, requiring explicit qfq OHLC."""
    def fetch(self, code: str) -> list[dict]:
        query = urlencode({"param": f"{code},day,,,640,qfq"})
        request = Request("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + query, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
        with urlopen(request, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return valid_bars([bar.model_dump(mode="json") for bar in parse_tencent_daily(payload, code)])


def cents(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def commission(gross: float) -> float:
    return cents(max(5, gross * .0003)) if gross else 0.0


def affordable(cash: float, price: float, fraction: float = 1) -> int:
    budget = cash * fraction
    shares = int(budget / price / 100) * 100
    while shares > 0 and shares * price + commission(shares * price) > budget + .000001:
        shares -= 100
    return shares


def equity(state: dict) -> float:
    return round(state["cash"] + state["shares"] * state["bars"][state["cursor"]]["close"], 2)


def stats(state: dict) -> dict:
    value = equity(state)
    curve = state["equity_curve"]
    peak, drawdown = INITIAL_CASH, 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        drawdown = max(drawdown, (peak - point["equity"]) / peak * 100)
    benchmark = state["benchmark_cash"] + state["benchmark_shares"] * state["bars"][state["cursor"]]["close"]
    ret = (value / INITIAL_CASH - 1) * 100
    base_ret = (benchmark / INITIAL_CASH - 1) * 100
    return {"equity": value, "return_pct": round(ret, 2), "benchmark_pct": round(base_ret, 2), "excess_pct": round(ret - base_ret, 2), "max_drawdown_pct": round(drawdown, 2), "fees": round(state["fees"], 2), "position_pct": round(state["shares"] * state["bars"][state["cursor"]]["close"] / value * 100, 2) if value else 0, "trades": sum(item["status"] == "filled" for item in state["actions"])}


def snapshot(state: dict) -> dict:
    finished = state["status"] != "active"
    visible = state["bars"][:state["cursor"] + 1]
    bars = []
    week_index, previous_week = -1, None
    for index, bar in enumerate(visible):
        week = date.fromisoformat(bar["trade_date"]).isocalendar()[:2]
        if week != previous_week:
            week_index += 1
            previous_week = week
        item = {key: value for key, value in bar.items() if key != "trade_date"}
        item.update(index=index, week=week_index, label=bar["trade_date"] if finished else f"第 {index + 1} 日")
        bars.append(item)
    metrics = stats(state)
    report = None
    if finished:
        report = {"stock_code": state["stock"]["code"], "stock_name": state["stock"]["name"], "start_date": state["bars"][WARMUP]["trade_date"], "end_date": visible[-1]["trade_date"], "fetched_at": state["fetched_at"], "notes": [
            f"本局收益 {metrics['return_pct']:+.2f}%，相对同期买入持有 {metrics['excess_pct']:+.2f} 个百分点。",
            f"收盘权益最大回撤 {metrics['max_drawdown_pct']:.2f}%；日内回撤未计入。",
            f"共成交 {metrics['trades']} 笔，模拟费用 {metrics['fees']:.2f} 元。" if metrics['trades'] else "本局没有成交。可回看观望记录，检查入场条件是否过于严格。",
            "期末持仓按最后收盘价估值，未强制平仓，未扣假设卖出费用。" if state["shares"] else "期末为空仓。结合买卖标记，复查退出时机与最初的交易理由。",
        ]}
    return {"id": state["id"], "status": state["status"], "revision": state["revision"], "created_at": state["created_at"], "pool": state["pool"], "total_steps": state["total_steps"], "step": state["cursor"] - WARMUP + 1, "warmup": WARMUP, "initial_cash": INITIAL_CASH, "cash": round(state["cash"], 2), "shares": state["shares"], "sellable_shares": state["shares"], "bars": bars, "actions": state["actions"], "equity_curve": state["equity_curve"], "metrics": metrics, "reveal": report, "rules_version": state.get("rules_version", RULES_VERSION), "data_source": "腾讯前复权日线 · 本地历史缓存" if state["cache_used"] else "腾讯前复权日线", "cache_used": state["cache_used"]}


class TrainingService:
    def __init__(self, path: Path, pool, watchlist, provider=None):
        self.path = path
        self.pool = pool
        self.watchlist = watchlist
        self.provider = provider or TrainingHistoryProvider()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS kline_sessions (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS kline_one_active ON kline_sessions(status) WHERE status='active';
                CREATE TABLE IF NOT EXISTS kline_history (code TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, bars TEXT NOT NULL);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=20)

    def stocks(self, kind: str) -> list[dict]:
        items = self.pool.stocks if kind == "reference" else self.watchlist()
        return [{"code": item.code, "name": item.name} for item in items if item.asset_type == "stock" and mainboard(item.code) and not any(token in item.name.upper() for token in ("ST", "退"))]

    def overview(self) -> dict:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM kline_sessions ORDER BY created_at DESC").fetchall()
            cache_count = db.execute("SELECT COUNT(*) FROM kline_history").fetchone()[0]
        states = [json.loads(row[0]) for row in rows]
        completed = [state for state in states if state["status"] == "completed"]
        returns = [stats(state)["return_pct"] for state in completed]
        return {"pools": [{"id": kind, "count": len(self.stocks(kind))} for kind in ("reference", "watchlist")], "cache_count": cache_count, "active_id": next((state["id"] for state in states if state["status"] == "active"), None), "summary": {"completed": len(completed), "win_rate": round(sum(value > 0 for value in returns) / len(returns) * 100, 1) if returns else None, "average_return": round(sum(returns) / len(returns), 2) if returns else None, "best_return": max(returns) if returns else None}, "history": [{"id": state["id"], "status": state["status"], "created_at": state["created_at"], "step": state["cursor"] - WARMUP + 1, "total_steps": state["total_steps"], "stock_name": state["stock"]["name"] if state["status"] != "active" else "未揭晓的训练", "metrics": stats(state)} for state in states[:30]]}

    def get(self, session_id: str) -> dict:
        with self.connect() as db:
            return snapshot(self.read(db, session_id))

    @staticmethod
    def read(db, session_id: str) -> dict:
        row = db.execute("SELECT payload FROM kline_sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            raise TrainingError("训练记录不存在", 404)
        return json.loads(row[0])

    def create(self, kind: str, steps: int) -> dict:
        if kind not in {"reference", "watchlist"} or steps not in {20, 40, 60}:
            raise TrainingError("训练参数无效")
        if self.overview()["active_id"]:
            raise TrainingError("请先继续或结束当前训练", 409)
        stocks = self.stocks(kind)
        if not stocks:
            raise TrainingError("该题库暂无可用沪深主板股票，请先添加主板自选股")
        random.SystemRandom().shuffle(stocks)
        chosen = None
        # Prefer successful local history; train offline after the first successful draw.
        with self.connect() as db:
            cache = {row[0]: row[1:] for row in db.execute("SELECT code, fetched_at, bars FROM kline_history")}
        for stock in stocks[:4]:
            cached = cache.get(stock["code"])
            if cached:
                bars = valid_bars(json.loads(cached[1]))
                fetched_at, cache_used = cached[0], True
            else:
                try:
                    bars = valid_bars(self.provider.fetch(stock["code"]))
                except (OSError, ValueError, KeyError, TypeError):
                    continue
                fetched_at, cache_used = datetime.now(timezone.utc).isoformat(), False
            if len(bars) >= WARMUP + steps:
                chosen = (stock, bars, fetched_at, cache_used)
                break
        if chosen is None:
            for stock in stocks:
                cached = cache.get(stock["code"])
                if cached:
                    bars = valid_bars(json.loads(cached[1]))
                    if len(bars) >= WARMUP + steps:
                        chosen = (stock, bars, cached[0], True)
                        break
        if chosen is None:
            raise TrainingError("暂时无法取得足够的真实历史行情，且没有可用缓存。请稍后重试或切换题库。", 503)
        stock, bars, fetched_at, cache_used = chosen
        start = random.SystemRandom().randint(0, len(bars) - WARMUP - steps)
        selected = bars[start:start + WARMUP + steps]
        state = {"id": str(uuid4()), "rules_version": RULES_VERSION, "status": "active", "revision": 0, "created_at": datetime.now(timezone.utc).isoformat(), "stock": stock, "pool": kind, "bars": selected, "cursor": WARMUP - 1, "total_steps": steps, "cash": INITIAL_CASH, "shares": 0, "fees": 0, "benchmark_cash": INITIAL_CASH, "benchmark_shares": 0, "actions": [], "equity_curve": [{"step": 0, "equity": INITIAL_CASH, "benchmark": INITIAL_CASH}], "fetched_at": fetched_at, "cache_used": cache_used}
        try:
            with self.connect() as db:
                db.execute("INSERT OR REPLACE INTO kline_history VALUES (?, ?, ?)", (stock["code"], fetched_at, json.dumps(bars)))
                db.execute("INSERT INTO kline_sessions VALUES (?, ?, ?, ?)", (state["id"], state["status"], state["created_at"], json.dumps(state)))
        except sqlite3.IntegrityError as exc:
            raise TrainingError("另一个窗口已开始训练，请刷新后继续", 409) from exc
        return snapshot(state)

    def act(self, session_id: str, revision: int, action: str, fraction: float = 1, note: str = "") -> dict:
        if action not in {"buy", "sell", "hold", "finish"} or fraction not in {.25, .5, 1}:
            raise TrainingError("操作参数无效")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self.read(db, session_id)
            if state["revision"] != revision or state["status"] != "active":
                raise TrainingError("训练已更新或结束，请刷新当前记录后再操作", 409)
            if action == "finish":
                state["status"] = "abandoned"
            else:
                self.advance(state, action, fraction, note[:160])
            state["revision"] += 1
            db.execute("UPDATE kline_sessions SET status=?, payload=? WHERE id=?", (state["status"], json.dumps(state), session_id))
        return snapshot(state)

    @staticmethod
    def advance(state: dict, action: str, fraction: float, note: str):
        previous = state["bars"][state["cursor"]]
        state["cursor"] += 1
        bar = state["bars"][state["cursor"]]
        price = bar["open"]
        step = state["cursor"] - WARMUP + 1
        flat = abs(bar["high"] - bar["low"]) < .000001
        buy_blocked = bar["volume"] == 0 or (flat and price > previous["close"])
        sell_blocked = bar["volume"] == 0 or (flat and price < previous["close"])
        # Benchmark submits once at the first executable open, using the same fees/lots.
        if not state["benchmark_shares"] and not buy_blocked:
            quantity = affordable(INITIAL_CASH, price)
            state["benchmark_shares"] = quantity
            state["benchmark_cash"] = INITIAL_CASH - quantity * price - commission(quantity * price)
        quantity, fee, status, reason = 0, 0.0, "skipped", "观望，推进一个交易日"
        if action == "buy":
            quantity = affordable(state["cash"], price, fraction)
            if buy_blocked:
                quantity, reason = 0, "无成交量或单一价上涨，保守判定买入未成交"
            elif not quantity:
                reason = "所选资金不足买入 100 股并支付费用"
            else:
                gross = round(quantity * price, 2)
                fee = commission(gross)
                state["cash"] = round(state["cash"] - gross - fee, 2)
                state["shares"] += quantity
                status, reason = "filled", "下一交易日开盘买入"
        elif action == "sell":
            quantity = int(state["shares"] * fraction / 100) * 100
            if sell_blocked:
                quantity, reason = 0, "无成交量或单一价下跌，保守判定卖出未成交"
            elif not quantity:
                reason = "所选持仓不足 100 股，未成交"
            else:
                gross = round(quantity * price, 2)
                fee = cents(commission(gross) + cents(gross * .0005))
                state["cash"] = round(state["cash"] + gross - fee, 2)
                state["shares"] -= quantity
                status, reason = "filled", "下一交易日开盘卖出"
        if action != "hold" and status != "filled":
            status = "rejected"
        state["fees"] += fee
        state["actions"].append({"step": step, "index": state["cursor"], "action": action, "fraction": fraction, "shares": quantity, "price": price if quantity else None, "fee": fee, "status": status, "reason": reason, "note": note})
        state["equity_curve"].append({"step": step, "equity": equity(state), "benchmark": round(state["benchmark_cash"] + state["benchmark_shares"] * bar["close"], 2)})
        if step == state["total_steps"]:
            state["status"] = "completed"
