"""
Data dashboard mode (个股估值 / 强势股归因 / 资金流向 / 资讯).

Extracted from app.py: all Streamlit rendering for the real-time data report mode.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import altair as alt
from collections import Counter

from web.data_functions import (
    normalize_code, tencent_quote, ths_eps_forecast,
    ths_hot_reason, baidu_concept_blocks, hsgt_realtime,
    load_northbound_history, get_kline_data, get_minute_data, industry_comparison,
    cls_telegraph, eastmoney_stock_news,
    forward_pe, calc_peg, pe_digestion,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Chart helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _price_chart(series: pd.Series, y_label: str = "价格(元)") -> alt.Chart:
    """Line chart with y‑axis anchored tightly to price range so oscillations are visible."""
    y_min = float(series.min())
    y_max = float(series.max())
    padding = max((y_max - y_min) * 0.1, 0.05)  # 10% headroom, min 0.05
    chart_df = series.reset_index()
    chart_df.columns = ["x", "y"]
    return (
        alt.Chart(chart_df)
        .mark_line(color="#ff5a1f")
        .encode(
            x=alt.X("x:T", title="", axis=alt.Axis(format="%m/%d")),
            y=alt.Y("y:Q", title=y_label,
                    scale=alt.Scale(domain=[y_min - padding, y_max + padding])),
        )
        .properties(width='container')
        .interactive().properties(usermeta={"embedOptions": {"actions": False}})
    )


def _vol_chart(series: pd.Series) -> alt.Chart:
    """Volume bar chart."""
    chart_df = series.reset_index()
    chart_df.columns = ["x", "y"]
    return (
        alt.Chart(chart_df)
        .mark_bar(color="#999", opacity=0.6)
        .encode(
            x=alt.X("x:T", title="", axis=alt.Axis(format="%m/%d")),
            y=alt.Y("y:Q", title="成交量(手)", axis=alt.Axis(format="~s")),
        )
        .properties(width='container')
        .interactive().properties(usermeta={"embedOptions": {"actions": False}})
    )


def _candlestick_chart(
    kdf: pd.DataFrame, display_tail: int | None = None, height: int = 480
):
    """OHLC 蜡烛图 + MA5/10/20 + 成交量副图（plotly，量价共享 x 轴联动缩放）。

    涨红跌绿（A 股惯例，与主题 --up/--down 同色系）；背景透明适配亮暗主题；
    周末 rangebreaks 去掉非交易日空隙。kdf 用于计算均线（建议 ≥25 根），
    display_tail 控制实际只显示最近 N 根（如 5 日视图取 tail(25) 显示 5 根）。
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    k = kdf.copy()
    k["datetime"] = pd.to_datetime(k["datetime"])
    k["ma5"] = k["close"].rolling(5).mean()
    k["ma10"] = k["close"].rolling(10).mean()
    k["ma20"] = k["close"].rolling(20).mean()
    if display_tail:
        k = k.tail(display_tail)
    up = (k["close"] >= k["open"]).tolist()
    up_c, dn_c = "#e03131", "#2f9e44"

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.74, 0.26], vertical_spacing=0.04,
    )
    fig.add_trace(go.Candlestick(
        x=k["datetime"], open=k["open"], high=k["high"], low=k["low"], close=k["close"],
        increasing_line_color=up_c, increasing_fillcolor=up_c,
        decreasing_line_color=dn_c, decreasing_fillcolor=dn_c,
        name="K线", showlegend=False,
    ), row=1, col=1)
    for name, color in (("ma5", "#f08c00"), ("ma10", "#1971c2"), ("ma20", "#9c36b5")):
        fig.add_trace(go.Scatter(
            x=k["datetime"], y=k[name], name=name.upper(),
            line=dict(width=1.3, color=color),
            hoverinfo="skip",
        ), row=1, col=1)
    fig.add_trace(go.Bar(
        x=k["datetime"], y=k["vol"],
        marker_color=[up_c if u else dn_c for u in up],
        name="成交量", showlegend=False,
    ), row=2, col=1)

    fig.update_layout(
        height=height, margin=dict(l=8, r=18, t=12, b=8),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#888888", size=11),
    )
    fig.update_xaxes(
        rangeslider_visible=False, gridcolor="rgba(128,128,128,0.18)",
        rangebreaks=[dict(bounds=["sat", "mon"])],
    )
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.18)", zeroline=False)
    fig.update_yaxes(title_text="价格(元)", row=1, col=1)
    fig.update_yaxes(title_text="成交量(手)", row=2, col=1)
    return fig


