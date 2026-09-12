"""Shared infrastructure for the A-stock data vendor.

Ticker resolution, mootdx (通达信) client singleton, throttled Eastmoney HTTP,
腾讯/同花顺/新浪 helpers and the OHLCV cache + Sina supplement chain.

Domain modules access these helpers through this module's namespace
(``_common.xxx``) so tests only ever need to patch one place.
"""

from __future__ import annotations

from typing import Annotated
from datetime import datetime
from dateutil.relativedelta import relativedelta
import json as _json
import os
import logging
import math
import random
import re as _re
import socket
import threading
import time
import uuid
import urllib.request

import pandas as pd
import requests as _requests

from ..utils import safe_ticker_component

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers: ticker format & market detection
# ---------------------------------------------------------------------------

def _get_prefix(code: str) -> str:
    """6-digit A-stock code -> market prefix for Tencent API."""
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    return "sz"


def _normalize_ticker(symbol: str) -> str:
    """Strip exchange prefix/suffix, return pure 6-digit code.

    Handles: '688017', 'SH688017', '688017.SH', 'sh688017'
    """
    s = symbol.strip().upper()
    # Remove .SH / .SZ / .BJ suffix
    for suffix in (".SH", ".SZ", ".BJ"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    # Remove SH / SZ / BJ prefix
    for prefix in ("SH", "SZ", "BJ"):
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    return safe_ticker_component(s)


# ---------------------------------------------------------------------------
# Stock name <-> code mapping (cached)
# ---------------------------------------------------------------------------

_name_to_code: dict[str, str] | None = None
_code_to_name: dict[str, str] | None = None


def _cache_dir() -> str:
    from ..config import get_config

    d = get_config().get("data_cache_dir", os.path.expanduser("~/.tradingagents/cache"))
    os.makedirs(d, exist_ok=True)
    return d


def _build_name_code_map() -> tuple[dict[str, str], dict[str, str]]:
    """Build name→code and code→name maps via mootdx (both SH & SZ markets)."""
    global _name_to_code, _code_to_name
    if _name_to_code is not None:
        return _name_to_code, _code_to_name

    # 进程级缓存之外再加按天落盘缓存：全市场列表拉取要走 TCP 遍历两个市场，
    # 每次进程重启都重拉一遍纯属浪费。
    disk_cache = os.path.join(
        _cache_dir(), f"name-code-map-{datetime.now():%Y%m%d}.json"
    )
    if os.path.exists(disk_cache):
        try:
            with open(disk_cache, "r", encoding="utf-8") as f:
                data = _json.load(f)
            _name_to_code = data["n2c"]
            _code_to_name = data["c2n"]
            logger.info("Loaded name-code map from disk: %d entries", len(_name_to_code))
            return _name_to_code, _code_to_name
        except Exception as e:
            logger.warning("name-code disk cache unreadable (%s), rebuilding", e)

    client = _get_mootdx_client()
    n2c: dict[str, str] = {}
    c2n: dict[str, str] = {}

    try:
        for market in (0, 1):  # 0=SZ, 1=SH
            stocks = client.stocks(market=market)
            if stocks is None or stocks.empty:
                continue
            for _, row in stocks.iterrows():
                code = str(row["code"]).strip()
                name = str(row["name"]).strip()
                if not _re.match(r"^[036]\d{5}$", code):
                    continue
                clean_name = name.replace(" ", "").replace("　", "")
                n2c[clean_name] = code
                c2n[code] = clean_name
    except Exception as e:
        # 网络抖动/通达信不可达时给出明确提示，而非冒泡成风马牛不相及的报错（#46/#66）
        raise ValueError(
            "无法通过 mootdx 解析股票名称（通达信服务暂时不可达）：%s。"
            "请稍后重试，或直接输入 6 位股票代码。" % e
        ) from e

    _name_to_code = n2c
    _code_to_name = c2n
    try:
        with open(disk_cache, "w", encoding="utf-8") as f:
            _json.dump({"n2c": n2c, "c2n": c2n}, f, ensure_ascii=False)
    except Exception as e:
        logger.warning("name-code disk cache write failed: %s", e)
    logger.info("Built stock name-code map: %d entries", len(n2c))
    return _name_to_code, _code_to_name


def resolve_ticker(user_input: str) -> str:
    """Resolve user input (code or Chinese name) to a 6-digit A-stock code.

    Accepts: '600379', 'SH600379', '600379.SH', '宝光股份'
    Returns: '600379'
    Raises: ValueError if not resolvable.
    """
    s = user_input.strip()
    if not s:
        raise ValueError("输入不能为空")

    has_chinese = any("一" <= ch <= "鿿" for ch in s)

    if not has_chinese:
        return _normalize_ticker(s)

    clean = s.replace(" ", "").replace("　", "")
    n2c, _ = _build_name_code_map()

    if clean in n2c:
        return n2c[clean]

    matches = {name: code for name, code in n2c.items() if clean in name}
    if len(matches) == 1:
        return next(iter(matches.values()))
    if len(matches) > 1:
        examples = ", ".join(f"{n}({c})" for n, c in list(matches.items())[:5])
        raise ValueError(f"'{s}' 匹配到多只股票: {examples}，请输入完整名称或代码")

    raise ValueError(f"找不到股票 '{s}'，请检查名称是否正确")


# ---------------------------------------------------------------------------
# mootdx client (singleton)
# ---------------------------------------------------------------------------

_mootdx_client = None

# pytdx 底层 socket 收发非线程安全：web runner 的 daemon 线程跑分析时，
# dashboard 可能并发复用同一客户端拉 K 线。所有客户端方法调用经此锁串行化。
_TDX_LOCK = threading.Lock()


class _LockedTdxClient:
    """mootdx 客户端代理：每个方法调用在 _TDX_LOCK 内执行。"""

    def __init__(self, client):
        self._locked_client = client

    def __getattr__(self, name):
        attr = getattr(self._locked_client, name)
        if not callable(attr):
            return attr

        def _locked(*args, **kwargs):
            with _TDX_LOCK:
                return attr(*args, **kwargs)

        return _locked

# 实测可用的通达信备选服务器（按延迟排序，2026-06 验证）。用于规避 mootdx
# 0.11.x 全新安装时 BESTIP.HQ 为空串导致的 `ValueError: not enough values to unpack`。
_TDX_SERVERS = [
    ("119.97.185.59", 7709), ("124.70.133.119", 7709), ("116.205.183.150", 7709),
    ("123.60.73.44", 7709), ("116.205.163.254", 7709), ("121.36.225.169", 7709),
    ("123.60.70.228", 7709), ("124.71.9.153", 7709), ("110.41.147.114", 7709),
    ("124.71.187.122", 7709),
]


def _probe_tdx(ip: str, port: int, timeout: float = 2.0) -> bool:
    """TCP 握手探测通达信服务器是否可达。"""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _get_mootdx_client():
    """Lazy-init 健壮版 mootdx Quotes client（TCP 连接，可复用）。

    规避 mootdx 0.11.x 全新安装的 BESTIP 空串 bug：先 TCP 探测内置服务器列表、
    用第一个可达的显式 server 绕过 BESTIP；三级 fallback（bestip 测速 → 裸 factory →
    明确 RuntimeError）保证 IP 老化/换网/老用户场景都能工作。
    """
    global _mootdx_client
    if _mootdx_client is not None:
        return _mootdx_client

    from mootdx.quotes import Quotes

    for ip, port in _TDX_SERVERS:
        if _probe_tdx(ip, port):
            _mootdx_client = _LockedTdxClient(
                Quotes.factory(market="std", server=(ip, port))
            )
            return _mootdx_client
    try:
        _mootdx_client = _LockedTdxClient(
            Quotes.factory(market="std", bestip=True)
        )  # fallback 1
        return _mootdx_client
    except Exception:
        pass
    try:
        _mootdx_client = _LockedTdxClient(
            Quotes.factory(market="std")
        )  # fallback 2（老用户 config 已有 IP）
        return _mootdx_client
    except Exception as e:
        raise RuntimeError(
            "mootdx 通达信服务器均不可达（TCP 7709）。海外网络通常全部超时，"
            "请走国内代理或直接使用 6 位股票代码。原始错误：%s" % e
        ) from e


# ---------------------------------------------------------------------------
# Tencent Finance API
# ---------------------------------------------------------------------------

def _tencent_quote(codes: list[str]) -> dict[str, dict]:
    """Batch real-time quotes from Tencent Finance (qt.gtimg.cn).

    Returns dict[code] -> {name, price, pe_ttm, pb, mcap_yi, ...}
    """
    prefixed = [f"{_get_prefix(c)}{c}" for c in codes]
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = _retry_once(
        lambda: urllib.request.urlopen(req, timeout=10), "tencent quote"
    )
    raw = resp.read().decode("gbk")

    result = {}
    for line in raw.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]  # strip sh/sz/bj prefix
        result[code] = {
            "name": vals[1],
            "price": float(vals[3]) if vals[3] else 0,
            "last_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
            "change_amt": float(vals[31]) if vals[31] else 0,
            "high": float(vals[33]) if vals[33] else 0,
            "low": float(vals[34]) if vals[34] else 0,
            "amount_wan": float(vals[37]) if vals[37] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm": float(vals[39]) if vals[39] else 0,
            "amplitude_pct": float(vals[43]) if vals[43] else 0,
            "mcap_yi": float(vals[44]) if vals[44] else 0,
            "float_mcap_yi": float(vals[45]) if vals[45] else 0,
            "pb": float(vals[46]) if vals[46] else 0,
            "limit_up": float(vals[47]) if vals[47] else 0,
            "limit_down": float(vals[48]) if vals[48] else 0,
            "vol_ratio": float(vals[49]) if vals[49] else 0,
            "pe_static": float(vals[52]) if vals[52] else 0,
        }
    return result


