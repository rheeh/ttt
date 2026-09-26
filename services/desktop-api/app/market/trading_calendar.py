"""Offline SH/SZ session calendar, bounded by published exchange notices.

Unknown years stay unknown. Government weekend make-up workdays are never
exchange sessions. Extend HOLIDAYS only against a published exchange notice.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
DAILY_READY_AT = time(15, 10)
CALENDAR_VERSION = "sse-holidays-2025-2026-v1"
SOURCES = {
    2025: "https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml",
    2026: "https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml",
}
HOLIDAYS = {
    2025: (("01-01", "01-01"), ("01-28", "02-04"), ("04-04", "04-06"),
           ("05-01", "05-05"), ("05-31", "06-02"), ("10-01", "10-08")),
    2026: (("01-01", "01-03"), ("02-15", "02-23"), ("04-04", "04-06"),
           ("05-01", "05-05"), ("06-19", "06-21"), ("09-25", "09-27"), ("10-01", "10-07")),
}


def is_session(day: date) -> bool | None:
    if day.year not in HOLIDAYS:
        return None
    return day.weekday() < 5 and not any(
        date.fromisoformat(f"{day.year}-{start}") <= day <= date.fromisoformat(f"{day.year}-{end}")
        for start, end in HOLIDAYS[day.year]
    )


def market_now() -> datetime:
    return datetime.now(SHANGHAI)


def latest_session(now: datetime | None = None, *, completed: bool = True) -> date | None:
    local = (now or market_now()).astimezone(SHANGHAI)
    day = local.date()
    if is_session(day) is None:
        return None
    if local.time() < (DAILY_READY_AT if completed else time(9, 30)):
        day -= timedelta(days=1)
    while is_session(day) is False:
        day -= timedelta(days=1)
    return day if is_session(day) is True else None


def calendar_status(now: datetime | None = None) -> dict:
    local = (now or market_now()).astimezone(SHANGHAI)
    expected = latest_session(local)
    return {"version": CALENDAR_VERSION, "source": SOURCES.get(local.year),
            "coverage_end": "2026-12-31", "known": is_session(local.date()) is not None,
            "expected_trade_date": expected.isoformat() if expected else None}
