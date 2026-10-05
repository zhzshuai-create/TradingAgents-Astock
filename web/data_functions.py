"""
AStock Pro data functions — UI adapter layer.

数据实现全部委托给核心数据层 ``tradingagents.dataflows.a_stock``（单一真相源），
本模块只负责两件事：
1. 把核心层抛异常/返回原始结构的接口包装成看板需要的形状（空 DataFrame / dict / list）；
2. 用 ``@st.cache_data`` 提供看板用的短 TTL 缓存（缓存只存在于 UI 层，核心层保持纯净）。
"""

import math
import re
import json
import logging
import urllib.request
from pathlib import Path

import streamlit as st
import pandas as pd

from tradingagents.dataflows.a_stock import _common as _core
from tradingagents.dataflows.a_stock import signals as _signals

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── 工具 ──────────────────────────────────────────────────

def normalize_code(raw: str) -> str:
    """委托核心层实现（单一真相源）。"""
    return _core._normalize_ticker(raw)

# ── 行情层 ────────────────────────────────────────────────

@st.cache_data(ttl=10, show_spinner=False)
def tencent_quote(codes: list[str]) -> dict:
    """批量实时行情（腾讯 qt.gtimg.cn），失败返回 {}。"""
    try:
        return _core._tencent_quote(codes)
    except Exception as e:
        logger.warning("tencent_quote failed: %s", e, exc_info=True)
        return {}

# ── 研报层 ────────────────────────────────────────────────

@st.cache_data(ttl=14400, show_spinner=False)
def ths_eps_forecast(code: str) -> pd.DataFrame:
    """同花顺一致预期 EPS，失败返回空 DataFrame。"""
    try:
        return _core._ths_eps_forecast(code)
    except Exception as e:
        logger.warning("ths_eps_forecast failed: %s", e, exc_info=True)
        return pd.DataFrame()

# ── 信号层 ────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def ths_hot_reason(date_str: str | None = None) -> pd.DataFrame:
    """Return today's strong stocks with real price-change data.

    The 10jqka API returns only ticker-level metadata (id, name, code, reason).
    We enrich it with live quotes from Tencent to provide accurate 涨幅% etc.
    """
    from datetime import date
    if date_str is None:
        date_str = date.today().strftime("%Y-%m-%d")
    url = (
        f"http://zx.10jqka.com.cn/event/api/getharden/"
        f"date/{date_str}/orderby/date/orderway/desc/charset/GBK/"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0"}
    try:
        r = _core._requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if data.get("errocode", 0) != 0:
            return pd.DataFrame()
        rows = data.get("data") or []
        if not rows:
            return pd.DataFrame()

        # Build base DataFrame from API fields
        df = pd.DataFrame(rows)
        df = df.rename(columns={
            "code": "代码", "name": "名称", "reason": "题材归因", "market": "市场",
        })
        # Ensure required columns exist
        for col in ["代码", "名称", "题材归因"]:
            if col not in df.columns:
                df[col] = ""

        # Enrich with live quotes in one batch call
        codes = [normalize_code(str(c)) for c in df["代码"].tolist() if pd.notna(c)]
        quotes = tencent_quote(codes) if codes else {}

        enrich = {"涨幅%": [], "涨跌额": [], "收盘价": [], "换手率%": []}
        for _, row in df.iterrows():
            c = normalize_code(str(row.get("代码", "")))
            q = quotes.get(c, {})
            enrich["涨幅%"].append(q.get("change_pct", 0))
            enrich["涨跌额"].append(q.get("change_amt", 0))
            enrich["收盘价"].append(q.get("price", 0))
            enrich["换手率%"].append(q.get("turnover_pct", 0))

        for k, v in enrich.items():
            df[k] = v
        return df
    except Exception as e:
        logger.warning("ths_hot_reason failed: %s", e, exc_info=True)
        return pd.DataFrame()

@st.cache_data(ttl=86400, show_spinner=False)
def baidu_concept_blocks(code: str) -> dict:
    url = (
        f"https://finance.pae.baidu.com/api/getrelatedblock"
        f"?code={code}&market=ab&typeCode=all&finClientType=pc"
    )
    headers = {
        "User-Agent": UA,
        "Accept": "application/vnd.finance-web.v1+json",
        "Origin": "https://gushitong.baidu.com",
        "Referer": "https://gushitong.baidu.com/",
    }
    try:
        r = _core._requests.get(url, headers=headers, timeout=10)
        d = r.json()
        if str(d.get("ResultCode", -1)) != "0":
            return {"industry": [], "concept": [], "region": [], "concept_tags": []}
        result = {"industry": [], "concept": [], "region": [], "concept_tags": []}
        for block in d.get("Result", []):
            block_type = block.get("type", "")
            for item in block.get("list", []):
                entry = {
                    "name": item.get("name", ""),
                    "change_pct": item.get("increase", ""),
                    "desc": item.get("desc", ""),
                }
                if "行业" in block_type:
                    result["industry"].append(entry)
                elif "概念" in block_type:
                    result["concept"].append(entry)
                    result["concept_tags"].append(entry["name"])
                elif "地域" in block_type:
                    result["region"].append(entry)
        return result
    except Exception as e:
        logger.warning("baidu_concept_blocks failed: %s", e, exc_info=True)
        return {"industry": [], "concept": [], "region": [], "concept_tags": []}

# ── 北向资金 ──────────────────────────────────────────────

HSGT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0",
    "Host": "data.hexin.cn",
    "Referer": "https://data.hexin.cn/",
}

