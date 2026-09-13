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


# ═══════════════════════════════════════════════════════════════════════════════
# Data Dashboard Mode
# ═══════════════════════════════════════════════════════════════════════════════

def render_data_mode() -> None:
    code = st.session_state.get("data_code", "")
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
            with st.spinner("加载中..."):
                quote = tencent_quote([code])
                eps_df = ths_eps_forecast(code)
                blocks = baidu_concept_blocks(code)
                klines = get_kline_data(code)
                news = eastmoney_stock_news(code, 8)

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
                            k5 = klines.tail(5).copy()
                            close_s = k5.set_index("datetime")["close"]
                            vol_s = k5.set_index("datetime")["vol"]
                            st.altair_chart(_price_chart(close_s), use_container_width=True)
                            st.altair_chart(_vol_chart(vol_s), use_container_width=True)
                            closes5 = k5["close"]
                            chg5 = (closes5.iloc[-1] / closes5.iloc[0] - 1) * 100 if len(closes5) >= 2 else 0
                            chg5_color = "var(--up)" if chg5 > 0 else "var(--down)"
                            st.markdown(f'5日变动: <span style="color:{chg5_color};font-weight:700">{chg5:+.2f}%</span>', unsafe_allow_html=True)
                        else:
                            st.caption("暂无数据")

                    # ── 30日 ──────────────────────────────────────
                    elif kline_period == "30日":
                        if not klines.empty:
                            k30 = klines.tail(30).copy()
                            close_s = k30.set_index("datetime")["close"]
                            vol_s = k30.set_index("datetime")["vol"]
                            st.altair_chart(_price_chart(close_s), use_container_width=True)
                            st.altair_chart(_vol_chart(vol_s), use_container_width=True)
                            closes = k30["close"]
                            chg = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
                            avg_vol = k30["vol"].mean()
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
                            close_s = all_k.set_index("datetime")["close"]
                            st.altair_chart(_price_chart(close_s), use_container_width=True)
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
        for _, row in df_hot.head(10).iterrows():
            pct_val = row.get("涨幅%", 0)
            pct_color = "var(--up)" if pct_val >= 0 else "var(--down)"
            reason_col = "题材归因" if "题材归因" in df_hot.columns else "reason"
            reason_text = str(row.get(reason_col, "")) if reason_col in row.index else ""
            code = normalize_code(str(row.get("代码", "-")))
            name = str(row.get("名称", "-"))

            c_info, c_go = st.columns([9, 1.1], vertical_alignment="center")
            with c_info:
                st.markdown(f'<div class="stock-card"><span class="code">{row.get("代码", "-")}</span><span class="name">{row.get("名称", "-")}</span><span class="pct" style="color:{pct_color}">{pct_val:+.2f}%</span><span class="reason">{reason_text}</span></div>', unsafe_allow_html=True)
            with c_go:
                if st.button("📊 行情", key=f"ov_hot_{code}", use_container_width=True):
                    st.session_state["data_code"] = code
                    st.session_state["dash_tab"] = "📈 个股估值"
                    st.toast(f"正在打开 {name}({code}) 的行情页", icon="📊")
                    st.rerun()
    else:
        st.caption("暂无今日数据")