# ---------------------------------------------------------------------------
# Eastmoney Datacenter unified helper (龙虎榜/解禁 etc.)
# ---------------------------------------------------------------------------

_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


# ---------------------------------------------------------------------------
# 东财防封：全局节流 + 会话复用 (Eastmoney anti-ban: throttle + Keep-Alive)
# ---------------------------------------------------------------------------
# 东财系 HTTP 接口（push2 / push2his / datacenter-web / search-api / np-weblist）
# 有风控：每秒 >5 次 / 单 IP 并发 ≥10 / 1 分钟 ≥200 次 / 5 分钟 ≥300 次 → 临时封 IP。
# 多 Agent 投研跑批量分析时会高频请求东财，是被封的头号元凶。所有 eastmoney.com
# 请求一律走 _em_get()：串行限流（最小间隔 + 随机抖动）+ 复用 Keep-Alive 会话 + 默认 UA。
# 注意：仅东财接口走此入口；mootdx(TCP) / 腾讯 / 新浪 / 同花顺 / 财联社 / 百度 等
# 不限流（实测不封 IP 或风控极弱）。批量任务可调大 EM_MIN_INTERVAL 进一步降速。
_EM_SESSION = _requests.Session()
_EM_SESSION.headers.update({"User-Agent": _UA})
# 两次东财请求最小间隔(秒)；批量多 Agent 场景可设环境变量 EM_MIN_INTERVAL=1.5~2 降速。
_EM_MIN_INTERVAL = float(os.environ.get("EM_MIN_INTERVAL", "1.0"))
_em_last_call = [0.0]  # 模块级上次东财请求时间戳
_EM_LOCK = threading.Lock()  # 东财请求跨线程串行化（防封设计的一部分）