def _northbound_cache_path() -> Path:
    """北向日线缓存路径 — 与核心层共用同一份缓存文件。"""
    return Path(_signals._northbound_cache_path())

@st.cache_data(ttl=30, show_spinner=False)
def hsgt_realtime() -> pd.DataFrame:
    url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
    try:
        r = _core._requests.get(url, headers=HSGT_HEADERS, timeout=10)
        d = r.json()
        times = d.get("time", [])
        hgt = d.get("hgt", [])
        sgt = d.get("sgt", [])
        n = len(times)
        return pd.DataFrame({
            "time": times,
            "hgt_yi": hgt[:n] + [None] * (n - len(hgt)),
            "sgt_yi": sgt[:n] + [None] * (n - len(sgt)),
        })
    except Exception as e:
        logger.warning("hsgt_realtime failed: %s", e, exc_info=True)
        return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def load_northbound_history(n: int = 20) -> pd.DataFrame:
    path = _northbound_cache_path()
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
        return df.tail(n)
    except Exception as e:
        logger.warning("load_northbound_history failed: %s", e, exc_info=True)
        return pd.DataFrame()

# ── 资金流向 / K线 ───────────────────────────────────────

def _tdx_client():
    """复用核心层的健壮 mootdx 客户端（内置 TDX 服务器探测，规避 BESTIP 空串 bug）。"""
    return _core._get_mootdx_client()

@st.cache_data(ttl=300, show_spinner=False)
def _get_kline_full(code: str) -> pd.DataFrame:
    """一次性拉取日 K 供各周期切片复用（mootdx 5000 根 ≈ 上市以来全部）。

    mootdx（TCP 7709）不可达时静默返回空会导致看板 K 线全空，
    因此回落核心数据层 `_load_ohlcv_astock`（800 根，mootdx 失败时
    内部再走新浪 HTTP 兜底 + 本地 CSV 缓存），并把列名映射回看板
    schema（datetime/open/high/low/close/vol）。
    """
    try:
        client = _tdx_client()
        klines = client.bars(symbol=code, category=4, offset=5000)
        if klines is not None and not klines.empty:
            return klines
    except Exception as e:
        logger.warning("_get_kline_full failed: %s", e, exc_info=True)
        pass
    from datetime import datetime as _dt

    try:
        df = _core._load_ohlcv_astock(code, _dt.now().strftime("%Y-%m-%d"))
    except Exception as e:
        logger.warning("_get_kline_full failed: %s", e, exc_info=True)
        return pd.DataFrame()
    if df.empty:
        return df
    return df.rename(columns={
        "Date": "datetime", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "vol",
    })


