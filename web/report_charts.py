"""报告 PDF 数据可视化：从数据层拉真实数据绘制图表。

原则：只画数据层能给出的真实数据，观点性内容（辩论/政策定性判断）
不硬量化——那会变成伪精确。当前覆盖 7 个章节：
技术分析(日K蜡烛)、市场情绪(融资余额日变化)、新闻舆情(关注度分布)、
基本面(估值路径)、游资追踪(主力净流入)、解禁减持(批次时间轴)、
最终决策(关键价位地图)。

设计边界（与数据层护栏同一标准）：
- 任一图表数据取不到或渲染失败 → 该图跳过并 log warning，绝不阻塞 PDF 导出；
- 图片渲染到临时目录，由调用方（generate_pdf）在导出完成后清理；
- PDF 为白底固定配色，不存在亮暗主题问题；
- A 股配色约定：红涨/红流入、绿跌/绿流出。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 无头渲染，必须在 pyplot 之前

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

from tradingagents.dataflows.a_stock import _common

logger = logging.getLogger(__name__)

# matplotlib 中文字体候选（命中第一个已安装的）
_CJK_FONT_CANDIDATES = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "WenQuanYi Micro Hei",
]

# A 股配色：红=涨/流入，绿=跌/流出
_UP_COLOR = "#d94a4a"
_DOWN_COLOR = "#2e9e60"
_MAIN_COLOR = "#e8590c"
_ACCENT_COLOR = "#3775ba"
_TARGET_COLOR = "#888888"


def _setup_cjk_font() -> None:
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in _CJK_FONT_CANDIDATES:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name]
            break
    plt.rcParams["axes.unicode_minus"] = False


def _save(fig: plt.Figure, out: Path) -> Path:
    fig.savefig(out, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# 图1: 日K蜡烛 + MA + 成交量（技术分析报告）
# ---------------------------------------------------------------------------


def _fig_candles(code: str, curr_date: str, out: Path) -> None:
    """近 90 个交易日日K蜡烛 + MA5/10/20 + 成交量副图。

    x 轴用整数序号而非日历时间：停牌/节假日不留空洞（看板 plotly 的
    rangebreaks 坑在 matplotlib 里用这个方式天然绕开）。
    """
    full = _common._load_ohlcv_astock(code, curr_date)
    if full is None or len(full) < 30:
        raise ValueError(f"K线数据不足({0 if full is None else len(full)}根)")

    ma_src = full.tail(110).reset_index(drop=True)  # MA 预热窗口
    df = ma_src.tail(90).reset_index(drop=True)
    close = df["Close"].astype(float)

    fig, (ax, ax_vol) = plt.subplots(
        2, 1, figsize=(9.5, 5.2), sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
    )

    up = close >= df["Open"].astype(float)
    x = range(len(df))
    up_x = [i for i in x if up[i]]
    down_x = [i for i in x if not up[i]]
    # 影线（按涨跌分组，vlines 不支持 where 参数）
    ax.vlines(up_x, df.loc[up_x, "Low"], df.loc[up_x, "High"],
              color=_UP_COLOR, linewidth=0.7)
    ax.vlines(down_x, df.loc[down_x, "Low"], df.loc[down_x, "High"],
              color=_DOWN_COLOR, linewidth=0.7)
    # 实体
    body_bottom = pd.concat([df["Open"], df["Close"]], axis=1).min(axis=1)
    body_height = (df["Close"] - df["Open"]).abs().clip(lower=1e-9)
    ax.bar(
        x, body_height, bottom=body_bottom, width=0.65,
        color=[_UP_COLOR if u else _DOWN_COLOR for u in up],
        linewidth=0,
    )

    for win, color in [(5, _MAIN_COLOR), (10, _ACCENT_COLOR), (20, "#9b59b6")]:
        ma = close.rolling(win).mean()
        ax.plot(x, ma, linewidth=1.1, color=color, label=f"MA{win}")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    ax.set_title(
        f"{code} 日K蜡烛图（近 {len(df)} 个交易日，"
        f"截至 {str(df['Date'].iloc[-1])[:10]}）",
        fontsize=11,
    )
    ax.grid(alpha=0.25, linewidth=0.5)
    ax.tick_params(labelsize=8)

    vol = df["Volume"].astype(float)
    ax_vol.bar(
        x, vol / 1e4, width=0.65,
        color=[_UP_COLOR if u else _DOWN_COLOR for u in up],
        linewidth=0,
    )
    ax_vol.set_ylabel("成交量", fontsize=8)
    ax_vol.grid(alpha=0.25, linewidth=0.5)
    ax_vol.tick_params(labelsize=8)

    # 日期刻度：约 8 个均布点
    step = max(1, len(df) // 8)
    ticks = list(range(0, len(df), step))
    labels = [str(df["Date"].iloc[i])[:10] for i in ticks]
    ax_vol.set_xticks(ticks)
    ax_vol.set_xticklabels(labels, rotation=30, fontsize=7)
    ax_vol.margins(x=0.01)

    return _save(fig, out)


# ---------------------------------------------------------------------------
# 图2: 主力/超大单净流入柱状图（游资追踪报告）
# ---------------------------------------------------------------------------


def _fetch_daily_main_flow(code: str, lmt: int = 20) -> pd.DataFrame:
    """东财 push2his 日级资金流 → DataFrame(date, 主力亿, 超大单亿)。

    fields2 序列: f51=日期, f52=主力, f53=小单, f54=中单, f55=大单,
    f56=超大单（单位: 元）——与 signals.get_fund_flow 同一接口。
    """
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": secid, "lmt": lmt, "klt": 101,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    r = _common._em_get(url, params=params, timeout=10)
    klines = (r.json().get("data") or {}).get("klines") or []
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 6:
            rows.append(
                (parts[0][:10], float(parts[1]) / 1e8, float(parts[5]) / 1e8)
            )
    if not rows:
        raise ValueError("东财日级资金流为空")
    return pd.DataFrame(rows, columns=["date", "main_yi", "super_yi"])


def _fig_fund_flow(code: str, curr_date: str, out: Path) -> None:
    df = _fetch_daily_main_flow(code)
    n = len(df)
    fig, ax = plt.subplots(figsize=(9.5, 4.2))
    x = range(n)
    width = 0.42
    ax.bar(
        [i - width / 2 for i in x], df["main_yi"], width=width,
        color=[_UP_COLOR if v >= 0 else _DOWN_COLOR for v in df["main_yi"]],
        label="主力净流入",
        linewidth=0,
    )
    ax.bar(
        [i + width / 2 for i in x], df["super_yi"], width=width,
        color=[_UP_COLOR if v >= 0 else _DOWN_COLOR for v in df["super_yi"]],
        alpha=0.55, label="超大单净流入",
        linewidth=0,
    )
    ax.axhline(0, color="#444444", linewidth=0.8)
    ax.set_title(
        f"{code} 主力/超大单日净流入（近 {n} 个交易日，单位: 亿元，"
        f"截至 {df['date'].iloc[-1]}）",
        fontsize=11,
    )
    ax.set_ylabel("净流入(亿元)", fontsize=8)
    step = max(1, n // 10)
    ax.set_xticks(list(range(0, n, step)))
    ax.set_xticklabels(
        [df["date"].iloc[i] for i in range(0, n, step)],
        rotation=30, fontsize=7,
    )
    ax.tick_params(axis="y", labelsize=8)
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    ax.grid(alpha=0.25, axis="y", linewidth=0.5)
    ax.margins(x=0.01)

    return _save(fig, out)


# ---------------------------------------------------------------------------
# 图3: 估值路径（基本面报告）
# ---------------------------------------------------------------------------


def _fig_valuation(code: str, curr_date: str, out: Path) -> None:
    """TTM PE + 一致预期前向 PE 阶梯图，附 A 股成长股 30x 锚线。

    数据与 get_fundamentals 同源：腾讯行情（TTM PE/价格）+ 同花顺一致预期
    （覆盖机构数/EPS 中枢）。
    """
    tq = _common._tencent_quote([code])
    if code not in tq:
        raise ValueError("腾讯行情无数据")
    price = tq[code]["price"]
    pe_ttm = tq[code]["pe_ttm"]
    if price <= 0:
        raise ValueError("价格异常")

    fdf = _common._ths_eps_forecast(code)
    if fdf is None or fdf.empty:
        raise ValueError("无一致预期数据")

    labels, values, covers = ["TTM"], [float(pe_ttm)], [0]
    for _, row in fdf.iterrows():
        year = str(row.iloc[0])
        try:
            mean_eps = float(row.iloc[3])
            count = int(row.iloc[1])
        except (ValueError, TypeError):
            continue
        if mean_eps > 0:
            labels.append(f"FY{year}E")
            values.append(price / mean_eps)
            covers.append(count)
    if len(labels) == 1:
        raise ValueError("一致预期 EPS 无有效年份")

    fig, ax = plt.subplots(figsize=(9.5, 4.2))
    colors = [_MAIN_COLOR] + [_ACCENT_COLOR] * (len(labels) - 1)
    bars = ax.bar(labels, values, color=colors, width=0.55, linewidth=0)
    for bar, value, count in zip(bars, values, covers):
        note = f"{value:.1f}x"
        if count >= 3:
            note += f"\n({count}家)"
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height(),
            note, ha="center", va="bottom", fontsize=8,
        )
    ax.axhline(30, color=_TARGET_COLOR, linestyle="--", linewidth=1,
               label="A股成长股估值锚 ≈30x")
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    ax.set_title(
        f"{code} 估值路径（现价 {price:.2f} 元；FY 前向 PE = 现价/一致预期 EPS）",
        fontsize=11,
    )
    ax.set_ylabel("PE (倍)", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=0.25, axis="y", linewidth=0.5)
    ax.margins(y=0.12)

    return _save(fig, out)


# ---------------------------------------------------------------------------
# 调度与清理
# ---------------------------------------------------------------------------
# 图4: 融资余额日度变化（市场情绪报告） — 杠杆资金退潮的可视化
# ---------------------------------------------------------------------------


def _fig_margin(code: str, curr_date: str, out: Path) -> None:
    rows = _common._eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX",
        filter_str=f'(SCODE="{code}")',
        page_size=30,
        sort_columns="DATE",
        sort_types="-1",
    )
    points = sorted(
        (str(r.get("DATE", ""))[:10], float(r.get("RZYE") or 0))
        for r in rows
        if r.get("RZYE") is not None
    )
    if len(points) < 3:
        raise ValueError("融资融券数据不足")
    df = pd.DataFrame(points, columns=["date", "rzye"])
    df["change"] = df["rzye"].diff() / 1e8  # 日环比变化(亿)
    df = df.iloc[1:]

    fig, ax = plt.subplots(figsize=(9.5, 4.0))
    colors = [_UP_COLOR if v >= 0 else _DOWN_COLOR for v in df["change"]]
    ax.bar(range(len(df)), df["change"], color=colors, width=0.65, linewidth=0)
    ax.axhline(0, color="#444444", linewidth=0.8)
    ax.set_title(
        f"{code} 融资余额日度变化（近 {len(df)} 个交易日，"
        f"最新余额 {df['rzye'].iloc[-1] / 1e8:.1f} 亿，截至 {df['date'].iloc[-1]}；"
        f"红=杠杆加仓 绿=杠杆减仓）",
        fontsize=10.5,
    )
    ax.set_ylabel("融资余额日变化(亿元)", fontsize=8)
    step = max(1, len(df) // 10)
    ax.set_xticks(list(range(0, len(df), step)))
    ax.set_xticklabels(
        [df["date"].iloc[i] for i in range(0, len(df), step)],
        rotation=30, fontsize=7,
    )
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(alpha=0.25, axis="y", linewidth=0.5)
    ax.margins(x=0.01)

    return _save(fig, out)


# ---------------------------------------------------------------------------
# 图5: 个股新闻关注度分布（新闻舆情报告）
# ---------------------------------------------------------------------------


def _fetch_news_dates(code: str, page_size: int = 100) -> list[str]:
    """东财个股新闻（JSONP）→ 新闻日期列表（YYYY-MM-DD）。"""
    import json as _json

    import requests

    inner = _json.dumps(
        {
            "uid": "",
            "keyword": code,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {"cmsArticleWebOld": {
                "searchScope": "default", "sort": "default",
                "pageIndex": 1, "pageSize": page_size,
                "preTag": "", "postTag": "",
            }},
        },
        separators=(",", ":"),
    )
    r = requests.get(
        "https://search-api-web.eastmoney.com/search/jsonp",
        params={"cb": "jQuery_chart_news", "param": inner},
        headers={"User-Agent": _common._UA, "Referer": "https://so.eastmoney.com/"},
        timeout=15,
    )
    text = r.text
    d = _json.loads(text[text.index("(") + 1: text.rindex(")")])
    # 形状兼容：2026-10 实测 result.cmsArticleWebOld 直接就是文章列表，
    # 技能库文档里的 {"list": [...]} 包装是旧形状
    result = d.get("result")
    if isinstance(result, list):
        result = result[0] if result else {}
    block = result.get("cmsArticleWebOld") if isinstance(result, dict) else None
    if isinstance(block, dict):
        arts = block.get("list") or []
    elif isinstance(block, list):
        arts = block
    else:
        arts = []
    dates = [
        str(a.get("date", ""))[:10]
        for a in arts
        if isinstance(a, dict) and a.get("date")
    ]
    return [x for x in dates if x <= "9999"]


def _fig_news_volume(code: str, curr_date: str, out: Path) -> None:
    dates = _fetch_news_dates(code)
    cutoff = pd.to_datetime(curr_date)
    s = pd.Series(pd.to_datetime(dates, errors="coerce")).dropna()
    s = s[s <= cutoff]
    if s.empty:
        raise ValueError("无新闻数据")

    # 近 30 个自然日逐日计数（含 0 条日，关注度真空也可见）
    idx = pd.date_range(end=cutoff, periods=30, freq="D")
    daily = s.dt.normalize().value_counts().reindex(idx, fill_value=0)

    fig, ax = plt.subplots(figsize=(9.5, 4.0))
    ax.bar(range(len(daily)), daily.values, color=_ACCENT_COLOR,
           width=0.7, linewidth=0)
    top = daily.nlargest(3)
    for ts, count in top.items():
        i = daily.index.get_loc(ts)
        if count > 0:
            ax.text(i, count, str(int(count)), ha="center", va="bottom",
                    fontsize=8, color="#333333")
    ax.set_title(
        f"{code} 东财个股新闻关注度（近 30 个自然日，"
        f"采样 {len(s)} 条，峰值 {int(daily.max())} 条/日）",
        fontsize=10.5,
    )
    ax.set_ylabel("新闻条数", fontsize=8)
    step = max(1, len(daily) // 10)
    ax.set_xticks(list(range(0, len(daily), step)))
    ax.set_xticklabels(
        [str(ts)[:10] for ts in daily.index[::step]],
        rotation=30, fontsize=7,
    )
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(alpha=0.25, axis="y", linewidth=0.5)
    ax.margins(x=0.01, y=0.15)

    return _save(fig, out)


# ---------------------------------------------------------------------------
# 图6: 限售解禁批次时间轴（解禁/减持报告）
# ---------------------------------------------------------------------------


def _fig_lockup(code: str, curr_date: str, out: Path) -> None:
    history = _common._eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=15,
        sort_columns="FREE_DATE",
        sort_types="-1",
    )
    end_dt = pd.to_datetime(curr_date) + pd.Timedelta(days=90)
    end_str = end_dt.strftime("%Y-%m-%d")
    upcoming = _common._eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=(
            f'(SECURITY_CODE="{code}")'
            f"(FREE_DATE>='{curr_date}')(FREE_DATE<='{end_str}')"
        ),
        page_size=20,
        sort_columns="FREE_DATE",
        sort_types="1",
    )
    if not history and not upcoming:
        raise ValueError("无解禁记录")

    # 占比口径自适应：2026-10-06 601208 实测 FREE_RATIO 为小数（0.4458 =
    # 44.58%）；若接口某天返回百分数值（最大值 > 1）则不再缩放
    hist_rows = sorted(
        (str(r.get("FREE_DATE", ""))[:10], float(r.get("FREE_RATIO") or 0))
        for r in history
        if r.get("FREE_DATE")
    )
    up_rows = sorted(
        (str(r.get("FREE_DATE", ""))[:10], float(r.get("FREE_RATIO") or 0))
        for r in upcoming
        if r.get("FREE_DATE")
    )
    all_vals = [v for _, v in hist_rows] + [v for _, v in up_rows]
    if all_vals and max(all_vals) <= 1.0:
        hist_rows = [(d, v * 100) for d, v in hist_rows]
        up_rows = [(d, v * 100) for d, v in up_rows]
        all_vals = [v * 100 for v in all_vals]

    fig, ax = plt.subplots(figsize=(9.5, 4.0))
    all_dates = [d for d, _ in hist_rows] + [d for d, _ in up_rows]
    all_vals = [v for _, v in hist_rows] + [v for _, v in up_rows]
    xs = range(len(all_dates))
    colors = [_MAIN_COLOR] * len(hist_rows) + [_ACCENT_COLOR] * len(up_rows)
    hatches = [""] * len(hist_rows) + ["//"] * len(up_rows)
    bars = ax.bar(xs, all_vals, color=colors, width=0.6, linewidth=0.6,
                  edgecolor="white")
    for bar, hatch in zip(bars, hatches):
        bar.set_hatch(hatch)
    for i, v in enumerate(all_vals):
        if v > 0:
            ax.text(i, v, f"{v:.1f}%", ha="center", va="bottom", fontsize=7.5)
    ax.set_title(
        f"{code} 限售解禁批次（历史 {len(hist_rows)} 批 + 未来90天 "
        f"{len(up_rows)} 批；橙色=已解禁 蓝色斜纹=待解禁）",
        fontsize=10.5,
    )
    ax.set_ylabel("解禁占总股本(%)", fontsize=8)
    step = max(1, len(all_dates) // 8)
    ax.set_xticks(list(range(0, len(all_dates), step)))
    ax.set_xticklabels(
        [all_dates[i] for i in range(0, len(all_dates), step)],
        rotation=30, fontsize=7,
    )
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(alpha=0.25, axis="y", linewidth=0.5)
    ax.margins(x=0.01, y=0.15)

    return _save(fig, out)


# ---------------------------------------------------------------------------
# 图7: 关键价位地图（最终决策）
# ---------------------------------------------------------------------------


def _fig_price_levels(code: str, curr_date: str, out: Path) -> None:
    """客观价位阶梯：现价/涨跌停/MA50/布林带上下轨。

    全部由已有数据计算（K线 + 腾讯行情），不含任何决策专属假设。
    """
    df = _common._load_ohlcv_astock(code, curr_date)
    if df is None or len(df) < 50:
        raise ValueError("K线数据不足，无法计算 MA50/布林带")
    close = df["Close"].astype(float)
    ma50 = close.rolling(50).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    std20 = close.rolling(20).std().iloc[-1]
    boll_up, boll_low = ma20 + 2 * std20, ma20 - 2 * std20

    tq = _common._tencent_quote([code])
    price = float(tq[code]["price"]) if code in tq else float(close.iloc[-1])
    limit_up = float(tq.get(code, {}).get("limit_up") or 0)
    limit_down = float(tq.get(code, {}).get("limit_down") or 0)

    levels: list[tuple[str, float, str, str]] = []  # (名称, 价位, 颜色, 线型)
    if limit_down > 0:
        levels.append(("跌停", limit_down, "#777777", ":"))
    levels.append(("布林下轨(20,2σ)", boll_low, "#9b59b6", "--"))
    levels.append(("MA50", ma50, _ACCENT_COLOR, "-"))
    levels.append(("现价", price, _MAIN_COLOR, "-"))
    levels.append(("布林上轨(20,2σ)", boll_up, "#9b59b6", "--"))
    if limit_up > 0:
        levels.append(("涨停", limit_up, "#777777", ":"))
    levels = [lv for lv in levels if lv[1] > 0]
    levels.sort(key=lambda lv: lv[1])

    fig, ax = plt.subplots(figsize=(9.5, 4.2))
    lo = min(lv[1] for lv in levels)
    hi = max(lv[1] for lv in levels)
    pad = max((hi - lo) * 0.12, 0.5)
    min_gap = (hi - lo) * 0.048  # 标签最小间距（布林上轨/涨停常挤在一起）
    last_text_y = None
    for i, (name, value, color, style) in enumerate(levels):
        lw = 2.4 if name == "现价" else 1.4
        ax.hlines(value, 0, 1, color=color, linewidth=lw, linestyle=style)
        text_y = value
        if last_text_y is not None and abs(text_y - last_text_y) < min_gap:
            text_y = last_text_y + min_gap  # 升序排列，向上错位
        ax.text(
            0.02, text_y, f"{name}  {value:.2f}",
            va="center", fontsize=9,
            color="#222222" if name != "现价" else _MAIN_COLOR,
            fontweight="bold" if name == "现价" else "normal",
        )
        last_text_y = text_y
    ax.set_xlim(0, 1)
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_title(
        f"{code} 关键价位地图（截至 {str(df['Date'].iloc[-1])[:10]}，"
        f"现价 {price:.2f} 元）",
        fontsize=11,
    )
    ax.set_xticks([])
    ax.tick_params(axis="y", labelsize=8)
    ax.set_ylabel("价格(元)", fontsize=8)

    return _save(fig, out)


# ---------------------------------------------------------------------------

# 章节名 → (文件名前缀, 渲染函数)
_CHART_BUILDERS = {
    "技术分析报告": ("candles", _fig_candles),
    "市场情绪报告": ("margin", _fig_margin),
    "新闻舆情报告": ("news_volume", _fig_news_volume),
    "基本面报告": ("valuation", _fig_valuation),
    "游资追踪报告": ("fund_flow", _fig_fund_flow),
    "解禁/减持报告": ("lockup", _fig_lockup),
    "最终决策": ("price_levels", _fig_price_levels),
}


def generate_report_charts(
    ticker: str,
    trade_date: str,
    out_dir: Path | None = None,
) -> tuple[dict[str, Path], Path]:
    """按 PDF 章节生成图表。

    返回 ({章节名: 图片路径}, 输出目录)。任一图表失败只 log warning 并
    跳过——图是锦上添花，绝不能阻塞导出。
    """
    code = _common._normalize_ticker(ticker)
    _setup_cjk_font()
    if out_dir is None:
        out_dir = Path(tempfile.mkdtemp(prefix="astock_charts_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    charts: dict[str, Path] = {}
    for section, (name, builder) in _CHART_BUILDERS.items():
        try:
            path = builder(code, trade_date, out_dir / f"{name}_{code}.png")
            if path.exists() and path.stat().st_size > 0:
                charts[section] = path
        except Exception as exc:  # noqa: BLE001 — 单图失败不能拖垮整份导出
            logger.warning("报告图表 %s(%s) 生成失败，跳过: %s", name, section, exc)
    return charts, out_dir


def cleanup_chart_dir(chart_dir: Path | None) -> None:
    """删除图表临时目录（generate_pdf 导出完成后调用）。"""
    if chart_dir is None:
        return
    shutil.rmtree(chart_dir, ignore_errors=True)
