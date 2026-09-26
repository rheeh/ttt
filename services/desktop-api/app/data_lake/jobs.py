from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.market.trading_calendar import latest_session, market_now
from .reader import LakeReader, installed_version, symbol_for, SUPPORTED_VERSION


class LakeSettings(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["600519.SH", "000001.SZ", "000858.SZ", "300750.SZ", "601318.SH"], min_length=1, max_length=200)
    auto_update: bool = True

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values):
        return list(dict.fromkeys(symbol_for(value) for value in values))


class CollectRequest(BaseModel):
    mode: str = Field(default="update", pattern="^(update|backfill|research|events)$")
    history_days: int = Field(default=1100, ge=30, le=3650)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS lake_jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS lake_one_active ON lake_jobs((1)) WHERE status IN ('queued','running')")
            db.execute("CREATE TABLE IF NOT EXISTS lake_config (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def settings(self):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM lake_config WHERE id=1").fetchone()
        return LakeSettings.model_validate_json(row[0]) if row else LakeSettings()

    def configure(self, settings):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO lake_config VALUES (1,?)", (settings.model_dump_json(),))

    def recent(self, limit=20):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM lake_jobs ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def read(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM lake_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return json.loads(row[0])

    def save(self, job):
        job["updated_at"] = utc_now()
        with self.connect() as db:
            db.execute("UPDATE lake_jobs SET status=?, payload=? WHERE id=?", (job["status"], json.dumps(job, ensure_ascii=False, default=str), job["id"]))

    def create(self, request, *, automatic=False):
        job = {"id": uuid4().hex, "status": "queued", "created_at": utc_now(), "updated_at": utc_now(),
               "mode": request.mode, "history_days": request.history_days, "symbols": self.settings().symbols,
               "automatic": automatic, "steps": [], "current_step": "准备采集", "pid": None, "error": None}
        try:
            with self.connect() as db:
                db.execute("INSERT INTO lake_jobs VALUES (?,?,?)", (job["id"], job["status"], json.dumps(job)))
        except sqlite3.IntegrityError as exc:
            raise ValueError("已有采集任务运行中") from exc
        return job

    def recover(self):
        for job in self.recent():
            if job["status"] not in {"queued", "running"}:
                continue
            if (datetime.now(timezone.utc) - datetime.fromisoformat(job["updated_at"])).total_seconds() < 60:
                continue
            try:
                if job.get("pid"):
                    os.kill(job["pid"], 0)
                    continue
            except ProcessLookupError:
                pass
            except PermissionError:
                continue
            job.update(status="interrupted", error="采集进程已退出；已发布的数据保留，可重新更新补齐")
            self.save(job)


class LakeJobs:
    def __init__(self, root: Path, state_path: Path):
        self.root = root
        self.reader = LakeReader(root)
        self.store = JobStore(state_path)
        self.process = None
        self.stop_event = Event()
        self.store.recover()

    def status(self):
        self.store.recover()
        error, datasets = None, []
        if installed_version() == SUPPORTED_VERSION and (self.root / "meta").exists():
            try:
                datasets = self.reader.catalog()
            except Exception as exc:
                error = str(exc)
        return {"installed_version": installed_version(), "required_version": SUPPORTED_VERSION,
                "root": str(self.root), "settings": self.store.settings().model_dump(),
                "datasets": datasets, "jobs": self.store.recent(), "error": error,
                "schedule": "应用运行时16:20后更新日线；启用过研究采集后，公告每天更新、财报与行业每周更新。每类每天最多3次，失败间隔至少15分钟"}

    def start(self, request: CollectRequest, *, automatic=False):
        if installed_version() != SUPPORTED_VERSION:
            raise ValueError(f"请先安装 requirements-data.txt（CNEquity {SUPPORTED_VERSION}）")
        self.store.recover()
        job = self.store.create(request, automatic=automatic)
        self.root.mkdir(parents=True, exist_ok=True)
        logs = self.root / "logs"
        logs.mkdir(exist_ok=True)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
        try:
            with (logs / f"{job['id']}.log").open("w") as output:
                process = subprocess.Popen([sys.executable, "-m", "app.data_lake.worker", str(self.root), str(self.store.path), job["id"]],
                                           stdout=output, stderr=subprocess.STDOUT, env=env)
            self.process = process
        except Exception as exc:
            job.update(status="failed", error=str(exc))
            self.store.save(job)
            raise
        Thread(target=self._watch, args=(job["id"], process), daemon=True).start()
        return job

    def _watch(self, job_id, process):
        error = None
        try:
            code = process.wait(timeout=1800)
            if code:
                error = f"采集进程退出（{code}），已保存的数据保留"
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            error = "采集超过30分钟，已停止；可缩小范围后继续补采"
        job = self.store.read(job_id)
        if job["status"] in {"queued", "running"}:
            job.update(status="failed" if error else "interrupted", error=error or "进程未写入完成状态")
            self.store.save(job)

    def begin_schedule(self):
        Thread(target=self._schedule, daemon=True).start()

    def _schedule(self):
        while not self.stop_event.wait(30):
            try:
                request = self.next_request()
                if request:
                    self.start(request, automatic=True)
            except Exception:
                continue

    def next_request(self, now=None):
        settings, recent, now = self.store.settings(), self.store.recent(200), now or market_now()
        if not settings.auto_update or not recent or now.hour * 60 + now.minute < 980:
            return None
        if any(job["status"] in {"queued", "running"} for job in recent):
            return None
        expected = latest_session(now)
        if expected is None:
            return None
        def eligible(mode):
            today = [job for job in recent if job["mode"] == mode and datetime.fromisoformat(job["created_at"]).astimezone(now.tzinfo).date() == now.date()]
            return len(today) < 3 and (not today or now - datetime.fromisoformat(today[0]["updated_at"]) >= timedelta(minutes=15))
        core_ready = any(job["mode"] in {"update", "backfill"} and job["status"] == "success"
                         and job.get("trade_date") == expected.isoformat() and job["symbols"] == settings.symbols for job in recent)
        if not core_ready and eligible("update"):
            return CollectRequest()
        research = [job for job in recent if job["mode"] == "research"]
        if not research:  # Research sources are opt-in via the first collection.
            return None
        successful = next((job for job in research if job["status"] == "success"), None)
        if (successful is None or now - datetime.fromisoformat(successful["created_at"]) >= timedelta(days=7)) and eligible("research"):
            return CollectRequest(mode="research")
        events_today = any(job["mode"] in {"events", "research"} and job["status"] == "success"
                           and datetime.fromisoformat(job["created_at"]).astimezone(now.tzinfo).date() == now.date() for job in recent)
        if not events_today and eligible("events"):
            return CollectRequest(mode="events")
        return None

    def stop(self):
        self.stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
