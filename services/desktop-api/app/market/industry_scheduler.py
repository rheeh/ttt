from __future__ import annotations

import json
import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path
from threading import Event, Thread, Lock
from typing import Callable
from zoneinfo import ZoneInfo
from app.market.trading_calendar import calendar_status, is_session


SHANGHAI = ZoneInfo("Asia/Shanghai")


class IndustryRadarScheduler:
    """Run the full industry refresh once after each weekday close.

    The scheduler is intentionally small and process-local. SQLite remains the
    source of truth, and a failed refresh never removes the previous snapshot.
    """

    def __init__(self, refresh: Callable[[], object], *, close_time: time = time(16, 10), poll_seconds: int = 30,
                 state_path: Path | None = None, max_attempts_per_day: int = 3,
                 clock: Callable[[], datetime] | None = None):
        self.refresh = refresh
        self.close_time = close_time
        self.poll_seconds = poll_seconds
        self.state_path = state_path
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.max_attempts_per_day = max_attempts_per_day
        self.attempts_today = 0
        self.next_retry_at: datetime | None = None
        self._run_lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self.last_attempt_at: datetime | None = None
        self.last_success_at: datetime | None = None
        self.last_error: str | None = None
        self.last_run_date: str | None = None
        if state_path:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(state_path, timeout=30) as db:
                db.execute("CREATE TABLE IF NOT EXISTS background_task_state (name TEXT PRIMARY KEY, payload_json TEXT NOT NULL)")
                row = db.execute("SELECT payload_json FROM background_task_state WHERE name='industry-radar'").fetchone()
            if row:
                saved = json.loads(row[0])
                for key in ("last_attempt_at", "last_success_at", "next_retry_at"):
                    setattr(self, key, datetime.fromisoformat(saved[key]) if saved.get(key) else None)
                self.last_run_date = saved.get("last_run_date")
                self.last_error = saved.get("last_error")
                self.attempts_today = saved.get("attempts_today", 0)

    def _persist(self) -> None:
        if self.state_path:
            with sqlite3.connect(self.state_path, timeout=30) as db:
                db.execute("INSERT OR REPLACE INTO background_task_state VALUES ('industry-radar', ?)",
                           (json.dumps(self.status(), default=lambda value: value.isoformat()),))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="industry-radar-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def run_now(self) -> object:
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("板块历史刷新正在运行，请等待当前任务完成")
        try:
            now = self.clock().astimezone(SHANGHAI)
            if not self.last_attempt_at or self.last_attempt_at.date() != now.date():
                self.attempts_today = 0
            self.attempts_today += 1
            self.last_attempt_at = now
            # Save the attempt before I/O so a process restart does not erase it.
            self.next_retry_at = now + timedelta(minutes=5 * 2 ** min(self.attempts_today - 1, 4))
            self.last_error = "刷新未完成；若进程中断，下次启动将保留重试记录"
            self._persist()
            try:
                result = self.refresh()
            except Exception as exc:
                self.last_error = str(exc)
                self._persist()
                raise
            self.last_success_at = self.clock().astimezone(SHANGHAI)
            self.last_run_date = now.date().isoformat()
            self.last_error = None
            self.next_retry_at = None
            self._persist()
            return result
        finally:
            self._run_lock.release()

    def status(self) -> dict[str, object | None]:
        return {
            "enabled": True,
            "close_time": self.close_time.strftime("%H:%M"),
            "last_attempt_at": self.last_attempt_at,
            "last_success_at": self.last_success_at,
            "last_run_date": self.last_run_date,
            "last_error": self.last_error,
            "running": self._run_lock.locked(),
            "attempts_today": self.attempts_today if self.last_attempt_at and self.last_attempt_at.date() == self.clock().astimezone(SHANGHAI).date() else 0,
            "max_attempts_per_day": self.max_attempts_per_day,
            "next_retry_at": self.next_retry_at,
            "calendar": calendar_status(self.clock()),
        }

    def due(self, now: datetime | None = None) -> bool:
        now = (now or self.clock()).astimezone(SHANGHAI)
        if self._run_lock.locked() or is_session(now.date()) is not True or now.time() < self.close_time:
            return False
        if self.last_run_date == now.date().isoformat():
            return False
        same_day = self.last_attempt_at and self.last_attempt_at.date() == now.date()
        return not same_day or (self.attempts_today < self.max_attempts_per_day and
                                (self.next_retry_at is None or now >= self.next_retry_at))

    def _run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            if not self.due():
                continue
            try:
                self.run_now()
            except Exception:
                # The cached last successful snapshot remains available.
                continue
