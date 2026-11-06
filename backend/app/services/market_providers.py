"""Market data providers: fetch and parse only, never assemble an envelope.

The default implementation talks to the same upstream endpoints as the legacy
dashboard, but every call is read-only: no CSV, no name-table rebuild, no
directory creation. Timeout / rate-limit / parse / other upstream failures are
normalised into :class:`ProviderError` so the service layer maps them to the
four data-source error codes once.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Protocol

import requests

from backend.app.services.market_clock import (
    CST,
    format_cst,
    latest_trading_day,
    now_cst,
    parse_day,
    previous_trading_day,
    to_cst,
)
from backend.app.services.market_envelope import ERROR_MESSAGES
from backend.app.services.ticker_directory import market_for

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

INDEX_ORDER = (
    ("000001", "上证指数"),
    ("399001", "深证成指"),
    ("399006", "创业板指"),
)

_PERIOD_CATEGORY = {"day": 4, "week": 5, "month": 6}


class ProviderError(RuntimeError):
    """A provider failure classified into one of the frozen error kinds."""

    KINDS = {
        "timeout": "upstream_timeout",
        "rate_limited": "upstream_rate_limited",
        "parse_error": "data_parse_error",
        "upstream": "upstream_error",
    }

    def __init__(self, kind: str, message: str | None = None) -> None:
        if kind not in self.KINDS:
            raise ValueError(f"未知 provider 异常类型: {kind}")
        self.kind = kind
        self.code = self.KINDS[kind]
        self.message = message or ERROR_MESSAGES.get(self.code, "数据服务暂时不可用")
        super().__init__(self.message)


@dataclass(frozen=True)
class Fetched:
    """One provider answer, before it is placed into a block."""

    data: Any
    as_of: str | None
    source: str
    status: str = "ok"
    stale_reason: str | None = None


def classify_exception(exc: BaseException) -> str:
    if isinstance(exc, ProviderError):
        return exc.kind
    if isinstance(exc, requests.Timeout):
        return "timeout"
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        if response is not None and response.status_code == 429:
            return "rate_limited"
        return "upstream"
    return "upstream"


def as_provider_error(exc: BaseException) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    return ProviderError(classify_exception(exc))


class MarketProviderProtocol(Protocol):
    def indices(self) -> Fetched: ...
    def northbound(self) -> Fetched: ...
    def industries(self, top: int = 20) -> Fetched: ...
    def constituents(self, board_code: str, limit: int = 10) -> Fetched: ...
    def strong_stocks(self, date_str: str | None = None) -> Fetched: ...
    def newsflash(self, limit: int = 30) -> Fetched: ...
    def quote(self, ticker: str) -> Fetched: ...
    def valuation(self, ticker: str) -> Fetched: ...
    def sector_blocks(self, ticker: str) -> Fetched: ...
    def kline(self, ticker: str, period: str = "day", limit: int = 120) -> Fetched: ...
    def intraday(self, ticker: str, date_str: str | None = None) -> Fetched: ...
    def stock_news(self, ticker: str, limit: int = 20) -> Fetched: ...
    def fund_flow(self, ticker: str) -> Fetched: ...


class DefaultMarketProviders:
    """Live adapters for Tencent, Eastmoney, THS, Hexin, CLS, Baidu, mootdx."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or now_cst

    # -- market overview ---------------------------------------------------
    def indices(self) -> Fetched:
        url = "https://qt.gtimg.cn/q=sh000001,sz399001,sz399006"
        response = _get(url)
        text = response.content.decode("gbk", errors="replace")
        parsed: dict[str, dict[str, Any]] = {}
        for line in text.split(";"):
            if "=" not in line or '"' not in line:
                continue
            key, content = line.split("=", 1)
            code = key.strip().split("_")[-1]
            if code[:2] in ("sh", "sz"):
                code = code[2:]
            values = content.strip().strip('";\n').split("~")
            if len(values) < 33:
                continue
            parsed[code] = {
                "price": _number(values[3], 0.0),
                "change_pct": _number(values[32], 0.0),
                "change_amt": _number(values[31], 0.0),
            }
        items = []
        for code, name in INDEX_ORDER:
            if code not in parsed:
                raise ProviderError("parse_error", f"指数 {code} 缺失")
            items.append({"code": code, "name": name, **parsed[code]})
        return Fetched(data=items, as_of=format_cst(self._clock()), source="tencent")

    def northbound(self) -> Fetched:
        url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        headers = {
            "User-Agent": _UA,
            "Host": "data.hexin.cn",
            "Referer": "https://data.hexin.cn/",
        }
        payload = _json(_get(url, headers=headers))
        times = payload.get("time") or []
        if not times:
            return Fetched(status="empty", data=None, as_of=None, source="hexin")
        hgt = payload.get("hgt") or []
        sgt = payload.get("sgt") or []
        points = []
        for index, stamp in enumerate(times):
            points.append(
                {
                    "time": stamp,
                    "hgt_yi": _nth(hgt, index),
                    "sgt_yi": _nth(sgt, index),
                }
            )
        latest = {"hgt_yi": points[-1]["hgt_yi"], "sgt_yi": points[-1]["sgt_yi"]}
        return Fetched(
            data={"points": points, "latest": latest},
            as_of=format_cst(self._clock()),
            source="hexin",
        )

    def industries(self, top: int = 20) -> Fetched:
        items = _eastmoney_industries()
        if not items:
            return Fetched(status="empty", data=None, as_of=None, source="eastmoney")
        bottom = list(reversed(items[-top:]))
        return Fetched(
            data={"top": items[:top], "bottom": bottom, "total": len(items)},
            as_of=format_cst(self._clock()),
            source="eastmoney",
        )

    def constituents(self, board_code: str, limit: int = 10) -> Fetched:
        rows = _eastmoney_constituents(board_code, limit)
        if not rows:
            return Fetched(status="empty", data=None, as_of=None, source="eastmoney")
        return Fetched(
            data={"items": rows},
            as_of=format_cst(self._clock()),
            source="eastmoney",
        )

    def strong_stocks(self, date_str: str | None = None) -> Fetched:
        day = date_str or self._clock().date().isoformat()
        url = (
            "http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{day}/orderby/date/orderway/desc/charset/GBK/"
        )
        payload = _json(_get(url, headers={"User-Agent": _UA}))
        if payload.get("errocode", 0) != 0:
            raise ProviderError("upstream", str(payload.get("errormsg") or "同花顺返回错误"))
        rows = payload.get("data") or []
        if not rows:
            return Fetched(status="empty", data=None, as_of=None, source="ths")

        codes = [str(row.get("code", "")).strip() for row in rows]
        try:
            quotes = _tencent_quotes([code for code in codes if code]) or {}
        except ProviderError:
            quotes = {}
        items = []
        for row in rows:
            code = str(row.get("code", "")).strip()
            quote = quotes.get(code, {})
            items.append(
                {
                    "ticker_code": code,
                    "name": str(row.get("name", "")),
                    "reason": str(row.get("reason", "")),
                    "market": str(row.get("market") or market_for(code)),
                    "change_pct": _number(
                        quote.get("change_pct", row.get("zhangfu")), 0.0
                    ),
                    "change_amt": _number(quote.get("change_amt"), 0.0),
                    "close": _number(quote.get("price"), 0.0),
                    "turnover_pct": _number(
                        quote.get("turnover_pct", row.get("huanshou")), 0.0
                    ),
                }
            )
        return Fetched(
            data={"items": items}, as_of=format_cst(self._clock()), source="ths"
        )

    def newsflash(self, limit: int = 30) -> Fetched:
        url = "https://www.cls.cn/nodeapi/telegraphList"
        payload = _json(
            _get(
                url,
                params={"rn": str(limit), "page": "1"},
                headers={"User-Agent": _UA, "Referer": "https://www.cls.cn/"},
            )
        )
        roll = ((payload.get("data") or {}).get("roll_data")) or []
        if not roll:
            return Fetched(status="empty", data=None, as_of=None, source="cls")
        items = []
        for item in roll[:limit]:
            items.append(
                {
                    "title": str(item.get("title") or item.get("brief") or ""),
                    "content": str(item.get("content") or item.get("brief") or ""),
                    "published_at": _epoch_iso(item.get("ctime")),
                }
            )
        return Fetched(
            data={"items": items}, as_of=format_cst(self._clock()), source="cls"
        )

    # -- stock -------------------------------------------------------------
    def quote(self, ticker: str) -> Fetched:
        quotes = _tencent_quotes([ticker])
        payload = quotes.get(ticker)
        if not payload:
            return Fetched(status="empty", data=None, as_of=None, source="tencent")
        return Fetched(
            data=payload, as_of=format_cst(self._clock()), source="tencent"
        )

    def valuation(self, ticker: str) -> Fetched:
        forecast = _eps_forecast(ticker)
        try:
            quote = _tencent_quotes([ticker]).get(ticker) or {}
        except ProviderError:
            quote = {}
        price = _number(quote.get("price"), None)

        eps_forecast = None
        cagr = None
        if forecast:
            years = sorted(forecast)
            target = next(
                (
                    forecast[year]
                    for year in years
                    if year >= self._clock().year and forecast[year] > 0
                ),
                None,
            )
            eps_forecast = target if target is not None else forecast[years[-1]]
            positive = [(year, forecast[year]) for year in years if forecast[year] > 0]
            if len(positive) >= 2 and positive[-1][0] > positive[0][0]:
                span = positive[-1][0] - positive[0][0]
                cagr = (positive[-1][1] / positive[0][1]) ** (1 / span) - 1

        pe_forward = price / eps_forecast if price and eps_forecast and eps_forecast > 0 else None
        peg = pe_forward / (cagr * 100) if pe_forward and cagr and cagr > 0 else None
        if pe_forward is None:
            digestion = None
        elif pe_forward <= 30:
            digestion = 0.0
        elif cagr and cagr > 0:
            import math

            digestion = math.log(pe_forward / 30) / math.log(1 + cagr)
        else:
            digestion = None

        return Fetched(
            data={
                "eps_forecast": _round(eps_forecast),
                "pe_forward": _round(pe_forward),
                "peg": _round(peg),
                "pe_digestion_years": _round(digestion),
            },
            as_of=format_cst(self._clock()),
            source="ths",
        )

    def sector_blocks(self, ticker: str) -> Fetched:
        url = "https://finance.pae.baidu.com/api/getrelatedblock"
        params = {
            "stock": json.dumps(
                [{"code": ticker, "market": "ab", "type": "stock"}],
                separators=(",", ":"),
            ),
            "finClientType": "pc",
        }
        headers = {
            "User-Agent": _UA,
            "Accept": "application/vnd.finance-" "web" ".v1+json",
            "Origin": "https://gushitong.baidu.com",
            "Referer": "https://gushitong.baidu.com/",
        }
        payload = _json(_get(url, params=params, headers=headers))
        if str(payload.get("ResultCode", -1)) != "0":
            raise ProviderError("upstream", str(payload.get("ResultMsg") or "百度返回错误"))
        result = payload.get("Result")
        if isinstance(result, dict) and result.get("code") == 403:
            raise ProviderError("upstream", "百度接口风控拦截")
        categories = result.get(ticker) if isinstance(result, dict) else result
        categories = categories or []
        buckets: dict[str, list[dict[str, Any]]] = {
            "industry": [],
            "concept": [],
            "region": [],
        }
        for category in categories:
            if not isinstance(category, dict):
                continue
            label = str(category.get("name", ""))
            for item in category.get("list") or []:
                entry = {
                    "name": str(item.get("name", "")),
                    "change_pct": _number(
                        item.get("increase", item.get("ratio")), None
                    ),
                    "desc": str(item.get("describe") or item.get("desc") or ""),
                }
                if "行业" in label:
                    buckets["industry"].append(entry)
                elif "概念" in label:
                    buckets["concept"].append(entry)
                elif "地域" in label:
                    buckets["region"].append(entry)
        if not any(buckets.values()):
            return Fetched(status="empty", data=None, as_of=None, source="baidu")
        return Fetched(
            data=buckets, as_of=format_cst(self._clock()), source="baidu"
        )

    def kline(self, ticker: str, period: str = "day", limit: int = 120) -> Fetched:
        frame = _mootdx_bars(ticker, period, limit)
        source = "mootdx"
        if frame is None or frame.empty:
            frame = _sina_daily_bars(ticker)
            source = "mixed"
        if frame is None or frame.empty:
            return Fetched(status="empty", data=None, as_of=None, source=source)

        if source == "mixed":
            frame = _resample(frame, period)
        frame = frame.tail(limit)
        bars = []
        for row in frame:
            bars.append(
                {
                    "date": row["date"],
                    "open": _round(row["open"]),
                    "high": _round(row["high"]),
                    "low": _round(row["low"]),
                    "close": _round(row["close"]),
                    "volume": _round(row["volume"]),
                    "amount": _round(row.get("amount")),
                }
            )
        return Fetched(
            data={
                "adjust": "none",
                "bars": bars,
                "units": {"price": "元", "volume": "手", "amount": "元"},
            },
            as_of=bars[-1]["date"],
            source=source,
        )

    def intraday(self, ticker: str, date_str: str | None = None) -> Fetched:
        requested = parse_day(date_str) if date_str else latest_trading_day(self._clock())
        if requested is None:
            requested = latest_trading_day(self._clock())
        slot = requested if requested.weekday() < 5 else previous_trading_day(requested)

        frame = _mootdx_minutes(ticker, slot)
        source = "mootdx"
        if (frame is None or frame.empty) and not date_str:
            fallback_slot = previous_trading_day(slot - timedelta(days=1))
            frame = _mootdx_minutes(ticker, fallback_slot)
            if frame is not None and not frame.empty:
                slot = fallback_slot
        if frame is None or frame.empty:
            frame = _eastmoney_5min_bars(ticker, slot)
            source = "mixed"
        if frame is None or frame.empty:
            return Fetched(status="empty", data=None, as_of=None, source=source)

        points = _intraday_points(frame)
        if not points:
            return Fetched(status="empty", data=None, as_of=None, source=source)
        as_of = (
            format_cst(self._clock())
            if slot >= latest_trading_day(self._clock())
            else f"{slot.isoformat()}T15:00:00+08:00"
        )
        return Fetched(
            data={
                "date": slot.isoformat(),
                "points": points,
                "session_gaps": [["11:30", "13:00"]],
                "units": {"price": "元", "volume": "手", "amount": "元"},
            },
            as_of=as_of,
            source=source,
        )

    def stock_news(self, ticker: str, limit: int = 20) -> Fetched:
        articles: list[dict[str, Any]] = []
        source = "eastmoney"
        try:
            articles = _eastmoney_news(ticker, limit)
        except ProviderError:
            articles = []
        if not articles:
            source = "mixed"
            try:
                articles = _sina_news(ticker, limit)
            except ProviderError:
                articles = []
        if not articles:
            return Fetched(status="empty", data=None, as_of=None, source=source)
        items = [
            {
                "title": _plain(article.get("title")),
                "content": _plain(article.get("content")),
                "published_at": str(article.get("time") or ""),
                "source": _plain(article.get("source")),
                "url": str(article.get("url") or ""),
            }
            for article in articles[:limit]
        ]
        return Fetched(
            data={"items": items}, as_of=format_cst(self._clock()), source=source
        )

    def fund_flow(self, ticker: str) -> Fetched:
        items = _eastmoney_fund_flow(ticker)
        if not items:
            return Fetched(status="empty", data=None, as_of=None, source="eastmoney")
        return Fetched(
            data={"items": items},
            as_of=format_cst(self._clock()),
            source="eastmoney",
        )


