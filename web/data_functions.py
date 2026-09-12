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
import urllib.request
from pathlib import Path

import streamlit as st
import pandas as pd

from tradingagents.dataflows.a_stock import _common as _core
from tradingagents.dataflows.a_stock import signals as _signals

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
    except Exception:
        return {}

# ── 研报层 ────────────────────────────────────────────────

@st.cache_data(ttl=14400, show_spinner=False)
def ths_eps_forecast(code: str) -> pd.DataFrame:
    """同花顺一致预期 EPS，失败返回空 DataFrame。"""
    try:
        return _core._ths_eps_forecast(code)
    except Exception:
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
    except Exception:
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
    except Exception:
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
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def load_northbound_history(n: int = 20) -> pd.DataFrame:
    path = _northbound_cache_path()
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
        return df.tail(n)
    except Exception:
        return pd.DataFrame()

# ── 资金流向 / K线 ───────────────────────────────────────

def _tdx_client():
    """复用核心层的健壮 mootdx 客户端（内置 TDX 服务器探测，规避 BESTIP 空串 bug）。"""
    return _core._get_mootdx_client()

@st.cache_data(ttl=300, show_spinner=False)
def get_kline_data(code: str, days: int = 60) -> pd.DataFrame:
    try:
        client = _tdx_client()
        klines = client.bars(symbol=code, category=4, offset=days)
        if klines is None or klines.empty:
            return pd.DataFrame()
        return klines
    except Exception:
        return pd.DataFrame()

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
    except Exception:
        return pd.DataFrame()

def eastmoney_fund_flow_minute(code: str) -> list[dict]:
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {"secid": secid, "klt": 1, "fields1": "f1,f2,f3,f7",
              "fields2": "f51,f52,f53,f54,f55,f56,f57"}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = _core._em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
    except Exception:
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
    except Exception:
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
    except Exception:
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
    except Exception:
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
            except Exception:
                continue
    except Exception:
        pass

    return result
