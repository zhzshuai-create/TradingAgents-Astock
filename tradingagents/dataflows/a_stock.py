"""A-stock (China mainland) data vendor for TradingAgents.

Bridges EP11's a-stock-data Skill (mootdx + Tencent Finance + akshare + 同花顺)
into TradingAgents' plugin architecture. 12 vendor methods implemented.

Data sources:
- mootdx (TCP 7709): OHLCV K-lines, financial snapshots, F10 text
- Tencent Finance (HTTP GBK): PE/PB/market cap/turnover
- akshare (Python): news, financial statements, stock info, consensus EPS
- 同花顺 (HTTP): hot stocks topic attribution, northbound capital flow
"""

from typing import Annotated
from datetime import datetime
from dateutil.relativedelta import relativedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
import os
import logging
import math
import urllib.request

import pandas as pd

from .utils import safe_ticker_component

logger = logging.getLogger(__name__)


def _fetch_with_timeout(fn, timeout=15, label=""):
    """Run fn in a thread; returns result or None on timeout/error."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout:
            logger.warning("%s timed out after %ds", label or fn.__name__, timeout)
            return None
        except Exception as e:
            logger.warning("%s failed: %s", label or fn.__name__, e)
            return None


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


_name_to_code_cache = None


def _load_name_to_code():
    """Lazy-load A-stock name->code mapping from akshare."""
    global _name_to_code_cache
    if _name_to_code_cache is None:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        _name_to_code_cache = dict(zip(df["name"].str.strip(), df["code"].str.strip()))
    return _name_to_code_cache


def _normalize_ticker(symbol: str) -> str:
    """Strip exchange prefix/suffix, return pure 6-digit code.

    Handles: '688017', 'SH688017', '688017.SH', 'sh688017'
    Also resolves company names like '绿的谐波' to codes.
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
    try:
        return safe_ticker_component(s)
    except ValueError:
        # Input may be a company name; try name->code lookup
        name_map = _load_name_to_code()
        code = name_map.get(symbol.strip())
        if code:
            return safe_ticker_component(code)
        # Also try case-insensitive match against Chinese names
        lower_map = {k.lower(): v for k, v in name_map.items()}
        code = lower_map.get(symbol.strip().lower())
        if code:
            return safe_ticker_component(code)
        raise


# ---------------------------------------------------------------------------
# mootdx client (singleton)
# ---------------------------------------------------------------------------

_mootdx_client = None


def _get_mootdx_client():
    """Lazy-init mootdx Quotes client (TCP connection, reusable)."""
    global _mootdx_client
    if _mootdx_client is None:
        from mootdx.quotes import Quotes

        _mootdx_client = Quotes.factory(market="std")
    return _mootdx_client


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
    resp = urllib.request.urlopen(req, timeout=10)
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
            "high": float(vals[33]) if vals[33] else 0,
            "low": float(vals[34]) if vals[34] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm": float(vals[39]) if vals[39] else 0,
            "mcap_yi": float(vals[44]) if vals[44] else 0,
            "float_mcap_yi": float(vals[45]) if vals[45] else 0,
            "pb": float(vals[46]) if vals[46] else 0,
            "limit_up": float(vals[47]) if vals[47] else 0,
            "limit_down": float(vals[48]) if vals[48] else 0,
            "pe_static": float(vals[52]) if vals[52] else 0,
        }
    return result


# ---------------------------------------------------------------------------
# OHLCV loading with cache (mootdx -> CSV)
# ---------------------------------------------------------------------------

def _load_ohlcv_astock(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV via mootdx, cache to CSV, filter by curr_date.

    Mirrors stockstats_utils.load_ohlcv but uses mootdx instead of yfinance.
    Returns DataFrame with columns: Date, Open, High, Low, Close, Volume
    """
    from .config import get_config

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
            data["Date"] = pd.to_datetime(data["Date"])
            cutoff = pd.to_datetime(curr_date)
            return data[data["Date"] <= cutoff]

    # Fetch from mootdx — 800 daily bars (~3 years of trading days)
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
    df["Date"] = pd.to_datetime(df["Date"])

    # Cache to disk
    df.to_csv(cache_file, index=False, encoding="utf-8")

    # Filter by curr_date to prevent look-ahead bias
    cutoff = pd.to_datetime(curr_date)
    return df[df["Date"] <= cutoff]


# ===========================================================================
# 9 Vendor Methods (matching interface.py VENDOR_METHODS signatures)
# ===========================================================================


# ---- 1. get_stock_data ----


def get_stock_data(
    symbol: Annotated[str, "A-stock code (e.g. 688017, SH688017)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Get OHLCV stock price data via mootdx."""
    code = _normalize_ticker(symbol)

    try:
        client = _get_mootdx_client()
        df = client.bars(symbol=code, category=4, offset=800)

        if df is None or df.empty:
            return (
                f"No data found for A-stock '{code}' "
                f"between {start_date} and {end_date}"
            )

        # Drop duplicate datetime column + extra columns before reset_index
        df = df.drop(
            columns=["datetime", "year", "month", "day", "hour", "minute"],
            errors="ignore",
        )
        df = df.reset_index()  # index 'datetime' → column 'datetime'
        df = df.rename(
            columns={
                "datetime": "Date",
                "open": "Open",
                "close": "Close",
                "high": "High",
                "low": "Low",
                "volume": "Volume",
                "amount": "Amount",
            }
        )

        # Filter by date range
        df["Date"] = pd.to_datetime(df["Date"])
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        df = df[(df["Date"] >= start_dt) & (df["Date"] <= end_dt)]

        if df.empty:
            return (
                f"No data found for A-stock '{code}' "
                f"between {start_date} and {end_date}"
            )

        for col in ["Open", "High", "Low", "Close"]:
            if col in df.columns:
                df[col] = df[col].round(2)

        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        csv_out = df[["Date", "Open", "High", "Low", "Close", "Volume"]].to_csv(
            index=False
        )

        header = f"# Stock data for {code} (A-stock) from {start_date} to {end_date}\n"
        header += f"# Total records: {len(df)}\n"
        header += "# Data source: mootdx (TCP)\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_out

    except Exception as e:
        return f"Error retrieving A-stock data for {code}: {str(e)}"


# ---- 2. get_indicators ----

# Supported technical indicators with descriptions
_INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50 SMA: Medium-term trend indicator.",
    "close_200_sma": "200 SMA: Long-term trend benchmark.",
    "close_10_ema": "10 EMA: Responsive short-term average.",
    "macd": "MACD: Momentum via EMA differences.",
    "macds": "MACD Signal: EMA smoothing of MACD line.",
    "macdh": "MACD Histogram: Gap between MACD and signal.",
    "rsi": "RSI: Momentum overbought/oversold indicator (70/30 thresholds).",
    "boll": "Bollinger Middle: 20 SMA basis for Bollinger Bands.",
    "boll_ub": "Bollinger Upper Band: 2 std devs above middle.",
    "boll_lb": "Bollinger Lower Band: 2 std devs below middle.",
    "atr": "ATR: Average True Range volatility measure.",
    "vwma": "VWMA: Volume-weighted moving average.",
    "mfi": "MFI: Money Flow Index (volume + price momentum).",
}