class FakeMarketProviders:
    """Test double: fixed results, fixed errors, delays and call counting."""

    def __init__(self, *, default_source: str = "static") -> None:
        self.default_source = default_source
        self.calls: Counter[str] = Counter()
        self._results: dict[str, Any] = {}
        self._errors: dict[str, BaseException] = {}
        self._delays: dict[str, float] = {}

    def set(
        self,
        method: str,
        result: Fetched | Callable[..., Fetched] | None = None,
        *,
        error: BaseException | None = None,
        delay: float = 0.0,
    ) -> None:
        if result is None:
            result = Fetched(
                status="empty", data=None, as_of=None, source=self.default_source
            )
        self._results[method] = result
        if error is not None:
            self._errors[method] = error
        else:
            self._errors.pop(method, None)
        self._delays[method] = delay

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Fetched:
        self.calls[method] += 1
        delay = self._delays.get(method, 0.0)
        if delay:
            time.sleep(delay)
        if method in self._errors:
            raise self._errors[method]
        value = self._results.get(method)
        if callable(value):
            return value(*args, **kwargs)
        if value is None:
            return Fetched(
                status="empty", data=None, as_of=None, source=self.default_source
            )
        return value

    def indices(self) -> Fetched:
        return self._call("indices")

    def northbound(self) -> Fetched:
        return self._call("northbound")

    def industries(self, top: int = 20) -> Fetched:
        return self._call("industries", top)

    def constituents(self, board_code: str, limit: int = 10) -> Fetched:
        return self._call("constituents", board_code, limit)

    def strong_stocks(self, date_str: str | None = None) -> Fetched:
        return self._call("strong_stocks", date_str)

    def newsflash(self, limit: int = 30) -> Fetched:
        return self._call("newsflash", limit)

    def quote(self, ticker: str) -> Fetched:
        return self._call("quote", ticker)

    def valuation(self, ticker: str) -> Fetched:
        return self._call("valuation", ticker)

    def sector_blocks(self, ticker: str) -> Fetched:
        return self._call("sector_blocks", ticker)

    def kline(self, ticker: str, period: str = "day", limit: int = 120) -> Fetched:
        return self._call("kline", ticker, period, limit)

    def intraday(self, ticker: str, date_str: str | None = None) -> Fetched:
        return self._call("intraday", ticker, date_str)

    def stock_news(self, ticker: str, limit: int = 20) -> Fetched:
        return self._call("stock_news", ticker, limit)

    def fund_flow(self, ticker: str) -> Fetched:
        return self._call("fund_flow", ticker)