@st.cache_data(ttl=300, show_spinner=False)
def get_kline_data(code: str, days: int = 60) -> pd.DataFrame:
    """按需切片：复用全量缓存，避免分时/近端/全历史各自触发一次 TCP 拉取。"""
    full = _get_kline_full(code)
    if full.empty:
        return full
    return full.tail(days)

@st.cache_data(ttl=30, show_spinner=False)
def get_minute_data(code: str, date_str: str | None = None) -> pd.DataFrame:
    """Fetch intraday 1‑minute data for *date_str*.

    Uses mootdx ``minutes()`` (historical minute data) which works at any time.
    If *date_str* is None, fetches the most recent trading day's data.
    """
    try:
        client = _tdx_client()
        if date_str is None:
            # Try today first, then fall back to yesterday
            from datetime import date, timedelta
            today = date.today().strftime("%Y%m%d")
            df = client.minutes(symbol=code, date=today)
            if df is None or df.empty:
                yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
                df = client.minutes(symbol=code, date=yesterday)
        else:
            # Convert "YYYY-MM-DD" -> "YYYYMMDD"
            clean_date = date_str.replace("-", "")
            df = client.minutes(symbol=code, date=clean_date)
        if df is None or df.empty:
            return pd.DataFrame()
        return df
    except Exception as e:
        logger.warning("get_minute_data failed: %s", e, exc_info=True)
        return pd.DataFrame()


def minute_timeline(date_str: str, n: int) -> pd.DatetimeIndex:
    """A 股分时时间轴：09:30–11:30 + 13:00–15:00 共 240 分钟，取前 n 个刻度。

    mootdx 历史分时只有 price/vol 两列、无时间戳（RangeIndex 0..239），旧单日
    视图把整数索引直接塞进 altair ``:T`` 导致 x 轴无意义——统一在这里构造
    规范刻度，今日/历史单日视图共用。n>240 时下午刻度顺延兜底；n<=0 返回空
    索引（负数不能交给切片，``[:n]`` 会从尾部裁）。
    """
    if n <= 0:
        return pd.DatetimeIndex([])
    day = pd.Timestamp(date_str).normalize()
    am = pd.date_range(day + pd.Timedelta(hours=9, minutes=30), periods=120, freq="min")
    pm = pd.date_range(day + pd.Timedelta(hours=13), periods=max(120, n), freq="min")
    return am.append(pm)[:n]


@st.cache_data(ttl=3600, show_spinner=False)
def get_minute_history(code: str, date_str: str) -> pd.DataFrame:
    """指定历史交易日的 1 分钟分时（mootdx），超出服务器保留期返回空 DataFrame。

    与 get_minute_data（今日/昨日自动回退，TTL 30s）不同：历史分时不可变，
    用长 TTL 缓存。date_str 接受 "YYYY-MM-DD" 或 "YYYYMMDD"。
    """
    try:
        client = _tdx_client()
        df = client.minutes(symbol=code, date=date_str.replace("-", ""))
        if df is None or df.empty:
            return pd.DataFrame()
        return df
    except Exception as e:
        logger.warning("get_minute_history(%s, %s) failed: %s", code, date_str, e, exc_info=True)
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _em_5min_bars(code: str, date_str: str) -> pd.DataFrame:
    """东财 5 分钟K线（klt=5，beg=end=当日）——历史分时取不到时的回退源。

    实测 push2his 的 5 分钟线只保留近约 31 个交易日（远端日期返回空），
    而 mootdx 分时保留期长达数年——本回退的真实角色是 TDX 服务器故障/
    个别日期缺失时的近端兜底。fqt=0 不复权，与 mootdx 日K口径一致。
    失败返回空 DataFrame。
    """
    clean = date_str.replace("-", "")
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {"secid": secid, "klt": "5", "fqt": "0", "beg": clean, "end": clean,
              "fields1": "f1,f2,f3,f4,f5,f6",
              "fields2": "f51,f52,f53,f54,f55,f56,f57"}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = _core._em_get(url, params=params, headers=headers, timeout=10)
        klines = (r.json().get("data") or {}).get("klines") or []
    except Exception as e:
        logger.warning("_em_5min_bars(%s, %s) failed: %s", code, date_str, e, exc_info=True)
        return pd.DataFrame()
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            rows.append({
                "datetime": pd.to_datetime(parts[0]),
                "open": float(parts[1]), "close": float(parts[2]),
                "high": float(parts[3]), "low": float(parts[4]), "vol": float(parts[5]),
            })
        except (ValueError, TypeError):
            logger.warning("_em_5min_bars(%s, %s): skip malformed kline %r", code, date_str, line)
            continue
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.set_index("datetime").assign(price=lambda d: d["close"])


