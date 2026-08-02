from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field


class FundFlowFacts(BaseModel):
    trade_date: str | None = None
    main_inflow: float | None = None
    main_flow_ratio: float | None = None
    main_inflow_5d: float | None = None
    main_inflow_10d: float | None = None
    ratio_kind: str | None = None
    small_inflow: float | None = None
    medium_inflow: float | None = None
    large_inflow: float | None = None
    super_inflow: float | None = None
    source: str = "eastmoney-fflow"
    endpoint: str | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "error"
    error: str | None = None
    data_age_seconds: float | None = None
    cache_used: bool = False
    cache_expired: bool = False


class FinanceFacts(BaseModel):
    report_date: str | None = None
    notice_date: str | None = None
    revenue: float | None = None
    revenue_yoy: float | None = None
    profit: float | None = None
    profit_yoy: float | None = None
    roe: float | None = None
    source: str = "eastmoney-finance"
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "error"
    error: str | None = None
    data_age_seconds: float | None = None
    cache_used: bool = False
    cache_expired: bool = False


class IndustryFacts(BaseModel):
    name: str | None = None
    rank: int | None = None
    total: int | None = None
    change_pct: float | None = None
    main_inflow: float | None = None
    constituent_count: int | None = None
    up_count: int | None = None
    down_count: int | None = None
    average_amount: float | None = None
    leader_name: str | None = None
    leader_change_pct: float | None = None
    source: str = "eastmoney-industry"
    endpoint: str | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "error"
    error: str | None = None
    data_age_seconds: float | None = None
    cache_used: bool = False
    cache_expired: bool = False


class NewsItem(BaseModel):
    title: str
    snippet: str = ""
    source_name: str = ""
    published_at: str = ""
    url: str = ""
    sentiment: str = "neutral"


class NewsFacts(BaseModel):
    items: list[NewsItem] = Field(default_factory=list)
    source: str = "eastmoney-news"
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "error"
    error: str | None = None
    data_age_seconds: float | None = None
    cache_used: bool = False
    cache_expired: bool = False


def _json_request(url: str, timeout: float) -> dict:
    return json.loads(_request_text(url, timeout, referer="https://quote.eastmoney.com/") or "{}")


def _json_request_any(urls: list[str], timeout: float) -> tuple[dict, str]:
    """Try equivalent Eastmoney endpoints and preserve the useful root cause.

    Eastmoney rotates the quote API across several hosts.  A single host being
    blocked should not make the adapter fail before trying the other official
    endpoint.  The helper deliberately does not swallow the final exception;
    callers expose it in the report/source-health response.
    """
    last_error: Exception | None = None
    for url in urls:
        try:
            return _json_request(url, timeout), url
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
    if last_error is not None:
        hosts = ", ".join(urlsplit(url).netloc for url in urls)
        raise OSError(f"all endpoints failed ({hosts}); last error: {last_error}") from last_error
    raise ValueError("no data source endpoint")


def _request_text(url: str, timeout: float, *, referer: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 ZhixingStockResearch/0.5", "Referer": referer})
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "ignore")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(.2)
    assert last_error is not None
    raise last_error


