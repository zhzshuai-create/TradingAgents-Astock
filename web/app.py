"""
TradingAgents-Astock · 统一投资研究平台
AI多智能体分析 + 实时数据看板
"""

from __future__ import annotations

import sys
import time
import ast
from datetime import date
from pathlib import Path

import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from collections import Counter

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

load_dotenv(_PROJECT_ROOT / ".env")

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from web.components.progress_panel import render_progress  # noqa: E402
from web.components.report_viewer import render_report  # noqa: E402
from web.history import extract_signal, load_analysis, get_history  # noqa: E402
from web.progress import ProgressTracker  # noqa: E402
from web.runner import run_analysis_in_thread  # noqa: E402
from web.data_functions import (  # noqa: E402
    normalize_code, tencent_quote, ths_eps_forecast,
    ths_hot_reason, baidu_concept_blocks, hsgt_realtime,
    load_northbound_history, get_kline_data, industry_comparison,
    cls_telegraph, eastmoney_stock_news,
    forward_pe, calc_peg, pe_digestion,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Page config
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="TradingAgents · AStock Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Session state ────────────────────────────────────────────────────────────
if "app_mode" not in st.session_state:
    st.session_state["app_mode"] = "analysis"
if "data_code" not in st.session_state:
    st.session_state["data_code"] = ""

# ═══════════════════════════════════════════════════════════════════════════════
# CSS
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');

#MainMenu, header[data-testid="stHeader"],
footer, div[data-testid="stDecoration"],
button[data-testid="stBaseButton-header"],
div[data-testid="stToolbar"] { display: none !important; }

html, body, [class*="css"] {
    font-family: 'Microsoft YaHei', 'PingFang SC', 'Inter', sans-serif;
}
.stApp { background: #ffffff; }
section[data-testid="stSidebar"] {
    background: #f8f9fa; border-right: 1px solid #e0e0e0;
}

/* Metric cards */
.metric-card {
    background: #fff; border-radius: 12px; padding: 1rem 0.8rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06); text-align: center;
}
.metric-card .label { font-size: 0.78rem; color: #999; margin-bottom: 0.2rem; }
.metric-card .value { font-size: 1.35rem; font-weight: 700; color: #1a1a1a; }
.metric-card .sub { font-size: 0.75rem; color: #aaa; }

/* Stock cards */
.stock-card {
    background: #fff; border-radius: 10px; padding: 0.55rem 0.8rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 0.25rem;
    display: flex; align-items: center; gap: 0.6rem; font-size: 0.9rem;
}
.stock-card .code { font-weight: 700; color: #1a1a1a; min-width: 55px; }
.stock-card .name { color: #555; min-width: 65px; }
.stock-card .pct { font-weight: 700; min-width: 55px; }
.stock-card .reason { color: #888; font-size: 0.8rem; flex: 1; }

/* Tags */
.tag { display: inline-block; background: #e8f0fe; color: #1a73e8;
       padding: 2px 8px; border-radius: 6px; font-size: 0.76rem; margin: 2px; }

/* Buttons */
.stMetric label { color: #888 !important; font-size: 0.8rem !important; }
.stMetric [data-testid="stMetricValue"] { color: #ff5a1f !important; font-weight: 700 !important; }
.stProgress > div > div > div { background: linear-gradient(90deg, #ff5a1f, #ff8c42) !important; }
button[kind="primary"] {
    background: linear-gradient(135deg, #ff5a1f, #e04d15) !important;
    border: none !important; font-weight: 700 !important;
    box-shadow: 0 2px 8px rgba(255,90,31,0.25) !important;
    color: #fff !important; transition: all 0.2s ease !important;
}
button[kind="primary"]:hover {
    background: linear-gradient(135deg, #e04d15, #cc3d00) !important;
    transform: translateY(-1px) !important;
}
button[kind="secondary"] {
    background: #ffffff !important; border: 1px solid #d0d0d0 !important;
    color: #333 !important; transition: all 0.2s ease !important;
}
button[kind="secondary"]:hover {
    background: #fff5f0 !important; border-color: #ff5a1f !important; color: #ff5a1f !important;
}
.stExpander { border: 1px solid #e0e0e0 !important; border-radius: 8px !important; }
.stTabs [data-baseweb="tab"] { color: #888 !important; }
.stTabs [aria-selected="true"] { color: #ff5a1f !important; border-bottom-color: #ff5a1f !important; }
div[data-testid="stDownloadButton"] button {
    background: #ffffff !important; border: 1px solid #ff5a1f !important; color: #ff5a1f !important;
}
div[data-testid="stDownloadButton"] button:hover { background: #fff5f0 !important; }
input[data-testid="stTextInputRootElement"] input, .stTextInput input {
    background: #ffffff !important; border-color: #d0d0d0 !important; color: #1a1a1a !important;
}
.stTextInput input:focus {
    border-color: #ff5a1f !important; box-shadow: 0 0 0 1px #ff5a1f !important;
}
.footer-note { text-align: center; color: #ccc; font-size: 0.75rem; padding: 1.5rem 0 0.5rem 0; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Sidebar
# ═══════════════════════════════════════════════════════════════════════════════

# ── Top navigation bar (replaces sidebar) ──
col_brand, col_nav, col_search = st.columns([1, 1.5, 2.5])
with col_brand:
    st.markdown("""
    <div style="padding-top:0.1rem;">
        <span style="font-size:1.1rem; font-weight:800; color:#ff5a1f;">Trading</span>
        <span style="font-size:1.1rem; font-weight:800; color:#1a1a1a;">Agents</span>
        <span style="font-size:1.1rem; font-weight:800; color:#ff5a1f;">-Astock</span>
        <br>
        <a href="https://github.com/zhzshuai-create" target="_blank" style="font-size:0.7rem; color:#aaa; text-decoration:none;">
            by zhzshuai-create
        </a>
    </div>
    """, unsafe_allow_html=True)

with col_nav:
    mode = st.radio(
        "模式",
        ["📊 AI分析报告", "📈 实时数据看板"],
        index=0 if st.session_state.get("app_mode") == "analysis" else 1,
        horizontal=True, key="top_mode",
    )
    if "AI分析" in mode and st.session_state.get("app_mode") != "analysis":
        st.session_state["app_mode"] = "analysis"
        st.rerun()
    elif "数据看板" in mode and st.session_state.get("app_mode") != "data":
        st.session_state["app_mode"] = "data"
        st.rerun()

with col_search:
    with st.form("search_form", clear_on_submit=False, border=False):
        s1, s2 = st.columns([5, 1])
        with s1:
            search_input = st.text_input(
                "股票代码",
                placeholder="输入代码如 600460",
                label_visibility="collapsed",
                key="top_search",
            )
        with s2:
            submitted = st.form_submit_button("→", help="搜索股票")
        if submitted and search_input:
            cleaned = normalize_code(search_input)
            if len(cleaned) >= 6:
                st.session_state["data_code"] = cleaned
                st.session_state["app_mode"] = "data"
                st.rerun()

st.markdown("---")


# ═══════════════════════════════════════════════════════════════════════════════
# Config helper (AI mode)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_config() -> dict:
    import os
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = os.getenv("LLM_PROVIDER", "deepseek")
    config["deep_think_llm"] = os.getenv("DEEP_THINK_LLM", "deepseek-chat")
    config["quick_think_llm"] = os.getenv("QUICK_THINK_LLM", "deepseek-chat")
    config["data_vendors"] = {
        "core_stock_apis": "a_stock", "technical_indicators": "a_stock",
        "fundamental_data": "a_stock", "news_data": "a_stock", "signal_data": "a_stock",
    }
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["output_language"] = "Chinese"
    return config


# ═══════════════════════════════════════════════════════════════════════════════
# AI Analysis Mode
# ═══════════════════════════════════════════════════════════════════════════════

def _render_analysis_mode() -> None:
    """Full TradingAgents analysis workflow."""
    # Trigger handler
    start_req = st.session_state.pop("start_analysis", None)
    if start_req:
        tracker = ProgressTracker(
            ticker=start_req["ticker"], trade_date=start_req["trade_date"],
        )
        st.session_state["tracker"] = tracker
        run_analysis_in_thread(
            ticker=start_req["ticker"], trade_date=start_req["trade_date"],
            config=_build_config(), tracker=tracker,
        )

    tracker: ProgressTracker | None = st.session_state.get("tracker")
    viewing_history: str | None = st.session_state.get("viewing_history")

    # State 1: viewing history
    if viewing_history:
        try:
            state = load_analysis(viewing_history)
            signal = extract_signal(state)
            ticker = Path(viewing_history).parent.parent.name
            trade_date = Path(viewing_history).stem.replace("full_states_log_", "")
            render_report(state, ticker, trade_date, signal)
        except Exception as exc:
            st.error(f"加载失败: {exc}")

    # State 2: running
    elif tracker and tracker.is_running:
        render_progress(tracker)
        time.sleep(2)
        st.rerun()

    # State 3: complete
    elif tracker and tracker.is_complete:
        render_report(tracker.final_state, tracker.ticker, tracker.trade_date,
                      tracker.signal, elapsed=tracker.elapsed)

    # State 4: error
    elif tracker and tracker.error:
        st.error(f"分析失败: {tracker.error}")
        if st.button("重试"):
            st.session_state.pop("tracker", None)
            st.rerun()

    # State 0: idle
    else:
        _SIG = {
            "Buy": ("🟢 买入", "#22c55e", "#f0fdf4"),
            "Sell": ("🔴 卖出", "#ef4444", "#fef2f2"),
            "Hold": ("🟡 持有", "#f59e0b", "#fffbeb"),
        }

        @st.cache_data(ttl=3600, show_spinner=False)
        def _signal_for(path: str) -> str:
            try:
                return extract_signal(load_analysis(path))
            except Exception:
                return "N/A"

        def _badge(s: str) -> str:
            label, color, bg = _SIG.get(s, (f"⚪ {s}", "#999", "#f5f5f5"))
            return (
                f'<span style="display:inline-block;font-size:0.7rem;font-weight:700;'
                f'color:{color};background:{bg};border:1px solid {color};'
                f'border-radius:4px;padding:2px 8px;white-space:nowrap;">{label}</span>'
            )

        # Banner
        st.markdown("""
        <div style="text-align: center; margin-top: 1rem; margin-bottom: 1.5rem;">
            <div style="font-size: 2rem; font-weight: 900;">
                <span style="color: #ff5a1f;">Trading</span><span style="color: #1a1a1a;">Agents</span><span style="color: #1a1a1a;">-</span><span style="color: #ff5a1f;">Astock</span>
            </div>
            <div style="color: #999; font-size: 0.82rem; margin-top: 0.2rem;">
                7位AI分析师 → 质量门控 → 多空辩论 → 风控评估 → 最终决策
            </div>
            <div style="margin-top: 0.5rem; font-size: 0.7rem; color: #ff5a1f; background: #fff5f0; display: inline-block; padding: 3px 12px; border-radius: 10px; border: 1px solid #ffccb0;">
                统一平台 · 2026-05-22
            </div>
        </div>
        """, unsafe_allow_html=True)

        left, right = st.columns([1.3, 1])

        # Left: history
        with left:
            st.markdown('<div style="font-weight:700;font-size:1.05rem;color:#1a1a1a;margin-bottom:0.4rem;">📊 历史分析记录</div>', unsafe_allow_html=True)

            full_history = get_history()
            history_search = st.text_input(
                "搜索历史", placeholder="搜索股票代码或日期",
                label_visibility="collapsed", key="main_history_search",
            )

            if history_search:
                q = history_search.strip().lower()
                display = [e for e in full_history if q in e["ticker"].lower() or q in e["date"]]
            else:
                display = full_history

            if not display:
                st.info("暂无历史分析记录" if not history_search else "没有匹配的记录")
            else:
                total = len(full_history)
                if history_search:
                    st.caption(f"找到 {len(display)} 条匹配（共 {total} 条）")
                else:
                    st.caption(f"共 {total} 条记录")
                max_items = 100 if history_search else 30
                for entry in display[:max_items]:
                    t, d, p = entry["ticker"], entry["date"], entry["path"]
                    signal = _signal_for(p)
                    badge_html = _badge(signal)
                    c1, c2 = st.columns([2.2, 1])
                    with c1:
                        if st.button(f"📈 {t}  ·  {d}", key=f"main_hist_{t}_{d}", use_container_width=True):
                            st.session_state["viewing_history"] = p
                            st.session_state["start_analysis"] = None
                            st.rerun()
                    with c2:
                        st.markdown(f'<div style="padding-top:6px;text-align:right;">{badge_html}</div>', unsafe_allow_html=True)

        # Right: new analysis
        with right:
            st.markdown('<div style="text-align:center;margin-bottom:0.5rem;font-weight:700;font-size:1.05rem;color:#1a1a1a;">🔍 新建分析</div>', unsafe_allow_html=True)
            st.markdown("<div style='height:0.3rem;'></div>", unsafe_allow_html=True)
            ticker = st.text_input("股票代码", placeholder="输入 6 位代码如 000636",
                                   max_chars=6, label_visibility="collapsed")
            trade_date = st.date_input("分析日期", label_visibility="collapsed")
            can_start = bool(ticker and len(ticker.strip()) >= 4)
            if st.button("开始分析", use_container_width=True, type="primary", disabled=not can_start):
                st.session_state["start_analysis"] = {
                    "ticker": ticker.strip(),
                    "trade_date": trade_date.strftime("%Y-%m-%d"),
                }
                st.session_state["viewing_history"] = None
                st.rerun()

    # Footer
    st.markdown("""
    <div style="text-align:center;margin-top:2rem;padding:0.8rem;color:#999;font-size:0.75rem;border-top:1px solid #e0e0e0;">
        ⚠️ 本项目仅供学习研究，不构成任何投资建议。
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Data Dashboard Mode
# ═══════════════════════════════════════════════════════════════════════════════

def _render_data_mode() -> None:
    code = st.session_state.get("data_code", "")

    if code:
        st.caption(f"当前股票: {code}")

    tabs = st.tabs(["📈 个股估值", "🔥 强势股归因", "💰 资金流向", "📰 资讯"])

    # ── Tab 1: 个股估值 ──
    with tabs[0]:
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
                clr = "#e03131" if q["change_pct"] >= 0 else "#2f9e44"

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
                                pe_color = "#e03131" if pe_fwd > 50 else ("#f08c00" if pe_fwd > 30 else "#2f9e44")
                                st.markdown(f'<div class="metric-card"><div class="label">前向 PE</div><div class="value" style="color:{pe_color}">{pe_fwd:.1f}x</div><div class="sub">{analyst_count} 家覆盖</div></div>', unsafe_allow_html=True)
                            with v2:
                                st.markdown(f'<div class="metric-card"><div class="label">CAGR</div><div class="value">{cagr*100:.0f}%</div><div class="sub">EPS 增速</div></div>', unsafe_allow_html=True)
                            with v3:
                                peg_str = f"{peg_val:.2f}" if peg_val != float("inf") else "-"
                                peg_color = "#2f9e44" if peg_val < 1 else ("#f08c00" if peg_val < 1.5 else "#e03131")
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

                    st.markdown("#### 近 30 日 K 线走势")
                    if not klines.empty:
                        recent_k = klines.tail(30).copy()
                        st.line_chart(recent_k.set_index("datetime")["close"], y_label="收盘价(元)", width='stretch')
                        st.bar_chart(recent_k.set_index("datetime")["vol"], y_label="成交量(手)", width='stretch')
                        closes = recent_k["close"]
                        chg = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
                        avg_vol = recent_k["vol"].mean()
                        chg_color = "#e03131" if chg > 0 else "#2f9e44"
                        st.markdown(f"**近30日涨幅:** <span style='color:{chg_color};font-weight:700'>{chg:+.2f}%</span> | **日均成交量:** {avg_vol/10000:.1f}万手", unsafe_allow_html=True)
                    else:
                        st.caption("暂无K线数据")

                if news:
                    st.markdown("---")
                    st.markdown("#### 近期新闻")
                    for n in news[:5]:
                        st.markdown(f"- **{n['time']}** {n['title']} `{n['source']}`")

    # ── Tab 2: 强势股归因 ──
    with tabs[1]:
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
                tag_html = " ".join([f'<span class="tag" style="font-size:0.85rem;margin:3px;">{t}({n})</span>' for t, n in top_tags])
                st.markdown(f"**题材热度 TOP 8:** {tag_html}")
            st.caption(f"共 {len(df_hot)} 只强势股")
            for _, row in df_hot.iterrows():
                pct_val = row.get("涨幅%", 0)
                pct_color = "#e03131" if pct_val >= 0 else "#2f9e44"
                reason_text = str(row.get(reason_col, "")) if reason_col in row.index else ""
                st.markdown(f'<div class="stock-card"><span class="code">{row.get("代码", "-")}</span><span class="name">{row.get("名称", "-")}</span><span class="pct" style="color:{pct_color}">{pct_val:+.2f}%</span><span class="reason">{reason_text}</span></div>', unsafe_allow_html=True)

    # ── Tab 3: 资金流向 ──
    with tabs[2]:
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
                        hgt_color = "#e03131" if last["hgt_yi"] > 0 else "#2f9e44"
                        st.markdown(f'<div class="metric-card"><div class="label">沪股通累计净买入</div><div class="value" style="color:{hgt_color}">{last["hgt_yi"]:.2f} 亿</div></div>', unsafe_allow_html=True)
                    with nc2:
                        sgt_color = "#e03131" if last["sgt_yi"] > 0 else "#2f9e44"
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
                        clr = "#e03131" if pct >= 0 else "#2f9e44"
                        st.markdown(f"<span style='color:{clr}'>{pct:+.2f}%</span> {r['name']} 涨{r['up_count']}跌{r['down_count']}", unsafe_allow_html=True)
                with ct2:
                    st.markdown("**跌幅 TOP 10**")
                    for r in comp["bottom"][:10]:
                        pct = r["change_pct"]
                        clr = "#e03131" if pct >= 0 else "#2f9e44"
                        st.markdown(f"<span style='color:{clr}'>{pct:+.2f}%</span> {r['name']}", unsafe_allow_html=True)

            if code:
                st.markdown(f"#### {code} K线走势")
                with st.spinner("加载K线..."):
                    kt3 = get_kline_data(code)
                if not kt3.empty:
                    recent = kt3.tail(30)
                    st.line_chart(recent.set_index("datetime")["close"], y_label="收盘价(元)", width='stretch')
                    st.bar_chart(recent.set_index("datetime")["vol"], y_label="成交量(手)", width='stretch')
                    st.caption(f"近30日涨幅: {(recent['close'].iloc[-1] / recent['close'].iloc[0] - 1)*100:+.2f}%")
                else:
                    st.caption("暂无K线数据")
            else:
                st.info("在上方输入股票代码可查看个股K线")

    # ── Tab 4: 资讯 ──
    with tabs[3]:
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

    st.markdown('<div class="footer-note">a-stock-data V3.1 | 数据仅供参考，不构成投资建议</div>', unsafe_allow_html=True)


def _render_market_overview() -> None:
    """Market overview shown when no stock code entered."""
    st.info("💡 在上方搜索框输入股票代码，查看完整估值分析")
    st.markdown("---")
    st.markdown("#### 大盘行业概况")
    with st.spinner("加载行业数据..."):
        comp = industry_comparison(10)
    if comp["top"]:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**📈 涨幅 TOP 10**")
            for r in comp["top"][:10]:
                pct = r["change_pct"]
                clr = "#e03131" if pct >= 0 else "#2f9e44"
                st.markdown(f"<span style='color:{clr};font-weight:600'>{pct:+.2f}%</span> {r['name']} 涨{r['up_count']}跌{r['down_count']}", unsafe_allow_html=True)
        with c2:
            st.markdown("**📉 跌幅 TOP 10**")
            for r in comp["bottom"][:10]:
                pct = r["change_pct"]
                clr = "#e03131" if pct >= 0 else "#2f9e44"
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
            pct_color = "#e03131" if pct_val >= 0 else "#2f9e44"
            reason_col = "题材归因" if "题材归因" in df_hot.columns else "reason"
            reason_text = str(row.get(reason_col, "")) if reason_col in row.index else ""
            st.markdown(f'<div class="stock-card"><span class="code">{row.get("代码", "-")}</span><span class="name">{row.get("名称", "-")}</span><span class="pct" style="color:{pct_color}">{pct_val:+.2f}%</span><span class="reason">{reason_text}</span></div>', unsafe_allow_html=True)
    else:
        st.caption("暂无今日数据")


# ═══════════════════════════════════════════════════════════════════════════════
# Main dispatch
# ═══════════════════════════════════════════════════════════════════════════════

if st.session_state.get("app_mode") == "analysis":
    _render_analysis_mode()
else:
    _render_data_mode()