def get_intraday_view(code: str, date_str: str) -> tuple[pd.DataFrame, str]:
    """指定交易日的日内行情数据，供"双击K线 → 单日详情"使用。返回 (df, kind)。

    kind="m1"：mootdx 历史分时（price/vol，已挂 minute_timeline 规范时间轴）；
    kind="m5"：分时超出保留期时回退的东财 5 分钟K线（datetime 索引）；
    两者皆空返回 (空 DataFrame, "")。本身不加缓存——两个内部数据源各自带长 TTL 缓存。
    """
    m1 = get_minute_history(code, date_str)
    if not m1.empty:
        # mootdx 列名存在版本差异（close/volume 别名），缺 price/vol 时就近映射
        for src, dst in (("close", "price"), ("volume", "vol")):
            if dst not in m1.columns and src in m1.columns:
                m1[dst] = m1[src]
        if {"price", "vol"}.issubset(m1.columns):
            m1 = m1.copy()
            m1.index = minute_timeline(date_str, len(m1))
            return m1[["price", "vol"]], "m1"
        logger.warning(
            "get_intraday_view(%s, %s): mootdx minutes unexpected columns %s",
            code, date_str, list(m1.columns),
        )
    m5 = _em_5min_bars(code, date_str)
    if not m5.empty:
        return m5, "m5"
    return pd.DataFrame(), ""

def eastmoney_fund_flow_minute(code: str) -> list[dict]:
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {"secid": secid, "klt": 1, "fields1": "f1,f2,f3,f7",
              "fields2": "f51,f52,f53,f54,f55,f56,f57"}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = _core._em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
    except Exception as e:
        logger.warning("eastmoney_fund_flow_minute failed: %s", e, exc_info=True)
        return []
    rows = []
    for line in d.get("data", {}).get("klines", []):
        parts = line.split(",")
        if len(parts) >= 6:
            rows.append({
                "time": parts[0],
                "main_net": float(parts[1]),
                "small_net": float(parts[2]),
                "mid_net": float(parts[3]),
                "large_net": float(parts[4]),
                "super_net": float(parts[5]),
            })
    return rows

