"""
A-Stock Data functions — extracted from stock_ui.py for unified app.
All functions are standalone, cache-enabled, and return clean data.
"""

import math
import re
import json
import urllib.request
from pathlib import Path
from collections import Counter

import requests
import pandas as pd
from mootdx.quotes import Quotes

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── 工具 ──────────────────────────────────────────────────

def normalize_code(raw: str) -> str:
    raw = raw.strip().upper()
    raw = raw.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    for prefix in ["SH", "SZ", "BJ"]:
        if raw.startswith(prefix):
            raw = raw[2:]
    return raw

# ── 行情层 ────────────────────────────────────────────────

def tencent_quote(codes: list[str]) -> dict:
    prefixed = []
    for c in codes:
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode("gbk")
    except Exception:
        return {}
    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name": vals[1],
            "price": float(vals[3]) if vals[3] else 0,
            "last_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
            "change_amt": float(vals[31]) if vals[31] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
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
        }
    return result

# ── 研报层 ────────────────────────────────────────────────

def ths_eps_forecast(code: str) -> pd.DataFrame:
    url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
    headers = {"User-Agent": UA, "Referer": "https://basic.10jqka.com.cn/"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "gbk"
        dfs = pd.read_html(r.text)
        for df in dfs:
            cols = [str(c) for c in df.columns]
            if any("每股收益" in c or "均值" in c for c in cols):
                return df
        return dfs[0] if dfs else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# ── 信号层 ────────────────────────────────────────────────

def ths_hot_reason(date_str: str | None = None) -> pd.DataFrame:
    from datetime import date
    if date_str is None:
        date_str = date.today().strftime("%Y-%m-%d")
    url = (
        f"http://zx.10jqka.com.cn/event/api/getharden/"
        f"date/{date_str}/orderby/date/orderway/desc/charset/GBK/"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if data.get("errocode", 0) != 0:
            return pd.DataFrame()
        rows = data.get("data") or []
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        rename_map = {
            "code": "代码", "name": "名称", "reason": "题材归因",
            "close": "收盘价", "zhangdie": "涨跌额", "zhangfu": "涨幅%",
            "huanshou": "换手率%", "chengjiaoe": "成交额", "market": "市场",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        return df
    except Exception:
        return pd.DataFrame()

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
        r = requests.get(url, headers=headers, timeout=10)
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
    p = Path.home() / ".tradingagents" / "cache" / "northbound_daily.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def hsgt_realtime() -> pd.DataFrame:
    url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
    try:
        r = requests.get(url, headers=HSGT_HEADERS, timeout=10)
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
    return Quotes.factory(market='std')

def get_kline_data(code: str, days: int = 60) -> pd.DataFrame:
    try:
        client = _tdx_client()
        klines = client.bars(symbol=code, category=4, offset=days)
        if klines is None or klines.empty:
            return pd.DataFrame()
        return klines
    except Exception:
        return pd.DataFrame()

def eastmoney_fund_flow_minute(code: str) -> list[dict]:
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {"secid": secid, "klt": 1, "fields1": "f1,f2,f3,f7",
              "fields2": "f51,f52,f53,f54,f55,f56,f57"}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
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

def industry_comparison(top_n: int = 20) -> dict:
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "100", "po": "1", "np": "1",
        "fltt": "2", "invt": "2", "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
    }
    headers = {"User-Agent": UA}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
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

def cls_telegraph(page_size: int = 30) -> list[dict]:
    url = "https://www.cls.cn/nodeapi/telegraphList"
    params = {"rn": str(page_size), "page": "1"}
    headers = {"User-Agent": UA, "Referer": "https://www.cls.cn/"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
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
        r = requests.get(url, params=params, headers=headers, timeout=15)
        text = r.text
        json_str = text[text.index("(") + 1 : text.rindex(")")]
        d = json.loads(json_str)
    except Exception:
        return []
    rows = []
    articles = d.get("result", {}).get("cmsArticleWebOld", {}).get("list", [])
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