# -- helpers -----------------------------------------------------------------


def _get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
) -> requests.Response:
    try:
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
    except requests.Timeout as exc:
        raise ProviderError("timeout") from exc
    except requests.RequestException as exc:
        raise as_provider_error(exc) from exc
    _check_status(response)
    return response


def _check_status(response: requests.Response) -> None:
    if response.status_code == 429:
        raise ProviderError("rate_limited")
    if response.status_code >= 400:
        raise ProviderError("upstream", f"上游返回 HTTP {response.status_code}")


def _json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderError("parse_error") from exc
    if not isinstance(payload, dict):
        raise ProviderError("parse_error")
    return payload


def _number(value: Any, default: float | None) -> float | None:
    if value in (None, "", "-", "--", "—"):
        return default
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ProviderError("parse_error") from exc


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _nth(items: list[Any], index: int) -> Any:
    return items[index] if index < len(items) else None


def _epoch_iso(value: Any) -> str:
    try:
        return format_cst(datetime.fromtimestamp(int(value), tz=CST))
    except (TypeError, ValueError, OSError):
        return str(value or "")


def _plain(value: Any) -> str:
    return re.sub(r"<[^>]+>", "", str(value or "")).strip()


def _em_get(url: str, params: dict[str, Any], timeout: float = 15) -> requests.Response:
    from tradingagents.dataflows.a_stock._common import _em_get as em_get

    try:
        response = em_get(url, params=params, headers={"User-Agent": _UA}, timeout=timeout)
    except requests.RequestException as exc:
        raise as_provider_error(exc) from exc
    _check_status(response)
    return response


