"""Bounded CNEquity jobs in a child process, independent of HTTP requests."""
from __future__ import annotations

import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

from app.market.trading_calendar import latest_session, market_now
from .jobs import JobStore, utc_now


def collect(root: Path, store: JobStore, job_id: str):
    import cnequity.steps  # noqa: F401: register upstream steps
    from cnequity.config import Config, WaveConfig
    from cnequity.orchestrator.engine import JobEngine
    from cnequity.storage.layout import init_data_layout
    from cnequity.query import load

    job = store.read(job_id)
    job.update(status="running", pid=os.getpid())
    store.save(job)
    end = latest_session()
    if end is None:
        raise ValueError("交易日历未知，不能采集日线")
    job["trade_date"] = end.isoformat()
    store.save(job)
    start = end - timedelta(days=job["history_days"])
    cfg = Config(data_root=root, workers=1, max_retries=1, retry_backoff_seconds=2,
                 tdx_connect_timeout_sec=5, eastmoney_timeout_sec=12, tdx_allow_mock=False,
                 tdx_daily_workers=1, adj_factor_workers=2, ingest_universe="all_a")
    init_data_layout(cfg)
    engine = JobEngine(cfg)

    def run(label, steps, begin=start, finish=end, symbols=None):
        job["current_step"] = label
        store.save(job)
        cfg._backfill_start, cfg._backfill_end = begin, finish
        cfg._backfill_symbols = symbols
        try:
            result = engine.run_job("backfill", trade_date=finish, backfill=True,
                                    waves=[WaveConfig(name="collect", parallel=False, steps=steps)])
            status = result.get("status", "failed")
            errors = [str(value.get("error") or value.get("note")) for value in result.get("results", [])
                      if value.get("status") in {"failed", "warning"} and (value.get("error") or value.get("note"))]
            job["steps"].append({"name": label, "status": status, "run_id": result.get("run_id"),
                                 "rows_written": result.get("rows_written", 0), "error": "; ".join(errors)[:1500] or None})
        except Exception as exc:
            job["steps"].append({"name": label, "status": "failed", "error": str(exc)[:1500]})
        store.save(job)

    if job["mode"] in {"research", "events"}:
        if job["mode"] == "research":
            run("财务历史", ["financial_statement_items", "compact"], begin=end - timedelta(days=740), symbols=job["symbols"])
        # CNINFO is a market-wide dated feed. Keep its first window to 7 days.
        run("最近7天公告索引（全市场）", ["announcement_index", "compact"], begin=market_now().date() - timedelta(days=6), finish=market_now().date())
        if job["mode"] == "research":
            run("申万行业成员历史（全市场）", ["industry_members", "compact"], begin=end - timedelta(days=365))
    else:
        if not (root / "curated" / "instruments").exists():
            run("证券名录", ["instruments", "compact"], begin=end)
        run("交易日历", ["trading_calendar", "compact"])
        for symbol in job["symbols"]:
            begin = start
            if job["mode"] == "update":
                try:
                    existing = load("daily_bars", symbols=[symbol], data_root=root)
                    if existing.height:
                        begin = max(start, existing["trade_date"].max() - timedelta(days=7))
                except (ValueError, OSError):
                    pass
            run(f"日线 {symbol}", ["daily_bars", "compact"], begin=begin, symbols=[symbol])
        begin = start
        if job["mode"] == "update":
            try:
                indices = load("index_bars", data_root=root)
                if indices.height:
                    begin = max(start, indices["trade_date"].max() - timedelta(days=7))
            except (ValueError, OSError):
                pass
        run("基准指数", ["index_bars", "compact"], begin=begin)
        run("复权因子", ["derive_adj_factors"])

    # This prunes database-version copies, never dates from the current lake.
    from cnequity.storage.revisions import prune_revision_generations
    prune_revision_generations(cfg.meta_root, keep=5)
    failed = [item for item in job["steps"] if item["status"] not in {"success", "skipped"}]
    job.update(status="partial" if failed else "success", current_step="采集结束", finished_at=utc_now(),
               error=f"{len(failed)}个步骤未完整成功，可重试；已发布历史仍可使用" if failed else None)
    store.save(job)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    root, state_path, job_id = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    store = JobStore(state_path)
    try:
        collect(root, store, job_id)
    except Exception as exc:
        logging.exception("CNEquity collection failed")
        job = store.read(job_id)
        job.update(status="failed", error=str(exc), finished_at=utc_now())
        store.save(job)
        raise SystemExit(1)