def get_indicators(
    symbol: Annotated[str, "A-stock code"],
    indicator: Annotated[
        str, "technical indicator (e.g. rsi, macd, close_50_sma)"
    ],
    curr_date: Annotated[str, "Current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Get technical indicators using stockstats on mootdx OHLCV data."""
    from stockstats import wrap

    code = _normalize_ticker(symbol)

    if indicator not in _INDICATOR_DESCRIPTIONS:
        raise ValueError(
            f"Indicator {indicator} not supported. "
            f"Choose from: {list(_INDICATOR_DESCRIPTIONS.keys())}"
        )

    try:
        data = _load_ohlcv_astock(code, curr_date)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

        # Trigger stockstats calculation
        df[indicator]

        # Build date -> value lookup
        ind_dict = {}
        for _, row in df.iterrows():
            d = row["Date"]
            v = row[indicator]
            ind_dict[d] = "N/A" if pd.isna(v) else str(round(float(v), 4))

        # Generate output for look_back window
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        before = curr_dt - relativedelta(days=look_back_days)

        lines = []
        dt = curr_dt
        while dt >= before:
            ds = dt.strftime("%Y-%m-%d")
            val = ind_dict.get(ds, "N/A: Not a trading day (weekend or holiday)")
            lines.append(f"{ds}: {val}")
            dt -= relativedelta(days=1)

        result = (
            f"## {indicator} values for {code} "
            f"from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
            + "\n".join(lines)
            + "\n\n"
            + _INDICATOR_DESCRIPTIONS.get(indicator, "")
        )
        return result

    except Exception as e:
        return f"Error calculating {indicator} for {code}: {str(e)}"


# ---- 3. get_fundamentals ----


def get_fundamentals(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Get company fundamentals from Tencent + mootdx + akshare."""
    code = _normalize_ticker(ticker)

    try:
        lines = []

        # --- Tencent: real-time valuation ---
        try:
            tq = _tencent_quote([code])
            if code in tq:
                q = tq[code]
                lines.extend(
                    [
                        f"Name: {q['name']}",
                        f"Price: {q['price']}",
                        f"PE (TTM): {q['pe_ttm']}",
                        f"PE (Static): {q['pe_static']}",
                        f"PB: {q['pb']}",
                        f"Market Cap (100M CNY): {q['mcap_yi']}",
                        f"Float Market Cap (100M CNY): {q['float_mcap_yi']}",
                        f"Turnover Rate: {q['turnover_pct']}%",
                        f"Change: {q['change_pct']}%",
                        f"Limit Up: {q['limit_up']}",
                        f"Limit Down: {q['limit_down']}",
                    ]
                )
        except Exception as e:
            logger.warning("Tencent quote failed for %s: %s", code, e)

        # --- mootdx: financial snapshot (quarterly) ---
        try:
            client = _get_mootdx_client()
            fin = client.finance(symbol=code)
            if fin is not None and not (
                isinstance(fin, pd.DataFrame) and fin.empty
            ):
                row = fin.iloc[0] if isinstance(fin, pd.DataFrame) else fin
                field_map = {
                    "eps": "EPS (Quarterly)",
                    "bvps": "Book Value Per Share",
                    "roe": "ROE (%)",
                    "profit": "Net Profit",
                    "income": "Revenue",
                    "liutongguben": "Float Shares",
                    "zongguben": "Total Shares",
                }
                idx = row.index if hasattr(row, "index") else []
                for field, label in field_map.items():
                    if field in idx:
                        val = row[field]
                        if val is not None and str(val) != "nan":
                            lines.append(f"{label}: {val}")
        except Exception as e:
            logger.warning("mootdx finance failed for %s: %s", code, e)

        # --- akshare: basic stock info ---
        try:
            import akshare as ak

            info_df = ak.stock_individual_info_em(symbol=code)
            if info_df is not None and not info_df.empty:
                for _, row in info_df.iterrows():
                    item = str(row.get("item", ""))
                    value = str(row.get("value", ""))
                    if item and value and value != "nan":
                        lines.append(f"{item}: {value}")
        except Exception as e:
            logger.warning("akshare stock_individual_info_em failed for %s: %s", code, e)

        # --- akshare: consensus EPS forecast (同花顺) ---
        try:
            import akshare as ak

            forecast_df = ak.stock_profit_forecast_ths(
                symbol=code, indicator="预测年报每股收益"
            )
            if forecast_df is not None and not forecast_df.empty:
                lines.append("\n--- Consensus EPS Forecast (同花顺) ---")
                eps_by_year = {}
                for _, row in forecast_df.iterrows():
                    year = str(row.get("年度", ""))
                    mean_eps = float(row.get("均值", 0))
                    count = int(row.get("预测机构数", 0))
                    min_eps = row.get("最小值", "N/A")
                    max_eps = row.get("最大值", "N/A")
                    lines.append(
                        f"FY{year}: EPS={mean_eps} "
                        f"(range {min_eps}~{max_eps}, {count} analysts)"
                    )
                    if count < 3:
                        lines.append(f"  Warning: low coverage (<3 analysts)")
                    eps_by_year[year] = mean_eps

                # Forward PE / PEG / PE digestion
                try:
                    tq = _tencent_quote([code])
                    if code in tq:
                        price = tq[code]["price"]
                        years_sorted = sorted(eps_by_year.keys())
                        if years_sorted and eps_by_year.get(years_sorted[0], 0) > 0:
                            eps_cur = eps_by_year[years_sorted[0]]
                            fwd_pe = price / eps_cur
                            lines.append(
                                f"\nForward PE (FY{years_sorted[0]}): "
                                f"{fwd_pe:.1f}x (price={price}, EPS={eps_cur})"
                            )
                            if (
                                len(years_sorted) >= 2
                                and eps_by_year.get(years_sorted[1], 0) > 0
                            ):
                                eps_next = eps_by_year[years_sorted[1]]
                                cagr = eps_next / eps_cur - 1
                                if cagr > 0:
                                    peg = fwd_pe / (cagr * 100)
                                    lines.append(
                                        f"PEG: {peg:.2f} "
                                        f"(EPS CAGR={cagr * 100:.0f}%)"
                                    )
                                    if fwd_pe > 30:
                                        digest = math.log(fwd_pe / 30) / math.log(
                                            1 + cagr
                                        )
                                        lines.append(
                                            f"PE Digestion to 30x: {digest:.1f} years"
                                        )
                                    else:
                                        lines.append("PE already below 30x target")
                                else:
                                    lines.append(
                                        f"EPS declining ({cagr * 100:.0f}%), "
                                        f"PEG not applicable"
                                    )
                except Exception as e:
                    logger.warning("Forward PE calc failed for %s: %s", code, e)
        except Exception as e:
            logger.warning("Consensus EPS forecast failed for %s: %s", code, e)

        if not lines:
            return f"No fundamentals data found for A-stock '{code}'"

        header = f"# Company Fundamentals for {code} (A-stock)\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + "\n".join(lines)

    except Exception as e:
        return f"Error retrieving fundamentals for {code}: {str(e)}"


# ---- 4. get_balance_sheet ----


def _sina_stock_code(code: str) -> str:
    """Pure 6-digit code → sina format (sh688017 / sz000001 / bj832000)."""
    return f"{_get_prefix(code)}{code}"


def _get_financial_report_sina(
    code: str, report_type: str, freq: str, curr_date: str = None,
) -> pd.DataFrame:
    """Shared helper: fetch financial report via akshare sina source.

    report_type: '资产负债表' | '利润表' | '现金流量表'
    """
    import akshare as ak

    sina_code = _sina_stock_code(code)
    df = ak.stock_financial_report_sina(stock=sina_code, symbol=report_type)

    if df is None or df.empty:
        return pd.DataFrame()

    # Filter by curr_date
    if curr_date and "报告日" in df.columns:
        df["报告日"] = pd.to_datetime(df["报告日"], errors="coerce")
        cutoff = pd.to_datetime(curr_date)
        df = df[df["报告日"] <= cutoff]

    # Filter by frequency (annual = month 12 reports only)
    if freq.lower() == "annual" and "报告日" in df.columns:
        months = pd.to_datetime(df["报告日"], errors="coerce").dt.month
        df = df[months == 12]

    return df.head(8)


def get_balance_sheet(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get balance sheet via akshare (sina source)."""
    code = _normalize_ticker(ticker)

    try:
        df = _get_financial_report_sina(code, "资产负债表", freq, curr_date)

        if df.empty:
            return f"No balance sheet data found for A-stock '{code}'"

        csv_string = df.to_csv(index=False)

        header = f"# Balance Sheet for {code} (A-stock, {freq})\n"
        header += "# Data source: akshare (sina)\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        return f"Error retrieving balance sheet for {code}: {str(e)}"


# ---- 5. get_cashflow ----


def get_cashflow(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get cash flow statement via akshare (sina source)."""
    code = _normalize_ticker(ticker)

    try:
        df = _get_financial_report_sina(code, "现金流量表", freq, curr_date)

        if df.empty:
            return f"No cash flow data found for A-stock '{code}'"

        csv_string = df.to_csv(index=False)

        header = f"# Cash Flow for {code} (A-stock, {freq})\n"
        header += "# Data source: akshare (sina)\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        return f"Error retrieving cash flow for {code}: {str(e)}"


# ---- 6. get_income_statement ----


def get_income_statement(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get income statement via akshare (sina source)."""
    code = _normalize_ticker(ticker)

    try:
        df = _get_financial_report_sina(code, "利润表", freq, curr_date)

        if df.empty:
            return f"No income statement data found for A-stock '{code}'"

        csv_string = df.to_csv(index=False)

        header = f"# Income Statement for {code} (A-stock, {freq})\n"
        header += "# Data source: akshare (sina)\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        return f"Error retrieving income statement for {code}: {str(e)}"


# ---- 7. get_news ----


def get_news(
    ticker: Annotated[str, "A-stock code or company name"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Get stock-specific news via akshare (eastmoney source)."""
    import akshare as ak

    try:
        code = _normalize_ticker(ticker)
    except ValueError:
        # Not a valid stock code; treat input as company name or search keyword
        code = None

    try:
        if code:
            fn = lambda: ak.stock_news_em(symbol=code)
        else:
            fn = lambda: ak.stock_news_em(symbol=ticker.strip())
        df = _fetch_with_timeout(fn, timeout=15, label=f"stock_news_em({ticker})")
        if df is None:
            return f"News API timed out for '{ticker}'. 请检查网络连接或稍后重试。"

        if df is None or df.empty:
            return f"No news found for '{ticker}'"

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        news_str = ""
        count = 0

        for _, row in df.iterrows():
            title = str(row.get("新闻标题", row.get("title", "")))
            content = str(row.get("新闻内容", row.get("content", "")))
            pub_time = str(row.get("发布时间", row.get("datetime", "")))
            source = str(row.get("文章来源", row.get("source", "Unknown")))
            link = str(row.get("新闻链接", row.get("url", "")))

            # Date filter
            try:
                pub_dt = datetime.strptime(pub_time[:10], "%Y-%m-%d")
                if pub_dt < start_dt or pub_dt > end_dt:
                    continue
            except (ValueError, IndexError):
                pass  # Include if date can't be parsed

            news_str += f"### {title} (source: {source})\n"
            if content:
                snippet = (
                    content[:300] + "..." if len(content) > 300 else content
                )
                news_str += f"{snippet}\n"
            if link and link != "nan":
                news_str += f"Link: {link}\n"
            news_str += "\n"
            count += 1

        if count == 0:
            return (
                f"No news found for A-stock '{code}' "
                f"between {start_date} and {end_date}"
            )

        return (
            f"## {code} (A-stock) News, from {start_date} to {end_date}:\n\n"
            + news_str
        )

    except Exception as e:
        return f"Error fetching news for A-stock {code}: {str(e)}"


# ---- 8. get_global_news ----


def get_global_news(
    curr_date: Annotated[str, "Current date yyyy-mm-dd"],
    look_back_days: Annotated[int, "Days to look back"] = 7,
    limit: Annotated[int, "Max articles"] = 10,
) -> str:
    """Get China/global financial news via akshare (CLS + eastmoney)."""
    import akshare as ak

    start_dt = datetime.strptime(curr_date, "%Y-%m-%d") - relativedelta(
        days=look_back_days
    )
    start_date = start_dt.strftime("%Y-%m-%d")

    all_news: list[dict] = []

    # Source 1: CLS wire (财联社快讯)
    try:
        df_cls = _fetch_with_timeout(ak.stock_info_global_cls, timeout=10, label="CLS global news")
        if df_cls is not None and not df_cls.empty:
            for _, row in df_cls.head(limit).iterrows():
                title = str(row.get("标题", row.get("title", "")))
                content = str(row.get("内容", row.get("content", "")))
                pub_time = str(row.get("发布时间", row.get("datetime", "")))
                all_news.append(
                    {
                        "title": title,
                        "content": content,
                        "time": pub_time,
                        "source": "CLS Wire",
                    }
                )
    except Exception as e:
        logger.warning("CLS news fetch failed: %s", e)

    # Source 2: Eastmoney global (东财全球资讯)
    try:
        df_em = _fetch_with_timeout(ak.stock_info_global_em, timeout=10, label="EM")
        if df_em is not None and not df_em.empty:
            for _, row in df_em.head(limit).iterrows():
                title = str(row.get("标题", row.get("title", "")))
                summary = str(row.get("摘要", row.get("summary", "")))
                pub_time = str(row.get("发布时间", row.get("datetime", "")))
                all_news.append(
                    {
                        "title": title,
                        "content": summary,
                        "time": pub_time,
                        "source": "Eastmoney Global",
                    }
                )
    except Exception as e:
        logger.warning("Eastmoney global news fetch failed: %s", e)

    if not all_news:
        return f"No global news found for {curr_date}"

    # Deduplicate by title
    seen: set[str] = set()
    unique: list[dict] = []
    for n in all_news:
        if n["title"] not in seen:
            seen.add(n["title"])
            unique.append(n)

    news_str = ""
    for n in unique[:limit]:
        news_str += f"### {n['title']} (source: {n['source']})\n"
        if n.get("content"):
            snippet = (
                n["content"][:300] + "..."
                if len(n["content"]) > 300
                else n["content"]
            )
            news_str += f"{snippet}\n"
        news_str += "\n"

    return (
        f"## China & Global Market News, from {start_date} to {curr_date}:\n\n"
        + news_str
    )


# ---- 9. get_insider_transactions ----


def get_insider_transactions(
    ticker: Annotated[str, "A-stock code"],
) -> str:
    """Get shareholder/insider activity via mootdx F10.

    Note: A-stock insider transaction data differs from US markets.
    Uses mootdx F10 shareholder research as the closest equivalent.
    """
    code = _normalize_ticker(ticker)

    try:
        client = _get_mootdx_client()
        text = client.F10(symbol=code, name="股东研究")

        if not text or not text.strip():
            return f"No insider/shareholder data found for A-stock '{code}'"

        header = f"# Shareholder Research for {code} (A-stock)\n"
        header += "# Note: A-stock equivalent of insider transactions\n"
        header += "# Data source: mootdx F10\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        import re

        sec4_hits = list(re.finditer(r"\r?\n【4\.股东变化】\r?\n", text))
        if sec4_hits:
            sec4_pos = sec4_hits[-1].start()
            before_sec4 = text[:sec4_pos]
            sec4_text = text[sec4_pos:]
            cut_at = 2000
            if len(sec4_text) > cut_at:
                sec4_text = (
                    sec4_text[:cut_at]
                    + "\n\n(... older shareholder history omitted, "
                    f"{len(text) - sec4_pos - cut_at} chars truncated ...)"
                )
            text = before_sec4 + sec4_text

        return header + text

    except Exception as e:
        return f"Error retrieving insider/shareholder data for {code}: {str(e)}"


# ---- 10. get_profit_forecast ----


def get_profit_forecast(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "current date (unused, for interface compat)"] = None,
) -> str:
    """Get consensus EPS forecasts with forward valuation (akshare → 同花顺)."""
    import akshare as ak

    code = _normalize_ticker(ticker)

    try:
        df = ak.stock_profit_forecast_ths(
            symbol=code, indicator="预测年报每股收益"
        )

        if df is None or df.empty:
            return f"No analyst coverage found for A-stock '{code}'"

        lines = [
            f"# Consensus EPS Forecast for {code} (A-stock)",
            f"# Source: 同花顺 analyst consensus",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        eps_by_year = {}
        for _, row in df.iterrows():
            year = str(row.get("年度", ""))
            count = int(row.get("预测机构数", 0))
            mean_eps = float(row.get("均值", 0))
            min_eps = row.get("最小值", "N/A")
            max_eps = row.get("最大值", "N/A")
            industry_avg = row.get("行业平均数", "N/A")
            lines.append(
                f"FY{year}: EPS={mean_eps} (range {min_eps}~{max_eps}), "
                f"analysts={count}, industry_avg={industry_avg}"
            )
            if count < 3:
                lines.append("  Warning: low coverage (<3 analysts)")
            eps_by_year[year] = mean_eps

        # Forward valuation
        try:
            tq = _tencent_quote([code])
            if code in tq:
                price = tq[code]["price"]
                pe_ttm = tq[code]["pe_ttm"]
                lines.append(f"\nCurrent: price={price}, PE(TTM)={pe_ttm}")

                years_sorted = sorted(eps_by_year.keys())
                if years_sorted and eps_by_year.get(years_sorted[0], 0) > 0:
                    eps_cur = eps_by_year[years_sorted[0]]
                    fwd_pe = price / eps_cur
                    lines.append(
                        f"Forward PE (FY{years_sorted[0]}): {fwd_pe:.1f}x"
                    )
                    if (
                        len(years_sorted) >= 2
                        and eps_by_year.get(years_sorted[1], 0) > 0
                    ):
                        eps_next = eps_by_year[years_sorted[1]]
                        cagr = eps_next / eps_cur - 1
                        if cagr > 0:
                            peg = fwd_pe / (cagr * 100)
                            lines.append(
                                f"PEG: {peg:.2f} (CAGR={cagr * 100:.0f}%)"
                            )
                            if fwd_pe > 30:
                                digest = math.log(fwd_pe / 30) / math.log(
                                    1 + cagr
                                )
                                lines.append(
                                    f"PE Digestion to 30x: {digest:.1f} years"
                                )
                        else:
                            lines.append(
                                f"EPS declining ({cagr * 100:.0f}%), "
                                f"PEG not applicable"
                            )
        except Exception as e:
            logger.warning("Forward PE calc failed for %s: %s", code, e)

        return "\n".join(lines)

    except Exception as e:
        return f"Error retrieving profit forecast for {code}: {str(e)}"


# ---- 11. get_hot_stocks ----


def get_hot_stocks(
    curr_date: Annotated[str, "Date YYYY-MM-DD, empty string for today"] = "",
) -> str:
    """Get strong stocks with topic attribution from 同花顺 editorial team.

    Returns stocks that hit limit-up with human-curated reason tags
    explaining WHY they surged (e.g. '算力租赁+AI政务').
    """
    import requests

    if not curr_date or curr_date.strip() == "":
        curr_date = datetime.now().strftime("%Y-%m-%d")

    try:
        url = (
            f"http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{curr_date}/orderby/date/orderway/desc/charset/GBK/"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "Chrome/117.0.0.0 Safari/537.36"
            )
        }
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()

        if data.get("errocode", 0) != 0:
            return f"同花顺 API error: {data.get('errormsg', 'unknown')}"

        rows = data.get("data") or []
        if not rows:
            return (
                f"No hot stocks data for {curr_date} "
                f"(may be non-trading day or data not yet available)"
            )

        lines = [
            f"# Hot Stocks with Topic Attribution ({curr_date})",
            f"# Source: 同花顺 editorial (human-curated reason tags)",
            f"# Total: {len(rows)} stocks",
            "",
        ]

        from collections import Counter

        all_tags: list[str] = []

        for row in rows:
            code = row.get("code", "")
            name = row.get("name", "")
            reason = row.get("reason", "")
            zhangfu = row.get("zhangfu", "")
            huanshou = row.get("huanshou", "")
            chengjiaoe = row.get("chengjiaoe", "")
            dde = row.get("ddejingliang", "")

            lines.append(
                f"{code} {name}: +{zhangfu}% "
                f"换手{huanshou}% 成交额{chengjiaoe} "
                f"大单净量{dde} | {reason}"
            )

            if reason:
                tags = [t.strip() for t in str(reason).split("+") if t.strip()]
                all_tags.extend(tags)

        if all_tags:
            cnt = Counter(all_tags)
            lines.append(f"\n## Theme Frequency (top 15)")
            for tag, n in cnt.most_common(15):
                lines.append(f"  {tag}: {n} stocks")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching hot stocks for {curr_date}: {str(e)}"


# ---- 12. get_northbound_flow ----


def _northbound_cache_path() -> str:
    """Path to local CSV cache for northbound daily close snapshots."""
    from .config import get_config

    config = get_config()
    cache_dir = config.get(
        "data_cache_dir", os.path.expanduser("~/.tradingagents/cache")
    )
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "northbound_daily.csv")


def _save_northbound_snapshot(date_str: str, hgt: float, sgt: float) -> None:
    """Append today's northbound close to local CSV cache (dedup by date)."""
    import csv

    path = _northbound_cache_path()
    existing: dict[str, tuple[str, str]] = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) >= 3:
                    existing[row[0]] = (row[1], row[2])
    existing[date_str] = (f"{hgt:.2f}", f"{sgt:.2f}")
    sorted_dates = sorted(existing.keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "hgt", "sgt"])
        for d in sorted_dates:
            writer.writerow([d, existing[d][0], existing[d][1]])


def _load_northbound_history(n: int = 20) -> list[tuple[str, float, float]]:
    """Load last N days of northbound close data from local cache."""
    import csv

    path = _northbound_cache_path()
    if not os.path.exists(path):
        return []
    rows: list[tuple[str, float, float]] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 3:
                try:
                    rows.append((row[0], float(row[1]), float(row[2])))
                except ValueError:
                    continue
    return rows[-n:]


def get_northbound_flow(
    curr_date: Annotated[str, "Date YYYY-MM-DD"],
    include_history: Annotated[
        bool, "Include historical daily data (last 20 trading days)"
    ] = False,
) -> str:
    """Get northbound capital flow (沪深股通) from 同花顺 hsgtApi.

    Realtime: minute-level cumulative net buying for HGT(沪股通) + SGT(深股通).
    History: self-cached daily close snapshots (upstream APIs stopped updating
    northbound history since 2024-08).
    """
    import requests

    hsgt_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "Chrome/117.0.0.0 Safari/537.36"
        ),
        "Host": "data.hexin.cn",
        "Referer": "https://data.hexin.cn/",
    }

    lines = [
        f"# Northbound Capital Flow ({curr_date})",
        "# Source: 同花顺 hsgtApi (沪深股通) + local cache",
        "",
    ]

    hgt_close = 0.0
    sgt_close = 0.0
    got_realtime = False

    try:
        url_rt = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        r = requests.get(url_rt, headers=hsgt_headers, timeout=10)
        d = r.json()

        times = d.get("time", [])
        hgt = d.get("hgt", [])
        sgt = d.get("sgt", [])

        if times:
            lines.append("## Realtime (cumulative net buying, 亿元)")
            n = len(times)
            start_idx = max(0, n - 10)
            for i in range(start_idx, n):
                t = times[i]
                h = hgt[i] if i < len(hgt) else "N/A"
                s = sgt[i] if i < len(sgt) else "N/A"
                lines.append(f"  {t}: HGT={h} SGT={s}")

            hgt_close = float(hgt[-1]) if hgt else 0
            sgt_close = float(sgt[-1]) if sgt else 0
            total = hgt_close + sgt_close
            lines.append(
                f"\nClose: HGT(沪股通)={hgt_close:.2f}亿 "
                f"SGT(深股通)={sgt_close:.2f}亿 "
                f"Total={total:.2f}亿"
            )
            if total > 0:
                lines.append("Signal: Net northbound INFLOW (bullish)")
            elif total < 0:
                lines.append("Signal: Net northbound OUTFLOW (bearish)")
            got_realtime = True
        else:
            lines.append("No realtime data (non-trading hours or holiday)")

        if got_realtime:
            today_str = datetime.now().strftime("%Y-%m-%d")
            _save_northbound_snapshot(today_str, hgt_close, sgt_close)

        if include_history:
            history = _load_northbound_history(20)
            if history:
                lines.append("\n## Historical Daily Close (local cache, 亿元)")
                lines.append("Date       | HGT(沪股通) | SGT(深股通) | Total")
                for date, h, s in history:
                    lines.append(f"  {date}: HGT={h:.2f} SGT={s:.2f} Total={h + s:.2f}")
                avg_total = sum(h + s for _, h, s in history) / len(history)
                lines.append(
                    f"\n{len(history)}-day avg net flow: {avg_total:.2f}亿"
                )
                if got_realtime:
                    today_total = hgt_close + sgt_close
                    diff = today_total - avg_total
                    lines.append(
                        f"Today vs avg: {'+' if diff >= 0 else ''}{diff:.2f}亿 "
                        f"({'above' if diff >= 0 else 'below'} average)"
                    )
            else:
                lines.append(
                    "\n## Historical Daily: No cached data yet. "
                    "History accumulates automatically with each call."
                )

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching northbound flow: {str(e)}"


# ---------------------------------------------------------------------------
# Baidu PAE (百度股市通) helpers
# ---------------------------------------------------------------------------

_BAIDU_PAE_HEADERS = {
    "Host": "finance.pae.baidu.com",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) "
        "Gecko/20100101 Firefox/110.0"
    ),
    "Accept": "application/vnd.finance-web.v1+json",
    "Origin": "https://gushitong.baidu.com",
    "Referer": "https://gushitong.baidu.com/",
}