def _tencent_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    from tradingagents.dataflows.a_stock._common import _tencent_quote

    try:
        return _tencent_quote(codes)
    except requests.RequestException as exc:
        raise as_provider_error(exc) from exc


def _eastmoney_industries() -> list[dict[str, Any]]:
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
    }
    payload = _json(_em_get(url, params))
    items = (payload.get("data") or {}).get("diff")
    if items is None:
        raise ProviderError("parse_error")
    rows = []
    for index, item in enumerate(items):
        rows.append(
            {
                "rank": index + 1,
                "name": str(item.get("f14", "")),
                "code": str(item.get("f12", "")),
                "change_pct": _round(_number(item.get("f3"), 0.0)),
                "up_count": _number(item.get("f104"), 0),
                "down_count": _number(item.get("f105"), 0),
                "leader": str(item.get("f128", "")),
                "leader_change": _round(_number(item.get("f136"), 0.0)),
            }
        )
    return rows


def _eastmoney_constituents(board_code: str, limit: int) -> list[dict[str, Any]]:
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": str(limit),
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fs": f"b:{board_code}",
        "fields": "f2,f3,f12,f14",
    }
    payload = _json(_em_get(url, params))
    items = (payload.get("data") or {}).get("diff") or []
    return [
        {
            "code": str(item.get("f12", "")),
            "name": str(item.get("f14", "")),
            "price": _number(item.get("f2"), None),
            "change_pct": _number(item.get("f3"), None),
        }
        for item in items
    ]