def _retry_once(fn, what: str, delay: float = 1.0):
    """Run fn() once more on failure — absorbs transient network blips.

    用于非东财源（腾讯/新浪/同花顺）：这些接口不限流也不重试，单发失败会被
    上层吞成空数据。东财的请求请走 _em_get（自带节流 + 重试）。
    """
    try:
        return fn()
    except Exception as e:
        logger.warning("%s failed (%s), retrying once", what, e)
        time.sleep(delay + random.uniform(0.0, 0.5))
        return fn()


def _em_get(url, params=None, headers=None, timeout=15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA + 失败重试。

    所有 eastmoney.com 接口都应通过它请求，避免多 Agent 高频拉数据被封 IP。
    串行限流：与上次东财请求间隔 < EM_MIN_INTERVAL 时 sleep 补足 + 0.1~0.5s 随机抖动。
    重试：连接错误/超时/5xx 自动重试 1 次（约 1s 退避），4xx 与业务错误直接抛出。
    传入的 headers 会覆盖 session 默认 UA（用于保留各端点自己的 Referer/Origin）。
    """
    # 节流时间戳的读改写跨线程无锁会有竞态（分析线程与 UI 线程同时放行），
    # 东财本就按"串行限流"设计，直接整段串行化。
    with _EM_LOCK:
        return _em_get_locked(url, params, headers, timeout, **kwargs)


def _em_get_locked(url, params=None, headers=None, timeout=15, **kwargs):
    wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))

    for attempt in range(2):
        try:
            resp = _EM_SESSION.get(
                url, params=params, headers=headers, timeout=timeout, **kwargs
            )
            _em_last_call[0] = time.time()
            if attempt == 0 and resp.status_code >= 500:
                logger.warning("EM %s returned %d, retrying once", url, resp.status_code)
                time.sleep(1.0 + random.uniform(0.0, 0.5))
                continue
            return resp
        except (_requests.ConnectionError, _requests.Timeout) as e:
            _em_last_call[0] = time.time()
            if attempt == 0:
                logger.warning("EM %s network error (%s), retrying once", url, e)
                time.sleep(1.0 + random.uniform(0.0, 0.5))
                continue
            raise
    raise RuntimeError("unreachable")


def _eastmoney_datacenter(
    report_name: str,
    columns: str = "ALL",
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
) -> list[dict]:
    """东财数据中心统一查询 — 龙虎榜/解禁 共用."""
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    r = _em_get(_DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


# ---------------------------------------------------------------------------
# 同花顺 EPS forecast helper (direct HTTP, no akshare)
# ---------------------------------------------------------------------------


def _ths_eps_forecast(code: str) -> pd.DataFrame:
    """Fetch consensus EPS forecast from 同花顺 (direct HTTP).

    Returns DataFrame with columns roughly: 年度, 预测机构数, 最小值, 均值, 最大值.
    """
    url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
    headers = {
        "User-Agent": _UA,
        "Referer": "https://basic.10jqka.com.cn/",
    }
    r = _retry_once(
        lambda: _requests.get(url, headers=headers, timeout=15), "ths eps forecast"
    )
    r.encoding = "gbk"
    dfs = pd.read_html(r.text)
    # Find the table containing EPS data
    for df in dfs:
        cols = [str(c) for c in df.columns]
        if any("每股收益" in c or "均值" in c for c in cols):
            return df
    # Fallback: return first table if exists
    return dfs[0] if dfs else pd.DataFrame()


# ---------------------------------------------------------------------------
# Sina K-line fallback helper (direct HTTP, no akshare)
# ---------------------------------------------------------------------------


def _sina_kline_fallback(code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """Fetch daily K-line from Sina HTTP API as mootdx fallback.

    Returns DataFrame with columns: Date, Open, High, Low, Close, Volume.
    """
    prefix = "sh" if code.startswith("6") else "sz"
    url = (
        "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "CN_MarketData.getKLineData"
    )
    params = {
        "symbol": f"{prefix}{code}",
        "scale": "240",  # daily
        "ma": "no",
        "datalen": "800",
    }
    r = _retry_once(
        lambda: _requests.get(url, params=params, timeout=15), "sina kline"
    )
    r.raise_for_status()
    data = _json.loads(r.text)

    if not data:
        return pd.DataFrame()

    rows = []
    for item in data:
        rows.append({
            "Date": item["day"],
            "Open": float(item["open"]),
            "High": float(item["high"]),
            "Low": float(item["low"]),
            "Close": float(item["close"]),
            "Volume": int(item["volume"]),
        })

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])

    if start_date:
        df = df[df["Date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["Date"] <= pd.to_datetime(end_date)]

    return df


def _last_ohlcv_date(df: pd.DataFrame) -> pd.Timestamp | None:
    """Return the latest OHLCV Date in a normalized dataframe."""
    if df is None or df.empty or "Date" not in df.columns:
        return None
    dates = pd.to_datetime(df["Date"], errors="coerce")
    if dates.dropna().empty:
        return None
    return dates.max().normalize()


def _normalize_ohlcv_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize OHLCV Date values to daily granularity."""
    if df is None or df.empty or "Date" not in df.columns:
        return df
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    return df.dropna(subset=["Date"])


def _needs_sina_supplement(df: pd.DataFrame, target_date: str | None) -> bool:
    """True when mootdx/cache data is older than the requested cutoff date."""
    if not target_date:
        return False
    last_date = _last_ohlcv_date(df)
    if last_date is None:
        return True
    target = pd.to_datetime(target_date).normalize()
    return last_date < target


def _merge_ohlcv(primary: pd.DataFrame, supplement: pd.DataFrame) -> pd.DataFrame:
    """Merge OHLCV frames, preferring supplement rows on duplicate dates."""
    frames = [frame for frame in (primary, supplement) if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    combined = pd.concat(frames, ignore_index=True)
    combined = _normalize_ohlcv_dates(combined)
    combined = combined.drop_duplicates(subset=["Date"], keep="last")
    combined = combined.sort_values("Date").reset_index(drop=True)
    return combined


def _supplement_stale_ohlcv_with_sina(
    code: str,
    df: pd.DataFrame,
    target_date: str | None,
    start_date: str | None = None,
) -> tuple[pd.DataFrame, bool]:
    """Use Sina daily K-line to fill dates missing from mootdx/cache data."""
    if not _needs_sina_supplement(df, target_date):
        return df, False
    try:
        sina_df = _sina_kline_fallback(code, start_date, target_date)
    except Exception as e:
        logger.warning("sina K-line supplement failed for %s: %s", code, e)
        return df, False
    if sina_df.empty:
        return df, False
    merged = _merge_ohlcv(df, sina_df)
    return merged, _last_ohlcv_date(merged) != _last_ohlcv_date(df)


# ---------------------------------------------------------------------------
# OHLCV loading with cache (mootdx -> CSV)
# ---------------------------------------------------------------------------

def _load_ohlcv_astock(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV via mootdx, cache to CSV, filter by curr_date.

    Mirrors stockstats_utils.load_ohlcv but uses mootdx instead of yfinance.
    Returns DataFrame with columns: Date, Open, High, Low, Close, Volume
    """
    from ..config import get_config

    code = _normalize_ticker(symbol)
    config = get_config()
    cache_dir = config.get(
        "data_cache_dir", os.path.expanduser("~/.tradingagents/cache")
    )
    os.makedirs(cache_dir, exist_ok=True)

    cache_file = os.path.join(cache_dir, f"{code}-astock-daily.csv")

    if os.path.exists(cache_file):
        mtime = datetime.fromtimestamp(os.path.getmtime(cache_file))
        if mtime.date() == datetime.now().date():
            data = pd.read_csv(cache_file, on_bad_lines="skip", encoding="utf-8")
            data = _normalize_ohlcv_dates(data)
            data, supplemented = _supplement_stale_ohlcv_with_sina(
                code, data, curr_date, start_date=None
            )
            if supplemented:
                data.to_csv(cache_file, index=False, encoding="utf-8")
            cutoff = pd.to_datetime(curr_date)
            return data[data["Date"] <= cutoff]

    # Fetch from mootdx — 800 daily bars (~3 years of trading days)
    try:
        client = _get_mootdx_client()
        df = client.bars(symbol=code, category=4, offset=800)

        if df is None or df.empty:
            raise ValueError(f"No OHLCV data from mootdx for {code}")

        # mootdx returns index named 'datetime' AND a column named 'datetime'
        # (plus year/month/day/hour/minute/volume). Drop duplicates before reset.
        df = df.drop(columns=["datetime", "year", "month", "day", "hour", "minute"], errors="ignore")
        df = df.reset_index()  # moves index 'datetime' → column 'datetime'
        rename_map = {
            "datetime": "Date",
            "open": "Open",
            "close": "Close",
            "high": "High",
            "low": "Low",
            "volume": "Volume",
        }
        df = df.rename(columns=rename_map)
        df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]
        df = _normalize_ohlcv_dates(df)
    except Exception as e:
        logger.warning("mootdx OHLCV failed for %s: %s, trying sina HTTP fallback", code, e)
        # Fallback: Sina direct HTTP API
        try:
            df = _sina_kline_fallback(code)
            if df.empty:
                raise ValueError(f"No OHLCV data from sina for {code}")
        except Exception:
            # 弱网降级：两个源都挂但存在旧缓存时，宁可给略旧的数据也别硬失败
            if os.path.exists(cache_file):
                logger.warning(
                    "mootdx/sina OHLCV failed for %s, falling back to stale cache", code
                )
                data = pd.read_csv(cache_file, on_bad_lines="skip", encoding="utf-8")
                data = _normalize_ohlcv_dates(data)
                cutoff = pd.to_datetime(curr_date)
                return data[data["Date"] <= cutoff]
            raise ValueError(f"No OHLCV data from mootdx/sina for {code}")

    df, _ = _supplement_stale_ohlcv_with_sina(code, df, curr_date, start_date=None)

    # Cache to disk
    df.to_csv(cache_file, index=False, encoding="utf-8")

    # Filter by curr_date to prevent look-ahead bias
    cutoff = pd.to_datetime(curr_date)
    return df[df["Date"] <= cutoff]