# ---- 13. get_concept_blocks ----


def get_concept_blocks(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
) -> str:
    """Get concept/sector/region blocks that a stock belongs to (百度股市通).

    Returns industry classification (申万), concept themes, and region.
    Each block includes current day's change percentage.
    """
    import requests

    code = _normalize_ticker(ticker)

    try:
        url = (
            "https://finance.pae.baidu.com/api/getrelatedblock"
            f'?stock=[{{"code":"{code}","market":"ab","type":"stock"}}]'
            "&finClientType=pc"
        )
        r = requests.get(url, headers=_BAIDU_PAE_HEADERS, timeout=10)
        d = r.json()

        if str(d.get("ResultCode", -1)) != "0":
            return (
                f"Baidu PAE error: ResultCode={d.get('ResultCode')} "
                f"{d.get('ResultMsg', '')}"
            )

        result = d.get("Result", {})
        categories = result.get(code, [])
        if not categories:
            return f"No concept/block data for {code}"

        lines = [
            f"# Concept & Sector Blocks for {code} (A-stock)",
            f"# Source: 百度股市通 (Baidu PAE)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        concept_names: list[str] = []

        for cat in categories:
            cat_name = cat.get("name", "")
            items = cat.get("list", [])
            if not items:
                continue
            lines.append(f"## {cat_name}")
            for item in items:
                name = item.get("name", "")
                ratio = item.get("ratio", "")
                desc = item.get("describe", "")
                suffix = f" ({desc})" if desc else ""
                lines.append(f"  {name}{suffix}: {ratio}")
                if cat_name == "概念":
                    concept_names.append(name)

        if concept_names:
            lines.append(f"\nConcept tags: {' / '.join(concept_names)}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching concept blocks for {code}: {str(e)}"


# ---- 14. get_fund_flow ----


def get_fund_flow(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "Date YYYY-MM-DD"],
    include_history: Annotated[
        bool, "Include historical daily fund flow (last 20 days)"
    ] = True,
) -> str:
    """Get individual stock fund flow from 百度股市通.

    Realtime: minute-level main force vs retail investor flow.
    History: daily super/large/medium/small order net inflow for 20 days.
    """
    import requests

    code = _normalize_ticker(ticker)
    lines = [
        f"# Fund Flow for {code} (A-stock)",
        f"# Source: 百度股市通 (Baidu PAE)",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    try:
        # Realtime minute-level fund flow
        url_rt = (
            "https://finance.pae.baidu.com/vapi/v1/fundflow"
            f"?finance_type=stock&fund_flow_type=&type=stock"
            f"&market=ab&code={code}&belongs=stocklevelone"
            "&finClientType=pc"
        )
        r = requests.get(url_rt, headers=_BAIDU_PAE_HEADERS, timeout=10)
        d = r.json()

        if str(d.get("ResultCode", -1)) == "0":
            content = d.get("Result", {}).get("content", {})
            ff = content.get("fundFlowMinute", {})
            data_str = ff.get("data", "")
            rows = data_str.split(";") if data_str else []

            if rows:
                lines.append(
                    "## Realtime Minute Flow "
                    "(mainForce vs retailInvestor, 万元)"
                )
                for row in rows[-10:]:
                    parts = row.split(",")
                    if len(parts) >= 8:
                        lines.append(
                            f"  {parts[0]}: "
                            f"主力={parts[2]} 散户={parts[3]} "
                            f"超大单={parts[4]} 大单={parts[5]} "
                            f"price={parts[8] if len(parts) > 8 else ''}"
                        )

                last_row = rows[-1].split(",")
                if len(last_row) >= 4:
                    main_force = float(last_row[2])
                    lines.append(
                        f"\nClose: mainForce={last_row[2]}万 "
                        f"retail={last_row[3]}万"
                    )
                    if main_force > 0:
                        lines.append(
                            "Signal: Net main force INFLOW (bullish)"
                        )
                    elif main_force < 0:
                        lines.append(
                            "Signal: Net main force OUTFLOW (bearish)"
                        )
            else:
                lines.append(
                    "No realtime fund flow (non-trading hours or holiday)"
                )

        # Historical daily fund flow
        if include_history:
            date_compact = curr_date.replace("-", "")
            url_hist = (
                "https://finance.pae.baidu.com/vapi/v1/fundsortlist"
                f"?code={code}&market=ab&finance_type=stock"
                f"&tab=day&from=history&date={date_compact}"
                "&pn=0&rn=20&finClientType=pc"
            )
            rh = requests.get(
                url_hist, headers=_BAIDU_PAE_HEADERS, timeout=10
            )
            dh = rh.json()

            if dh.get("ResultCode", -1) == 0:
                hist = dh.get("Result", {}).get("content", [])
                if hist:
                    lines.append(
                        f"\n## Historical Daily Fund Flow "
                        f"(last {len(hist)} trading days)"
                    )
                    lines.append(
                        "Date | Close | Change | SuperBig | Large "
                        "| Medium | Small | MainForce"
                    )
                    for row in hist:
                        lines.append(
                            f"  {row.get('showtime', '')} "
                            f"| {row.get('closepx', '')} "
                            f"| {row.get('ratio', '')} "
                            f"| super={row.get('superNetIn', '')} "
                            f"| large={row.get('largeNetIn', '')} "
                            f"| med={row.get('mediumNetIn', '')} "
                            f"| small={row.get('littleNetIn', '')} "
                            f"| main={row.get('extMainIn', '')}"
                        )

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching fund flow for {code}: {str(e)}"


# ---------------------------------------------------------------------------
# 15. Dragon Tiger Board (龙虎榜)
# ---------------------------------------------------------------------------

def get_dragon_tiger_board(
    ticker: str,
    trade_date: str,
    look_back_days: int = 30,
) -> str:
    """Get dragon-tiger board (龙虎榜) appearances and seat details.

    Args:
        ticker: 6-digit A-share code, e.g. '000858'
        trade_date: YYYY-MM-DD
        look_back_days: how many days back to search (default 30)

    Returns:
        Formatted text with LHB appearances, top buyer/seller seats,
        and institutional activity.
    """
    import akshare as ak

    code = safe_ticker_component(ticker)
    end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
    start_dt = end_dt - pd.Timedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y%m%d")
    end_date = end_dt.strftime("%Y%m%d")
    lines = [f"# 龙虎榜数据 | {code} | {trade_date} (近{look_back_days}日)"]

    try:
        df = ak.stock_lhb_detail_em(start_date=start_date, end_date=end_date)
        stock_df = df[df["代码"] == code]
        if stock_df.empty:
            lines.append(f"\n近{look_back_days}日未上龙虎榜。")
        else:
            lines.append(f"\n## 上榜记录 ({len(stock_df)} 次)")
            lines.append("日期 | 原因 | 净买入(万) | 成交额(万) | 换手率")
            for _, row in stock_df.iterrows():
                lines.append(
                    f"  {row.get('上榜日', '')} | {row.get('上榜原因', '')} "
                    f"| {row.get('龙虎榜净买额', 0):.0f} "
                    f"| {row.get('成交额', 0):.0f} "
                    f"| {row.get('换手率', 0):.2f}%"
                )
    except Exception as e:
        lines.append(f"龙虎榜列表查询失败: {e}")

    try:
        dates_df = ak.stock_lhb_stock_detail_date_em(symbol=code)
        if dates_df is not None and not dates_df.empty:
            latest_date = str(dates_df.iloc[0]["交易日"]).split(" ")[0]
            lines.append(f"\n## 最近上榜席位明细 ({latest_date})")
            for flag_label in ("买入", "卖出"):
                try:
                    seat_df = ak.stock_lhb_stock_detail_em(
                        symbol=code, date=latest_date, flag=flag_label
                    )
                    if seat_df is not None and not seat_df.empty:
                        lines.append(f"\n### {flag_label}席位 TOP5")
                        lines.append("营业部 | 买入(万) | 卖出(万) | 净额(万)")
                        for _, row in seat_df.head(5).iterrows():
                            lines.append(
                                f"  {row.get('交易营业部名称', '')} "
                                f"| {row.get('买入金额', 0):.0f} "
                                f"| {row.get('卖出金额', 0):.0f} "
                                f"| {row.get('净额', 0):.0f}"
                            )
                except Exception:
                    pass
    except Exception:
        pass

    try:
        inst_df = ak.stock_lhb_jgmmtj_em(
            start_date=start_date, end_date=end_date
        )
        stock_inst = inst_df[inst_df["代码"] == code]
        if not stock_inst.empty:
            lines.append("\n## 机构动向")
            for _, row in stock_inst.iterrows():
                lines.append(
                    f"  机构买入 {row.get('买方机构数', 0)} 家 "
                    f"| 卖出 {row.get('卖方机构数', 0)} 家 "
                    f"| 净额 {row.get('机构买卖净额', row.get('净额', 0)):.0f} 万"
                )
    except Exception:
        pass

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 16. Lockup Expiry Calendar (限售解禁日历)
# ---------------------------------------------------------------------------

def get_lockup_expiry(
    ticker: str,
    trade_date: str,
    forward_days: int = 90,
) -> str:
    """Get lockup expiry schedule for a stock.

    Args:
        ticker: 6-digit A-share code
        trade_date: YYYY-MM-DD
        forward_days: how many days forward to check (default 90)

    Returns:
        Formatted text with historical unlock records and upcoming
        expiry calendar with impact metrics.
    """
    import akshare as ak

    code = safe_ticker_component(ticker)
    lines = [f"# 限售解禁日历 | {code} | {trade_date}"]

    try:
        df = ak.stock_restricted_release_queue_em(symbol=code)
        if df is not None and not df.empty:
            lines.append(f"\n## 个股解禁记录 (共 {len(df)} 批)")
            lines.append(
                "解禁时间 | 类型 | 解禁数量 | 占总市值比例 | 解禁前后涨跌幅"
            )
            for _, row in df.head(15).iterrows():
                lines.append(
                    f"  {row.get('解禁时间', '')} "
                    f"| {row.get('限售股类型', '')} "
                    f"| {row.get('实际解禁数量', row.get('解禁数量', ''))} "
                    f"| {row.get('占总市值比例', '')} "
                    f"| {row.get('解禁前后20日涨跌幅', '')}"
                )
        else:
            lines.append("\n无历史解禁记录。")
    except Exception as e:
        lines.append(f"个股解禁查询失败: {e}")

    try:
        end_dt = datetime.strptime(trade_date, "%Y-%m-%d") + pd.Timedelta(
            days=forward_days
        )
        df = ak.stock_restricted_release_detail_em(
            start_date=trade_date.replace("-", ""),
            end_date=end_dt.strftime("%Y%m%d"),
        )
        if df is not None:
            stock_df = df[df["股票代码"] == code]
            if not stock_df.empty:
                lines.append(
                    f"\n## 未来 {forward_days} 天待解禁"
                )
                for _, row in stock_df.iterrows():
                    lines.append(
                        f"  {row.get('解禁时间', '')} "
                        f"| {row.get('限售股类型', '')} "
                        f"| 数量 {row.get('实际解禁数量', row.get('解禁数量', ''))} "
                        f"| 占流通 {row.get('占流通市值比例', '')} "
                        f"| 解禁前收盘 {row.get('解禁前收盘价', '')}"
                    )
            else:
                lines.append(f"\n未来 {forward_days} 天无待解禁。")
    except Exception as e:
        lines.append(f"解禁日历查询失败: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 17. Industry Comparison (行业横向对比)
# ---------------------------------------------------------------------------

def get_industry_comparison(
    ticker: str,
    trade_date: str,
    top_n: int = 20,
) -> str:
    """Get industry sector performance comparison.

    Args:
        ticker: 6-digit A-share code (used to identify relevant sector)
        trade_date: YYYY-MM-DD
        top_n: number of top/bottom industries to show (default 20)

    Returns:
        Formatted text with sector performance ranking, highlighting
        the sector the target stock belongs to.
    """
    import akshare as ak

    code = safe_ticker_component(ticker)
    lines = [f"# 行业横向对比 | {code} | {trade_date}"]

    try:
        df = ak.stock_board_industry_summary_ths()
        if df is not None and not df.empty:
            lines.append(
                f"\n## 全行业表现 (同花顺 {len(df)} 个行业)"
            )
            lines.append(
                "排名 | 行业 | 涨跌幅 | 成交额(亿) | 净流入(亿) "
                "| 上涨 | 下跌 | 领涨股"
            )
            for i, (_, row) in enumerate(df.iterrows()):
                change = row.get("涨跌幅", 0)
                turnover = row.get("总成交额", 0)
                net_flow = row.get("净流入", 0)
                lines.append(
                    f"  {i+1}. {row.get('板块', '')} "
                    f"| {change}% "
                    f"| {turnover:.1f} "
                    f"| {net_flow:.1f} "
                    f"| {row.get('上涨家数', '')} "
                    f"| {row.get('下跌家数', '')} "
                    f"| {row.get('领涨股', '')}"
                )
                if i >= top_n * 2 - 1:
                    lines.append(f"  ... (showing top/bottom {top_n})")
                    break
        else:
            lines.append("行业数据获取为空。")
    except Exception as e:
        lines.append(f"行业对比查询失败: {e}")

    return "\n".join(lines)