def _show_candles(kdf: pd.DataFrame, display_tail: int | None = None, height: int = 480) -> None:
    st.plotly_chart(
        _candlestick_chart(kdf, display_tail=display_tail, height=height),
        use_container_width=True,
        config={"displayModeBar": False, "scrollZoom": True},
    )


# 个股估值首载骨架屏：模拟 标题 + 6 估值卡 + 左右两栏 + K线图 的版式。
# 复用主题 CSS 变量（--line/--muted 等），亮暗主题自动适配，无需 JS 判断主题。
_QUOTE_SKELETON_HTML = """
<style>
@keyframes sk-shimmer {
  0%   { background-position: -420px 0; }
  100% { background-position: 420px 0; }
}
.sk-block {
  border-radius: 10px;
  background: linear-gradient(90deg, var(--line) 25%, var(--muted) 45%, var(--line) 65%);
  background-size: 420px 100%;
  animation: sk-shimmer 1.3s infinite linear;
  opacity: 0.35;
}
</style>
<div style="padding: 0.25rem 0;">
  <div class="sk-block" style="width:220px;height:28px;margin-bottom:0.9rem;"></div>
  <div style="display:flex;gap:0.8rem;margin-bottom:0.9rem;">
    <div class="sk-block" style="flex:1;height:84px;"></div>
    <div class="sk-block" style="flex:1;height:84px;"></div>
    <div class="sk-block" style="flex:1;height:84px;"></div>
    <div class="sk-block" style="flex:1;height:84px;"></div>
    <div class="sk-block" style="flex:1;height:84px;"></div>
    <div class="sk-block" style="flex:1;height:84px;"></div>
  </div>
  <div style="display:flex;gap:0.8rem;margin-bottom:0.9rem;">
    <div class="sk-block" style="flex:1;height:200px;"></div>
    <div class="sk-block" style="flex:1;height:200px;"></div>
  </div>
  <div class="sk-block" style="width:100%;height:320px;"></div>
  <div style="color:var(--muted);font-size:var(--font-sm);margin-top:0.6rem;">
    正在加载 __CODE__ 的行情、估值与 K 线数据…
  </div>
</div>
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Data Dashboard Mode
# ═══════════════════════════════════════════════════════════════════════════════

def _dash_search_callback() -> None:
    """看板顶部搜索框提交回调：代码/中文名 → data_code（与侧边栏同源 resolve_ticker）.

    提交后清空输入框便于连续搜索；解析失败把错误写进 session 下一轮显示。
    """
    from tradingagents.dataflows.a_stock import resolve_ticker

    raw = (st.session_state.get("dash_search_input") or "").strip()
    st.session_state["dash_search_input"] = ""
    if not raw:
        return
    try:
        code = resolve_ticker(raw)
    except ValueError as e:
        st.session_state["dash_search_err"] = str(e)
        return
    st.session_state["dash_search_err"] = None
    st.session_state["data_code"] = code
    # 新代码 → 自动切个股估值分区，复用 render_data_mode 开头的 _last_data_code 门控


def render_data_mode() -> None:
    code = st.session_state.get("data_code", "")

    # ── 顶部搜索框（代码或中文名，Enter 提交）──
    ss1, _ = st.columns([2, 3])
    with ss1:
        st.text_input(
            "搜索股票", key="dash_search_input", on_change=_dash_search_callback,
            placeholder="搜索代码或名称，如 300750 / 宁德时代",
            label_visibility="collapsed",
        )
    if st.session_state.get("dash_search_err"):
        st.error(f"搜索失败：{st.session_state.pop('dash_search_err')}")

    # 顶部搜索框输入新代码 → 自动切到个股估值分区
    if st.session_state.get("_last_data_code") != code:
        st.session_state["_last_data_code"] = code
        if code:
            st.session_state["dash_tab"] = "📈 个股估值"

    if code:
        bc1, bc2 = st.columns([6, 1])
        with bc1:
            st.markdown(
                f'<div style="font-size:var(--font-md); color:var(--muted);">'
                f'<a href="#" style="color:var(--muted);text-decoration:none;" onclick="return false;">总览</a>'
                f'  ›  <b style="color:var(--text);">{code}</b></div>',
                unsafe_allow_html=True,
            )
        with bc2:
            if st.button("← 返回总览", key="clear_stock_top", use_container_width=True):
                st.session_state.pop("data_code", None)
                st.rerun()

    DASH_TABS = ["📈 个股估值", "🔥 强势股归因", "💰 资金流向", "📰 资讯"]
    selected_tab = st.radio(
        "看板分区", DASH_TABS, key="dash_tab",
        horizontal=True, label_visibility="collapsed",
    )

    # ── Tab 1: 个股估值 ──
    if selected_tab == "📈 个股估值":
        if not code:
            _render_market_overview()
        else:
            # 骨架屏：仅同股首次加载显示（慢速抓取 2~8s），后续重跑（切周期/换主题）
            # 走缓存秒回，不再渲染骨架避免闪烁。抓取完成后用 ph.empty() 清除占位。
            _sk_key = f"_quote_loaded_{code}"
            ph = st.empty()
            if not st.session_state.get(_sk_key):
                with ph.container():
                    st.markdown(_QUOTE_SKELETON_HTML.replace("__CODE__", code), unsafe_allow_html=True)
            quote = tencent_quote([code])
            eps_df = ths_eps_forecast(code)
            blocks = baidu_concept_blocks(code)
            klines = get_kline_data(code)
            news = eastmoney_stock_news(code, 8)
            st.session_state[_sk_key] = True
            ph.empty()

            if code not in quote:
                st.error(f"未找到 {code} 的行情数据")
            else:
                q = quote[code]
                clr = "var(--up)" if q["change_pct"] >= 0 else "var(--down)"

                st.markdown(f"### {q['name']}({code})")

                c1, c2, c3, c4, c5, c6 = st.columns(6)
                with c1:
                    st.markdown(f'<div class="metric-card"><div class="label">当前价</div><div class="value" style="color:{clr}">{q["price"]:.2f}</div><div class="sub">{q["change_amt"]:+.2f} ({q["change_pct"]:+.2f}%)</div></div>', unsafe_allow_html=True)
                with c2:
                    st.markdown(f'<div class="metric-card"><div class="label">PE(TTM)</div><div class="value">{q["pe_ttm"]:.1f}</div><div class="sub">{"亏损" if q["pe_ttm"] <= 0 else "盈利"}</div></div>', unsafe_allow_html=True)
                with c3:
                    st.markdown(f'<div class="metric-card"><div class="label">PB</div><div class="value">{q["pb"]:.2f}</div><div class="sub">市净率</div></div>', unsafe_allow_html=True)
                with c4:
                    mcap_str = f"{q['mcap_yi']:.0f}亿" if q['mcap_yi'] else "-"
                    st.markdown(f'<div class="metric-card"><div class="label">总市值</div><div class="value">{mcap_str}</div><div class="sub">流通{q["float_mcap_yi"]:.0f}亿</div></div>', unsafe_allow_html=True)
                with c5:
                    st.markdown(f'<div class="metric-card"><div class="label">换手率</div><div class="value">{q["turnover_pct"]:.2f}%</div><div class="sub">成交{q["amount_wan"]/10000:.2f}亿</div></div>', unsafe_allow_html=True)
                with c6:
                    st.markdown(f'<div class="metric-card"><div class="label">涨跌停</div><div class="value">{q["limit_up"]:.2f}</div><div class="sub">跌停{q["limit_down"]:.2f}</div></div>', unsafe_allow_html=True)

                st.markdown("---")

                col_left, col_right = st.columns([1, 1])

                with col_left:
                    st.markdown("#### 机构一致预期 EPS")
                    if eps_df.empty:
                        st.caption("暂无机构覆盖数据")
                    else:
                        st.dataframe(eps_df, width='stretch', hide_index=True)
                        eps_cur = eps_next = None
                        analyst_count = 0
                        try:
                            for i, row in eps_df.iterrows():
                                if i == 0:
                                    eps_cur = float(row.iloc[2]) if len(row) > 2 and pd.notna(row.iloc[2]) else None
                                    analyst_count = int(row.iloc[1]) if len(row) > 1 and pd.notna(row.iloc[1]) else 0
                                elif i == 1:
                                    eps_next = float(row.iloc[2]) if len(row) > 2 and pd.notna(row.iloc[2]) else None
                        except (ValueError, IndexError):
                            pass

                        if eps_cur:
                            pe_fwd = forward_pe(q["price"], eps_cur)
                            cagr = (eps_next / eps_cur - 1) if eps_next else 0
                            peg_val = calc_peg(pe_fwd, cagr) if cagr > 0 else float("inf")
                            digest = pe_digestion(pe_fwd, cagr) if cagr > 0 else float("inf")

                            st.markdown("#### 估值指标")
                            v1, v2, v3, v4 = st.columns(4)
                            with v1:
                                pe_color = "var(--up)" if pe_fwd > 50 else ("var(--warn)" if pe_fwd > 30 else "var(--down)")
                                st.markdown(f'<div class="metric-card"><div class="label">前向 PE</div><div class="value" style="color:{pe_color}">{pe_fwd:.1f}x</div><div class="sub">{analyst_count} 家覆盖</div></div>', unsafe_allow_html=True)
                            with v2:
                                st.markdown(f'<div class="metric-card"><div class="label">CAGR</div><div class="value">{cagr*100:.0f}%</div><div class="sub">EPS 增速</div></div>', unsafe_allow_html=True)
                            with v3:
                                peg_str = f"{peg_val:.2f}" if peg_val != float("inf") else "-"
                                peg_color = "var(--down)" if peg_val < 1 else ("var(--warn)" if peg_val < 1.5 else "var(--up)")
                                st.markdown(f'<div class="metric-card"><div class="label">PEG</div><div class="value" style="color:{peg_color}">{peg_str}</div><div class="sub">{"便宜" if peg_val < 1 else ("合理" if peg_val < 1.5 else "偏贵")}</div></div>', unsafe_allow_html=True)
                            with v4:
                                digest_str = f"{digest:.1f}年" if digest != float("inf") else "∞"
                                st.markdown(f'<div class="metric-card"><div class="label">PE 消化</div><div class="value">{digest_str}</div><div class="sub">消化至 30x</div></div>', unsafe_allow_html=True)

                with col_right:
                    st.markdown("#### 概念板块")
                    if blocks.get("concept_tags"):
                        tags_html = " ".join([f'<span class="tag">{t}</span>' for t in blocks["concept_tags"][:15]])
                        st.markdown(f"<div>{tags_html}</div>", unsafe_allow_html=True)
                    else:
                        st.caption("暂无概念数据")
                    if blocks.get("industry"):
                        ind_names = [b["name"] for b in blocks["industry"][:3]]
                        st.markdown("**行业:** " + ", ".join(ind_names))
                    if blocks.get("region"):
                        reg_names = [b["name"] for b in blocks["region"][:3]]
                        st.markdown("**地域:** " + ", ".join(reg_names))

                    st.markdown("#### K 线走势")
                    kline_period = st.radio(
                        "周期", ["单日详情", "5日", "30日", "全部历史"],
                        horizontal=True, key=f"kperiod_{code}",
                        index=2,  # default to 30-day
                    )

                    # ── 单日详情 ──────────────────────────────────
                    if kline_period == "单日详情":
                        minute_df = get_minute_data(code)
                        if not minute_df.empty:
                            st.altair_chart(_price_chart(minute_df["price"], "价格(元)"), use_container_width=True)
                            st.altair_chart(_vol_chart(minute_df["vol"]), use_container_width=True)
                            st.caption(f"共 {len(minute_df)} 个1分钟数据点")
                        else:
                            st.info("暂无日内分钟数据（可能为非交易日）")
                        # Key stats from daily quote
                        mc1, mc2, mc3, mc4 = st.columns(4)
                        with mc1:
                            st.metric("今开", f"{q['open']:.2f}")
                        with mc2:
                            st.metric("最高", f"{q['high']:.2f}")
                        with mc3:
                            st.metric("最低", f"{q['low']:.2f}")
                        with mc4:
                            st.metric("昨收", f"{q['last_close']:.2f}")

                    # ── 5日 ───────────────────────────────────────
                    elif kline_period == "5日":
                        if not klines.empty:
                            k5 = klines.tail(25).copy()   # 25 根算 MA，只显示最近 5 根
                            _show_candles(k5, display_tail=5, height=420)
                            closes5 = klines.tail(5)["close"]
                            chg5 = (closes5.iloc[-1] / closes5.iloc[0] - 1) * 100 if len(closes5) >= 2 else 0
                            chg5_color = "var(--up)" if chg5 > 0 else "var(--down)"
                            st.markdown(f'5日变动: <span style="color:{chg5_color};font-weight:700">{chg5:+.2f}%</span>', unsafe_allow_html=True)
                        else:
                            st.caption("暂无数据")

                    # ── 30日 ──────────────────────────────────────
                    elif kline_period == "30日":
                        if not klines.empty:
                            k30 = klines.tail(50).copy()  # 50 根算 MA，只显示最近 30 根
                            _show_candles(k30, display_tail=30, height=480)
                            closes = k30["close"]
                            chg = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
                            avg_vol = klines.tail(30)["vol"].mean()
                            chg_color = "var(--up)" if chg > 0 else "var(--down)"
                            st.markdown(f'30日涨幅: <span style="color:{chg_color};font-weight:700">{chg:+.2f}%</span>  |  日均成交量: {avg_vol/10000:.1f}万手', unsafe_allow_html=True)
                        else:
                            st.caption("暂无K线数据")

                    # ── 全部历史 ──────────────────────────────────
                    else:
                        with st.spinner("加载全部历史K线..."):
                            from web.data_functions import _get_kline_full
                            all_k = _get_kline_full(code)
                        if not all_k.empty:
                            _show_candles(all_k, height=520)
                            closes_all = all_k["close"]
                            chg_all = (closes_all.iloc[-1] / closes_all.iloc[0] - 1) * 100 if len(closes_all) >= 2 else 0
                            chga_color = "var(--up)" if chg_all > 0 else "var(--down)"
                            st.markdown(f'上市至今: <span style="color:{chga_color};font-weight:700">{chg_all:+.2f}%</span>  |  共 {len(all_k)} 个交易日', unsafe_allow_html=True)
                        else:
                            st.caption("暂无全部历史K线数据")

                if news:
                    st.markdown("---")
                    st.markdown("#### 近期新闻")
                    for n in news[:5]:
                        st.markdown(f"- **{n['time']}** {n['title']} `{n['source']}`")

    # ── Tab 2: 强势股归因 ──
    elif selected_tab == "🔥 强势股归因":
        st.markdown("#### 当日强势股 · 题材归因")
        with st.spinner("加载强势股数据..."):
            df_hot = ths_hot_reason()
        if df_hot.empty:
            st.warning("暂无今日强势股数据（可能非交易日或盘后未更新）")
        else:
            all_tags = []
            reason_col = "题材归因" if "题材归因" in df_hot.columns else "reason"
            for r in df_hot[reason_col].dropna() if reason_col in df_hot.columns else []:
                all_tags.extend([t.strip() for t in str(r).split("+") if t.strip()])
            cnt = Counter(all_tags)
            if cnt:
                top_tags = cnt.most_common(8)
                tag_html = " ".join([f'<span class="tag" style="font-size:var(--font-md);margin:var(--space-xs);">{t}({n})</span>' for t, n in top_tags])
                st.markdown(f"**题材热度 TOP 8:** {tag_html}", unsafe_allow_html=True)
            st.caption(f"共 {len(df_hot)} 只强势股  |  点击 📊 查看股票详情")
            for _, row in df_hot.iterrows():
                code = str(row.get("代码", ""))
                name = str(row.get("名称", ""))
                pct_val = row.get("涨幅%", 0)
                pct_color = "var(--up)" if pct_val >= 0 else "var(--down)"
                reason_text = str(row.get(reason_col, "")) if reason_col in row.index else ""

                c_cols = st.columns([1, 2, 1.5, 5, 1.2])
                with c_cols[0]:
                    st.markdown(f'<div style="padding-top:var(--space-xs);font-weight:700;color:var(--text);">{code}</div>', unsafe_allow_html=True)
                with c_cols[1]:
                    st.markdown(f'<div style="padding-top:var(--space-xs);color:var(--muted);">{name}</div>', unsafe_allow_html=True)
                with c_cols[2]:
                    st.markdown(f'<div style="padding-top:var(--space-xs);font-weight:700;color:{pct_color};">{pct_val:+.2f}%</div>', unsafe_allow_html=True)
                with c_cols[3]:
                    st.markdown(f'<div style="padding-top:var(--space-xs);color:var(--muted);font-size:var(--font-md);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{reason_text}</div>', unsafe_allow_html=True)
                with c_cols[4]:
                    if st.button("📊 查看", key=f"hot_{code}", use_container_width=True):
                        st.session_state["data_code"] = normalize_code(code)
                        st.session_state["dash_tab"] = "📈 个股估值"
                        st.toast(f"已选择 {name}({code})，正在跳转个股估值", icon="📊")
                        st.rerun()

    # ── Tab 3: 资金流向 ──
    elif selected_tab == "💰 资金流向":
        sub_a, sub_b = st.tabs(["北向资金", "行业资金"])
        with sub_a:
            st.markdown("#### 北向资金（沪股通 + 深股通）")
            with st.spinner("加载北向数据..."):
                df_north = hsgt_realtime()
                df_hist = load_northbound_history(20)
            if not df_north.empty:
                df_clean = df_north.dropna()
                if not df_clean.empty:
                    last = df_clean.iloc[-1]
                    nc1, nc2 = st.columns(2)
                    with nc1:
                        hgt_color = "var(--up)" if last["hgt_yi"] > 0 else "var(--down)"
                        st.markdown(f'<div class="metric-card"><div class="label">沪股通累计净买入</div><div class="value" style="color:{hgt_color}">{last["hgt_yi"]:.2f} 亿</div></div>', unsafe_allow_html=True)
                    with nc2:
                        sgt_color = "var(--up)" if last["sgt_yi"] > 0 else "var(--down)"
                        st.markdown(f'<div class="metric-card"><div class="label">深股通累计净买入</div><div class="value" style="color:{sgt_color}">{last["sgt_yi"]:.2f} 亿</div></div>', unsafe_allow_html=True)
                    st.line_chart(df_clean.set_index("time")[["hgt_yi", "sgt_yi"]], y_label="累计净买入(亿)", width='stretch')
            else:
                st.warning("暂无北向实时数据（非交易时段）")
            if not df_hist.empty:
                st.markdown("#### 近 20 日北向历史")
                st.dataframe(df_hist.set_index("date"), width='stretch')

        with sub_b:
            st.markdown("#### 行业资金排名")
            with st.spinner("加载行业数据..."):
                comp = industry_comparison(15)
            if comp["top"]:
                ct1, ct2 = st.columns([1, 1])
                with ct1:
                    st.markdown("**涨幅 TOP 10**")
                    for r in comp["top"][:10]:
                        pct = r["change_pct"]
                        clr = "var(--up)" if pct >= 0 else "var(--down)"
                        st.markdown(f"<span style='color:{clr}'>{pct:+.2f}%</span> {r['name']} 涨{r['up_count']}跌{r['down_count']}", unsafe_allow_html=True)
                with ct2:
                    st.markdown("**跌幅 TOP 10**")
                    for r in comp["bottom"][:10]:
                        pct = r["change_pct"]
                        clr = "var(--up)" if pct >= 0 else "var(--down)"
                        st.markdown(f"<span style='color:{clr}'>{pct:+.2f}%</span> {r['name']}", unsafe_allow_html=True)

            if code:
                st.markdown(f"#### {code} K线走势")
                with st.spinner("加载K线..."):
                    kt3 = get_kline_data(code)
                if not kt3.empty:
                    recent = kt3.tail(30)
                    close_s = recent.set_index("datetime")["close"]
                    vol_s = recent.set_index("datetime")["vol"]
                    st.altair_chart(_price_chart(close_s), use_container_width=True)
                    st.altair_chart(_vol_chart(vol_s), use_container_width=True)
                    st.caption(f"近30日涨幅: {(recent['close'].iloc[-1] / recent['close'].iloc[0] - 1)*100:+.2f}%")
                else:
                    st.caption("暂无K线数据")
            else:
                st.info("在上方输入股票代码可查看个股K线")

    # ── Tab 4: 资讯 ──
    elif selected_tab == "📰 资讯":
        st.markdown("#### 财联社快讯")
        with st.spinner("加载快讯..."):
            telegrams = cls_telegraph(30)
        if telegrams:
            for item in telegrams[:20]:
                st.markdown(f"- **{item['time']}** {item['title'][:80]}")
        else:
            st.warning("暂无快讯数据")

        if code:
            st.markdown("---")
            st.markdown(f"#### {code} 个股新闻")
            with st.spinner("加载个股新闻..."):
                s_news = eastmoney_stock_news(code, 15)
            if s_news:
                for n in s_news:
                    st.markdown(f"- **{n['time']}** [{n['title']}]({n['url']}) `{n['source']}`")
            else:
                st.caption("暂无个股新闻")
        else:
            st.info("在上方输入股票代码可加载个股新闻")

    st.markdown('<div class="footer-note">AStock Pro · <a href="https://github.com/zhzshuai-create" target="_blank">github.com/zhzshuai-create</a> | a-stock-data V3.1 | 数据仅供参考，不构成投资建议</div>', unsafe_allow_html=True)


def _render_market_overview() -> None:
    """Market overview shown when no stock code entered."""
    st.caption("💡 在顶部搜索框输入股票代码，查看完整估值分析")
    with st.spinner("加载行业数据..."):
        comp = industry_comparison(10)
    if comp["top"]:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**📈 涨幅 TOP 10**")
            for r in comp["top"][:10]:
                pct = r["change_pct"]
                clr = "var(--up)" if pct >= 0 else "var(--down)"
                st.markdown(f"<span style='color:{clr};font-weight:600'>{pct:+.2f}%</span> {r['name']} 涨{r['up_count']}跌{r['down_count']}", unsafe_allow_html=True)
        with c2:
            st.markdown("**📉 跌幅 TOP 10**")
            for r in comp["bottom"][:10]:
                pct = r["change_pct"]
                clr = "var(--up)" if pct >= 0 else "var(--down)"
                st.markdown(f"<span style='color:{clr};font-weight:600'>{pct:+.2f}%</span> {r['name']}", unsafe_allow_html=True)
    else:
        st.caption("暂无行业数据")

    st.markdown("---")
    st.markdown("#### 当日强势股速览")
    with st.spinner("加载..."):
        df_hot = ths_hot_reason()
    if not df_hot.empty:
        reason_col = "题材归因" if "题材归因" in df_hot.columns else "reason"
        hot_display = df_hot.head(10)[["代码", "名称", "涨幅%", reason_col]].rename(
            columns={reason_col: "题材归因"}
        )
        hot_display["代码"] = hot_display["代码"].astype(str)
        _chg = pd.to_numeric(hot_display["涨幅%"], errors="coerce").fillna(0)
        hot_display["涨幅%"] = _chg.map(lambda v: f"{v:+.2f}%")

        # 整行可点：点击任意一行直接跳转到该股的个股估值页
        event = st.dataframe(
            hot_display,
            hide_index=True,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
            key="hot_pick",
            column_config={
                "代码": st.column_config.TextColumn("代码", width="small"),
                "名称": st.column_config.TextColumn("名称", width="small"),
                "涨幅%": st.column_config.TextColumn("涨幅%", width="small"),
                "题材归因": st.column_config.TextColumn("题材归因", width="large"),
            },
        )
        sel_rows = event.selection.rows
        if sel_rows:
            picked = str(hot_display.iloc[sel_rows[0]]["代码"])
            st.session_state["data_code"] = normalize_code(picked)
            st.session_state["dash_tab"] = "📈 个股估值"
            st.rerun()
    else:
        st.caption("暂无今日数据")