class EastmoneyFundFlowProvider:
    name = "eastmoney-fflow"
    _hosts = ("push2his.eastmoney.com", "push2.eastmoney.com", "17.push2.eastmoney.com")

    def __init__(self, timeout_seconds: float = 8):
        self.timeout_seconds = timeout_seconds

    def fetch(self, code: str) -> FundFlowFacts:
        market = "1" if code.startswith("sh") else "0"
        clean = code[2:]
        params = {
            "lmt": 0,
            "klt": 101,
            "secid": f"{market}.{clean}",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "_": int(time.time() * 1000),
        }
        try:
            urls = [f"https://{host}/api/qt/stock/fflow/daykline/get?{urlencode(params)}" for host in self._hosts]
            payload, endpoint = _json_request_any(urls, self.timeout_seconds)
            rows = list((payload.get("data") or {}).get("klines") or [])
            if not rows:
                raise ValueError("no fund-flow row")
            # AKShare returns chronological rows.  Do not assume the API's
            # order: malformed/proxy caches have returned reverse order too.
            values = max((row.split(",") for row in rows if row), key=lambda row: row[0] if row else "")
            if not values or not values[0]:
                raise ValueError("fund-flow row has no trade date")
            number = lambda index: float(values[index]) if len(values) > index and values[index] not in {"", "-"} else None
            return FundFlowFacts(
                trade_date=values[0], main_inflow=round(number(1) / 1e8, 4) if number(1) is not None else None,
                small_inflow=round(number(2) / 1e8, 4) if number(2) is not None else None,
                medium_inflow=round(number(3) / 1e8, 4) if number(3) is not None else None,
                large_inflow=round(number(4) / 1e8, 4) if number(4) is not None else None,
                super_inflow=round(number(5) / 1e8, 4) if number(5) is not None else None,
                main_flow_ratio=round(number(6) / 100, 6) if number(6) is not None else None,
                endpoint=urlsplit(endpoint).netloc,
                status="ok",
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            return FundFlowFacts(error=str(exc))


class EastmoneyFinanceProvider:
    name = "eastmoney-finance"

    def __init__(self, timeout_seconds: float = 8):
        self.timeout_seconds = timeout_seconds

    def fetch(self, code: str) -> FinanceFacts:
        clean, suffix = code[2:], ".SZ" if code.startswith("sz") else ".SH"
        params = {
            "reportName": "RPT_F10_FINANCE_MAINFINADATA",
            "columns": "SECUCODE,REPORT_DATE,NOTICE_DATE,PARENTNETPROFIT,TOTALOPERATEREVE,TOTALOPERATEREVETZ,PARENTNETPROFITTZ,ROEJQ",
            "filter": f'(SECUCODE in ("{clean}{suffix}"))', "pageNumber": 1, "pageSize": 6,
            "sortTypes": "-1", "sortColumns": "NOTICE_DATE",
        }
        try:
            payload = _json_request("https://datacenter-web.eastmoney.com/api/data/v1/get?" + urlencode(params), self.timeout_seconds)
            rows = payload.get("result", {}).get("data", [])
            if not rows:
                raise ValueError("no finance row")
            row = rows[0]
            return FinanceFacts(
                report_date=str(row.get("REPORT_DATE") or "")[:10], notice_date=str(row.get("NOTICE_DATE") or "")[:10],
                revenue=_number(row.get("TOTALOPERATEREVE")),
                revenue_yoy=_number(row.get("TOTALOPERATEREVETZ")), profit=_number(row.get("PARENTNETPROFIT")),
                profit_yoy=_number(row.get("PARENTNETPROFITTZ")), roe=_number(row.get("ROEJQ")), status="ok",
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            return FinanceFacts(error=str(exc))


class EastmoneyIndustryProvider:
    name = "eastmoney-industry"
    _hosts = ("17.push2.eastmoney.com", "push2.eastmoney.com", "push2his.eastmoney.com")
    _cache: tuple[float, list[dict], str] | None = None

    def __init__(self, timeout_seconds: float = 8):
        self.timeout_seconds = timeout_seconds

    def fetch(self, code: str) -> IndustryFacts:
        market = "1" if code.startswith("sh") else "0"
        clean = code[2:]
        try:
            stock_urls = [
                f"https://{host}/api/qt/stock/get?secid={market}.{clean}&fields=f57,f58,f127"
                for host in self._hosts
            ]
            stock, stock_endpoint = _json_request_any(stock_urls, self.timeout_seconds)
            industry = (stock.get("data") or {}).get("f127")
            if not industry:
                raise ValueError("industry unavailable")
            rows, industry_endpoint = self._industries()
            matches = [row for row in rows if row.get("f14") == industry]
            if not matches:
                return IndustryFacts(name=industry, endpoint=f"{urlsplit(stock_endpoint).netloc}; {urlsplit(industry_endpoint).netloc}", status="degraded", error="industry not found in heat table")
            ordered = sorted(rows, key=lambda row: _number(row.get("f3")) if _number(row.get("f3")) is not None else -999, reverse=True)
            rank = next((index + 1 for index, row in enumerate(ordered) if row.get("f14") == industry), None)
            row = matches[0]
            return IndustryFacts(name=industry, rank=rank, total=len(ordered), change_pct=_number(row.get("f3")),
                                 main_inflow=round(_number(row.get("f62")) / 1e8, 4) if _number(row.get("f62")) is not None else None,
                                 endpoint=f"{urlsplit(stock_endpoint).netloc}; {urlsplit(industry_endpoint).netloc}", status="ok")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            return IndustryFacts(error=str(exc))

    def _industries(self) -> tuple[list[dict], str]:
        now = time.time()
        if self._cache and now - self._cache[0] < 300:
            return self._cache[1], self._cache[2]
        params = {
            "pn": 1,
            "pz": 600,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": "m:90 t:2 f:!50",
            "fields": "f12,f14,f3,f62",
        }
        urls = [f"https://{host}/api/qt/clist/get?{urlencode(params)}" for host in self._hosts]
        payload, endpoint = _json_request_any(urls, self.timeout_seconds)
        diff = (payload.get("data") or {}).get("diff") or []
        rows = list(diff.values()) if isinstance(diff, dict) else list(diff)
        self._cache = (now, rows, endpoint)
        return rows, endpoint


class EastmoneyNewsProvider:
    name = "eastmoney-news"

    def __init__(self, timeout_seconds: float = 8):
        self.timeout_seconds = timeout_seconds

    def fetch(self, name: str, limit: int = 8) -> NewsFacts:
        param = json.dumps({"uid": "", "keyword": name, "type": ["cmsArticleWebOld"], "client": "web", "page_index": 1, "page_size": limit, "search_type": "title"}, ensure_ascii=False, separators=(",", ":"))
        params = urlencode({"cb": "jQuery", "param": param})
        try:
            raw = self._request_text("https://search-api-web.eastmoney.com/search/jsonp?" + params)
            body = raw[raw.find("(") + 1:raw.rfind(")")] if "(" in raw else raw
            payload = json.loads(body)
            rows = payload.get("result", {}).get("cmsArticleWebOld", [])
            return NewsFacts(items=[self._item(row) for row in rows[:limit]], status="ok")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            return NewsFacts(error=str(exc))

    def _request_text(self, url: str) -> str:
        return _request_text(url, self.timeout_seconds, referer="https://so.eastmoney.com/")

    @staticmethod
    def _item(row: dict) -> NewsItem:
        title = _clean_html(row.get("title"))
        snippet = _clean_html(row.get("content"))
        text = title + " " + snippet
        bull = sum(word in text for word in ("利好", "涨停", "增长", "回购", "中标", "订单", "增持", "突破", "超预期", "获批"))
        bear = sum(word in text for word in ("利空", "跌停", "亏损", "减持", "风险", "处罚", "立案", "下调", "退市", "暴雷", "下滑"))
        return NewsItem(title=title or "未命名新闻", snippet=snippet, source_name=str(row.get("mediaName") or ""), published_at=str(row.get("date") or ""), url=str(row.get("url") or ""), sentiment="bull" if bull > bear else "bear" if bear > bull else "neutral")


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _clean_html(value: object) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()