def _eps_forecast(ticker: str) -> dict[int, float]:
    from tradingagents.dataflows.a_stock._common import _ths_eps_forecast

    try:
        frame = _ths_eps_forecast(ticker)
    except requests.RequestException as exc:
        raise as_provider_error(exc) from exc
    if frame is None or frame.empty:
        return {}
    columns = {str(column): column for column in frame.columns}
    mean_column = next(
        (original for label, original in columns.items() if "均值" in label), None
    )
    if mean_column is None:
        mean_column = next(
            (original for label, original in columns.items() if "每股收益" in label),
            None,
        )
    if mean_column is None:
        return {}
    year_column = next(
        (original for label, original in columns.items() if "年度" in label), None
    )
    result: dict[int, float] = {}
    for _, row in frame.iterrows():
        raw_year = row[year_column] if year_column is not None else row.iloc[0]
        match = re.search(r"(20\d{2})", str(raw_year))
        if not match:
            continue
        value = _number(row[mean_column], None)
        if value is not None:
            result[int(match.group(1))] = value
    return result


def _mootdx_bars(ticker: str, period: str, limit: int):
    try:
        from tradingagents.dataflows.a_stock._common import _get_mootdx_client

        client = _get_mootdx_client()
        frame = client.bars(
            symbol=ticker, category=_PERIOD_CATEGORY.get(period, 4), offset=limit
        )
    except Exception:
        return None
    return _normalize_bar_frame(frame)