@st.cache_data(ttl=300, show_spinner=False)
def industry_comparison(top_n: int = 20) -> dict:
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "100", "po": "1", "np": "1",
        "fltt": "2", "invt": "2", "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
    }
    headers = {"User-Agent": UA}
    try:
        r = _core._em_get(url, params=params, headers=headers, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", [])
        if not items:
            return {"top": [], "bottom": [], "total": 0}
        rows = []
        for i, item in enumerate(items):
            rows.append({
                "rank": i + 1,
                "name": item.get("f14", ""),
                "change_pct": item.get("f3", 0),
                "code": item.get("f12", ""),
                "up_count": item.get("f104", 0),
                "down_count": item.get("f105", 0),
                "leader": item.get("f140", ""),
                "leader_change": item.get("f136", 0),
            })
        return {"top": rows[:top_n], "bottom": rows[-top_n:], "total": len(rows)}
    except Exception as e:
        logger.warning("industry_comparison failed: %s", e, exc_info=True)
        return {"top": [], "bottom": [], "total": 0}

# ── 新闻层 ────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def cls_telegraph(page_size: int = 30) -> list[dict]:
    url = "https://www.cls.cn/nodeapi/telegraphList"
    params = {"rn": str(page_size), "page": "1"}
    headers = {"User-Agent": UA, "Referer": "https://www.cls.cn/"}
    try:
        r = _core._requests.get(url, params=params, headers=headers, timeout=10)
        d = r.json()
    except Exception as e:
        logger.warning("cls_telegraph failed: %s", e, exc_info=True)
        return []
    rows = []
    for item in d.get("data", {}).get("roll_data", []):
        rows.append({
            "title": item.get("title", "") or item.get("brief", ""),
            "content": item.get("content", "") or item.get("brief", ""),
            "time": item.get("ctime", ""),
        })
    return rows

@st.cache_data(ttl=300, show_spinner=False)
def eastmoney_stock_news(code: str, page_size: int = 20) -> list[dict]:
    cb = "jQuery_news"
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    inner = json.dumps({
        "uid": "", "keyword": code, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                  "pageIndex": 1, "pageSize": page_size, "preTag": "", "postTag": ""}},
    }, separators=(',', ':'))
    params = {"cb": cb, "param": inner}
    headers = {"User-Agent": UA, "Referer": "https://so.eastmoney.com/"}
    try:
        r = _core._em_get(url, params=params, headers=headers, timeout=15)
        text = r.text
        json_str = text[text.index("(") + 1 : text.rindex(")")]
        d = json.loads(json_str)
    except Exception as e:
        logger.warning("eastmoney_stock_news failed: %s", e, exc_info=True)
        return []
    rows = []
    result = d.get("result", {})
    if not isinstance(result, dict):
        return []
    cms = result.get("cmsArticleWebOld", {})
    if not isinstance(cms, dict):
        return []
    articles = cms.get("list", [])
    for a in articles:
        rows.append({
            "title": re.sub(r'<[^>]+>', '', a.get("title", "")),
            "content": re.sub(r'<[^>]+>', '', a.get("content", ""))[:200],
            "time": a.get("date", ""),
            "source": a.get("mediaName", ""),
            "url": a.get("url", ""),
        })
    return rows

# ── 估值公式 ──────────────────────────────────────────────

def forward_pe(price: float, eps_forecast: float) -> float:
    if eps_forecast <= 0:
        return float("inf")
    return price / eps_forecast

def calc_peg(pe: float, cagr: float) -> float:
    if cagr <= 0:
        return float("inf")
    return pe / (cagr * 100)

def pe_digestion(current_pe: float, cagr: float, target_pe: float = 30) -> float:
    if current_pe <= target_pe:
        return 0.0
    if cagr <= 0:
        return float("inf")
    return math.log(current_pe / target_pe) / math.log(1 + cagr)


# ── 大盘指数 ──────────────────────────────────────────────

@st.cache_data(ttl=10, show_spinner=False)
def index_spot() -> dict:
    """获取三大指数（上证/深证/创业板）实时行情（腾讯 qt.gtimg.cn）。

    返回 {"000001": {name, price, change_pct, change_amt}, ...}
    """
    result = {}
    try:
        url = "https://qt.gtimg.cn/q=sh000001,sz399001,sz399006"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode("gbk")
        order = [("000001", "上证指数"), ("399001", "深证成指"), ("399006", "创业板指")]
        for code, label in order:
            result[code] = {"name": label, "price": 0, "change_pct": 0, "change_amt": 0}
        for line in data.strip().split(";"):
            if not line.strip() or "=" not in line or '"' not in line:
                continue
            try:
                _, content = line.split("=", 1)
                vals = content.strip('";\n').split("~")
                if len(vals) < 33:
                    continue
                raw_code = vals[2]  # e.g. "000001" or "399001"
                if raw_code in result:
                    result[raw_code]["price"] = float(vals[3]) if vals[3] else 0
                    result[raw_code]["change_pct"] = float(vals[32]) if vals[32] else 0
                    result[raw_code]["change_amt"] = float(vals[31]) if vals[31] else 0
            except Exception as e:
                logger.warning("index_spot failed: %s", e, exc_info=True)
                continue
    except Exception as e:
        logger.warning("index_spot failed: %s", e, exc_info=True)
        pass

    return result