def _sina_daily_bars(ticker: str):
    try:
        from tradingagents.dataflows.a_stock._common import _sina_kline_fallback

        frame = _sina_kline_fallback(ticker)
    except Exception:
        return None
    if frame is None or frame.empty:
        return frame
    frame = frame.rename(
        columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    frame["amount"] = None
    return _normalize_bar_frame(frame, already=True)


def _normalize_bar_frame(frame, *, already: bool = False):
    if frame is None or frame.empty:
        return frame
    if not already:
        frame = frame.rename(
            columns={
                "datetime": "date",
                "vol": "volume",
            }
        )
    if "date" not in frame.columns:
        frame = frame.reset_index().rename(columns={"index": "date"})
    for column in ("open", "high", "low", "close", "volume"):
        if column not in frame.columns:
            raise ProviderError("parse_error", f"K 线缺少 {column}")
    if "amount" not in frame.columns:
        frame["amount"] = None
    frame["date"] = frame["date"].map(_day_text)
    frame = frame[["date", "open", "high", "low", "close", "volume", "amount"]]
    return frame.sort_values("date").reset_index(drop=True)


def _resample(frame, period: str):
    if period not in ("week", "month") or frame.empty:
        return frame
    import pandas as pd

    working = frame.copy()
    working["date"] = pd.to_datetime(working["date"])
    working = working.set_index("date")
    rule = "W-FRI" if period == "week" else "ME"
    grouped = working.resample(rule).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "amount": "sum",
        }
    )
    grouped = grouped.dropna(subset=["open", "close"]).reset_index()
    grouped["date"] = grouped["date"].map(_day_text)
    return grouped


def _day_text(value: Any) -> str:
    if isinstance(value, datetime):
        return to_cst(value).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    return text[:10]


def _mootdx_minutes(ticker: str, slot: date):
    try:
        from tradingagents.dataflows.a_stock._common import _get_mootdx_client

        client = _get_mootdx_client()
        frame = client.minutes(symbol=ticker, date=slot.strftime("%Y%m%d"))
    except Exception:
        return None
    if frame is None or frame.empty:
        return frame
    return frame


def _eastmoney_5min_bars(ticker: str, slot: date):
    import pandas as pd

    clean = slot.strftime("%Y%m%d")
    secid = f"1.{ticker}" if ticker.startswith("6") else f"0.{ticker}"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "klt": "5",
        "fqt": "0",
        "beg": clean,
        "end": clean,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    payload = _json(_em_get(url, params))
    klines = (payload.get("data") or {}).get("klines") or []
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        rows.append(
            {
                "datetime": pd.to_datetime(parts[0]),
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("datetime")


def _session_times(count: int) -> list[str]:
    labels = []
    for index in range(count):
        if index < 120:
            minute = 9 * 60 + 30 + index
        else:
            minute = 13 * 60 + (index - 120)
        labels.append(f"{minute // 60:02d}:{minute % 60:02d}")
    return labels


def _intraday_points(frame) -> list[dict[str, Any]]:
    price_column = "price" if "price" in frame.columns else "close"
    volume_column = next(
        (name for name in ("vol", "volume") if name in frame.columns), None
    )
    if price_column not in frame.columns:
        raise ProviderError("parse_error", "分时缺少价格列")
    prices = [_number(value, None) for value in frame[price_column].tolist()]
    volumes = (
        [_number(value, 0.0) for value in frame[volume_column].tolist()]
        if volume_column
        else [0.0] * len(prices)
    )
    index_values = list(frame.index)
    if index_values and isinstance(index_values[0], datetime):
        labels = [stamp.strftime("%H:%M") for stamp in index_values]
    else:
        labels = _session_times(len(prices))
    points = []
    cumulative_amount = 0.0
    cumulative_volume = 0.0
    for label, price, volume in zip(labels, prices, volumes):
        if price is None:
            continue
        volume = volume or 0.0
        cumulative_amount += price * volume
        cumulative_volume += volume
        average = (
            cumulative_amount / cumulative_volume if cumulative_volume > 0 else None
        )
        points.append(
            {
                "time": label,
                "price": _round(price),
                "volume": _round(volume),
                "avg_price": _round(average),
            }
        )
    return points


def _eastmoney_news(ticker: str, limit: int) -> list[dict[str, Any]]:
    from tradingagents.dataflows.a_stock.news import _fetch_news_eastmoney

    try:
        return _fetch_news_eastmoney(ticker, page_size=limit)
    except requests.RequestException as exc:
        raise as_provider_error(exc) from exc
    except Exception as exc:
        raise ProviderError("parse_error") from exc


def _sina_news(ticker: str, limit: int) -> list[dict[str, Any]]:
    from tradingagents.dataflows.a_stock.news import _fetch_news_sina

    try:
        return _fetch_news_sina(ticker, page_size=limit)
    except requests.RequestException as exc:
        raise as_provider_error(exc) from exc
    except Exception as exc:
        raise ProviderError("parse_error") from exc


def _eastmoney_fund_flow(ticker: str) -> list[dict[str, Any]]:
    secid = f"1.{ticker}" if ticker.startswith("6") else f"0.{ticker}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid,
        "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    payload = _json(_em_get(url, params, timeout=10))
    klines = (payload.get("data") or {}).get("klines") or []
    items = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        items.append(
            {
                "time": parts[0],
                "main_net": _number(parts[1], 0.0),
                "small_net": _number(parts[2], 0.0),
                "mid_net": _number(parts[3], 0.0),
                "large_net": _number(parts[4], 0.0),
                "super_net": _number(parts[5], 0.0),
            }
        )
    return items
