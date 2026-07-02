"""
AStock Pro · zhzshuai-create 定制版
AI多智能体分析 + 实时数据看板 | Powered by TradingAgents
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

import altair as alt

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

load_dotenv(_PROJECT_ROOT / ".env")

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402
from web.components.progress_panel import render_progress  # noqa: E402
from web.components.report_viewer import render_report  # noqa: E402
from web.components.sidebar import render_sidebar  # noqa: E402
from web.history import extract_signal, load_analysis, get_history  # noqa: E402
from web.progress import ProgressTracker  # noqa: E402
from web.runner import run_analysis_in_thread  # noqa: E402
from web.data_functions import (  # noqa: E402
    normalize_code, tencent_quote, ths_eps_forecast,
    ths_hot_reason, baidu_concept_blocks, hsgt_realtime,
    load_northbound_history, get_kline_data, get_minute_data, industry_comparison,
    cls_telegraph, eastmoney_stock_news,
    forward_pe, calc_peg, pe_digestion,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Page config
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="AStock Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state ────────────────────────────────────────────────────────────
if "app_mode" not in st.session_state:
    st.session_state["app_mode"] = "analysis"
if "data_code" not in st.session_state:
    st.session_state["data_code"] = ""
if "theme" not in st.session_state:
    st.session_state["theme"] = "light"

# ═══════════════════════════════════════════════════════════════════════════════
# JS: Load saved theme before CSS paints (prevents flash on reruns)
# ═══════════════════════════════════════════════════════════════════════════════
components.html("""
<script>
(function(){
    var theme = localStorage.getItem('astock-theme') || 'light';
    document.documentElement.className = theme;
})();
</script>
""", height=0)

# ═══════════════════════════════════════════════════════════════════════════════
# CSS
# ═══════════════════════════════════════════════════════════════════════════════




# ═══════════════════════════════════════════════════════════════════════════════
# Dynamic CSS (theme-aware)
# ═══════════════════════════════════════════════════════════════════════════════

_LIGHT_VARS = """
    --bg-primary: #ffffff;
    --bg-secondary: #f8f9fa;
    --bg-tertiary: #e9ecef;
    --text-primary: #1a1a1a;
    --text-secondary: #555555;
    --text-tertiary: #777777;
    --accent: #e85d04;
    --accent-hover: #d9480f;
    --accent-light: #fff5f0;
    --up-color: #c92a2a;
    --down-color: #2b8a3e;
    --border-color: #dee2e6;
    --card-bg: #ffffff;
    --card-shadow: 0 1px 4px rgba(0,0,0,0.06);
    --tag-bg: #e8f0fe;
    --tag-text: #1a73e8;
    --input-bg: #ffffff;
    --input-border: #d0d0d0;
    --brand-text: #1a1a1a;
    --sidebar-bg: #f8f9fa;
"""

_LIGHT_STREAMLIT_OVERRIDES = """
/* Light mode Streamlit overrides (config.toml base=dark) */
html.light .stApp [data-testid="stHeader"] { background: #fff !important; }
html.light .stApp [data-testid="stToolbar"] { background: #fff !important; }
html.light .stApp .stMarkdown, html.light .stApp .stMarkdown * { color: #1a1a1a !important; }
html.light .stApp .stMarkdown a { color: #e85d04 !important; }
html.light .stApp [data-testid="stSidebar"] .stMarkdown * { color: #1a1a1a !important; }
html.light .stApp h1, html.light .stApp h2, html.light .stApp h3, html.light .stApp h4, html.light .stApp h5, html.light .stApp h6 { color: #1a1a1a !important; }
html.light .stApp p, html.light .stApp span:not([class*="metric"]) { color: #1a1a1a !important; }
html.light .stApp [data-testid="stMetricValue"] { color: #e85d04 !important; }
html.light .stApp [data-testid="stMetricLabel"] { color: #555 !important; }
html.light .stApp [data-testid="stCaptionContainer"] { color: #777 !important; }
html.light .stApp hr { border-color: #dee2e6 !important; }
html.light .stApp [data-baseweb="input"] { background: #fff !important; color: #1a1a1a !important; border-color: #d0d0d0 !important; }
html.light .stApp [data-baseweb="input"] input { color: #1a1a1a !important; }
html.light .stApp [data-baseweb="input"] input::placeholder { color: #999 !important; }
html.light .stApp [data-baseweb="select"] { background: #fff !important; color: #1a1a1a !important; border-color: #d0d0d0 !important; }
html.light .stApp [data-baseweb="select"] * { color: #1a1a1a !important; }
html.light .stApp [data-baseweb="popover"] { background: #fff !important; }
html.light .stApp [data-baseweb="popover"] * { color: #1a1a1a !important; }
html.light .stApp [data-testid="stExpander"] { background: #fff !important; border-color: #dee2e6 !important; color: #1a1a1a !important; }
html.light .stApp [data-testid="stExpander"] *:not(button) { color: #1a1a1a !important; }
html.light .stApp .stDataFrame { background: #fff !important; }
html.light .stApp .stDataFrame td, html.light .stApp .stDataFrame th { color: #1a1a1a !important; }
html.light .stApp [data-testid="stTable"] td, html.light .stApp [data-testid="stTable"] th { color: #1a1a1a !important; }
html.light .stApp .stAlert { background: #f8f9fa !important; color: #1a1a1a !important; }
html.light .stApp [data-baseweb="radio"] * { color: #1a1a1a !important; }
html.light .stApp [data-baseweb="checkbox"] * { color: #1a1a1a !important; }
html.light .stApp [data-testid="stForm"] { background: #fff !important; border-color: #dee2e6 !important; }
html.light .stApp [data-testid="stNotification"] { background: #fff !important; color: #1a1a1a !important; }
html.light .stApp [role="tab"] { color: #555 !important; }
html.light .stApp [aria-selected="true"][role="tab"] { color: #e85d04 !important; }
html.light .stApp [data-baseweb="tag"] { background: #e8f0fe !important; color: #1a73e8 !important; }
html.light .stApp [data-testid="stFormSubmitButton"] button { background: #e85d04 !important; color: #fff !important; border: none !important; }
html.light .stApp [data-testid="stFormSubmitButton"] button:hover { background: #d9480f !important; }
"""

_DARK_VARS = """
    --bg-primary: #1c1816;
    --bg-secondary: #252120;
    --bg-tertiary: #2d2927;
    --text-primary: #ede4dc;
    --text-secondary: #a3968a;
    --text-tertiary: #7d7268;
    --accent: #f0883e;
    --accent-hover: #ffa94d;
    --accent-light: #3d2a1a;
    --up-color: #ff6b6b;
    --down-color: #51cf66;
    --border-color: #383330;
    --card-bg: #252120;
    --card-shadow: 0 1px 4px rgba(0,0,0,0.25);
    --tag-bg: #2a3040;
    --tag-text: #7eb8f4;
    --input-bg: #2d2927;
    --input-border: #383330;
    --brand-text: #ede4dc;
    --sidebar-bg: #1c1816;
"""

_BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');

/* Hide Streamlit chrome selectively — keep sidebar toggle buttons accessible */
footer,
div[data-testid="stDecoration"],
button[data-testid="stBaseButton-header"],
div[data-testid="stStatusWidget"],
div[data-testid="stToolbarActions"],
div[data-testid="stAppDeployButton"],
span[data-testid="stMainMenu"] { display: none !important; }

/* Make header transparent so sidebar toggle controls remain clickable */
header[data-testid="stHeader"] {
    background: transparent !important;
    box-shadow: none !important;
}
div[data-testid="stToolbar"] {
    background: transparent !important;
}

/* Always keep sidebar collapse/expand controls visible & clickable */
button[data-testid="stSidebarCollapseButton"],
button[data-testid="collapsedControl"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    background: var(--card-bg) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 6px !important;
    color: var(--text-primary) !important;
    z-index: 999999 !important;
}
button[data-testid="stSidebarCollapseButton"]:hover,
button[data-testid="collapsedControl"]:hover {
    background: var(--accent-light) !important;
    border-color: var(--accent) !important;
    color: var(--accent) !important;
}

html, body, [class*="css"] {
    font-family: 'Microsoft YaHei', 'PingFang SC', 'Inter', sans-serif;
}
.stApp { background: var(--bg-primary); }
section[data-testid="stSidebar"] {
    background: var(--sidebar-bg); border-right: 1px solid var(--border-color);
}

.metric-card {
    background: var(--card-bg); border-radius: 12px; padding: 1rem 0.8rem;
    box-shadow: var(--card-shadow); text-align: center;
}
.metric-card .label { font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 0.2rem; }
.metric-card .value { font-size: 1.35rem; font-weight: 700; color: var(--text-primary); }
.metric-card .sub { font-size: 0.75rem; color: var(--text-tertiary); }

.stock-card {
    background: var(--card-bg); border-radius: 10px; padding: 0.55rem 0.8rem;
    box-shadow: var(--card-shadow); margin-bottom: 0.25rem;
    display: flex; align-items: center; gap: 0.6rem; font-size: 0.9rem;
}
.stock-card .code { font-weight: 700; color: var(--text-primary); min-width: 55px; }
.stock-card .name { color: var(--text-secondary); min-width: 65px; }
.stock-card .pct { font-weight: 700; min-width: 55px; }
.stock-card .reason { color: var(--text-secondary); font-size: 0.8rem; flex: 1; }

.tag { display: inline-block; background: var(--tag-bg); color: var(--tag-text);
       padding: 2px 8px; border-radius: 6px; font-size: 0.76rem; margin: 2px; }

.stMetric label { color: var(--text-secondary) !important; font-size: 0.8rem !important; }
.stMetric [data-testid="stMetricValue"] { color: var(--accent) !important; font-weight: 700 !important; }
.stProgress > div > div > div { background: linear-gradient(90deg, var(--accent), var(--accent-hover)) !important; }
button[kind="primary"] {
    background: linear-gradient(135deg, var(--accent), var(--accent-hover)) !important;
    border: none !important; font-weight: 700 !important;
    color: #fff !important; transition: all 0.2s ease !important;
}
button[kind="primary"]:hover { transform: translateY(-1px) !important; }
button[kind="secondary"] {
    background: var(--card-bg) !important; border: 1px solid var(--border-color) !important;
    color: var(--text-primary) !important; transition: all 0.2s ease !important;
}
button[kind="secondary"]:hover {
    background: var(--accent-light) !important; border-color: var(--accent) !important; color: var(--accent) !important;
}
.stExpander { border: 1px solid var(--border-color) !important; border-radius: 8px !important; }
.stTabs [data-baseweb="tab"] { color: var(--text-secondary) !important; }
.stTabs [aria-selected="true"] { color: var(--accent) !important; border-bottom-color: var(--accent) !important; }
div[data-testid="stDownloadButton"] button {
    background: var(--card-bg) !important; border: 1px solid var(--accent) !important; color: var(--accent) !important;
}
div[data-testid="stDownloadButton"] button:hover { background: var(--accent-light) !important; }
input[data-testid="stTextInputRootElement"] input, .stTextInput input {
    background: var(--input-bg) !important; border-color: var(--input-border) !important; color: var(--text-primary) !important;
}
.stTextInput input:focus {
    border-color: var(--accent) !important; box-shadow: 0 0 0 1px var(--accent) !important;
}
.footer-note { text-align: center; color: var(--text-tertiary); font-size: 0.75rem; padding: 1.5rem 0 0.5rem 0; }

/* Streamlit native element overrides for dark mode */
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 { color: var(--text-primary) !important; }
.stApp p, .stApp span, .stApp li, .stApp td, .stApp th { color: var(--text-primary); }
.stApp .stMarkdown { color: var(--text-primary); }
.stApp [data-testid="stExpander"] { background: var(--card-bg) !important; border-color: var(--border-color) !important; color: var(--text-primary) !important; }
.stApp .stDataFrame, .stApp [data-testid="stTable"] { background: var(--card-bg); }
.stApp [data-testid="stTable"] td { color: var(--text-primary); }
.stApp [data-testid="stMetric"] { background: var(--card-bg); border-radius: 8px; padding: 0.5rem; }
.stApp [data-testid="stCaptionContainer"] { color: var(--text-tertiary); }
.stApp [data-testid="stNotification"] { background: var(--card-bg); color: var(--text-primary); }
.stApp hr { border-color: var(--border-color); }
.stApp .stAlert { background: var(--card-bg); color: var(--text-primary); }
.stApp [data-testid="stSidebar"] .stMarkdown { color: var(--text-primary); }
.stApp [data-baseweb="select"] { background: var(--input-bg); color: var(--text-primary); }
.stApp [data-baseweb="input"] { background: var(--input-bg); color: var(--text-primary); }
.stApp [data-baseweb="popover"] { background: var(--card-bg); }
"""

st.markdown(f"<style>html.light {{{_LIGHT_VARS}}} html.dark {{{_DARK_VARS}}} {_LIGHT_STREAMLIT_OVERRIDES} {_BASE_CSS}</style>", unsafe_allow_html=True)

# ── Sidebar content ──────────────────────────────────────────────────────────
with st.sidebar:
    render_sidebar()

# ── Top navigation bar (replaces sidebar) ──
col_toggle, col_brand, col_nav, col_search, col_theme = st.columns([0.15, 1, 1.5, 2, 0.5])
with col_toggle:
    components.html("""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body {
        height: 100%; background: transparent;
        display: flex; align-items: center; justify-content: center;
      }
      .toggle-btn {
        background: #f8f9fa;
        border: 1px solid #d0d0d0;
        border-radius: 6px;
        cursor: pointer;
        font-size: 18px;
        width: 34px;
        height: 34px;
        color: #333;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.15s;
        padding: 0;
        line-height: 1;
        user-select: none;
        -webkit-user-select: none;
      }
      .toggle-btn:hover {
        background: #fff5f0;
        border-color: #e85d04;
        color: #e85d04;
      }
      .toggle-btn:active { transform: scale(0.93); }
    </style>
    </head>
    <body>
    <button class="toggle-btn" id="toggleBtn" title="展开/收起侧边栏">☰</button>
    <script>
    document.getElementById('toggleBtn').addEventListener('click', function(e) {
        e.preventDefault();
        var d = window.parent.document;
        // Try both Streamlit native toggle buttons
        var btn = d.querySelector('button[data-testid="stSidebarCollapseButton"]');
        if (!btn) btn = d.querySelector('button[data-testid="collapsedControl"]');
        if (!btn) btn = d.querySelector('[data-testid="stSidebarCollapsedControl"]');
        if (btn) {
            btn.click();
        } else {
            // Last fallback: click the sidebar section itself to trigger Streamlit
            var sidebar = d.querySelector('section[data-testid="stSidebar"]');
            if (sidebar) {
                var arrow = sidebar.querySelector('button');
                if (arrow) arrow.click();
            }
        }
    });
    </script>
    </body>
    </html>
    """, height=44)
with col_brand:
    st.markdown("""
    <div style="padding-top:0.1rem;">
        <span style="font-size:1.1rem; font-weight:800; color:var(--accent);">AStock</span>
        <span style="font-size:1.1rem; font-weight:800; color:var(--brand-text);"> Pro</span>
        <br>
        <a href="https://github.com/zhzshuai-create" target="_blank" style="font-size:0.65rem; color:var(--text-tertiary); text-decoration:none;" onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color='var(--text-tertiary)'">github.com/zhzshuai-create</a>
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

with col_theme:
    components.html("""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { height: 100%; background: transparent; display: flex; align-items: center; justify-content: center; }
      .theme-toggle { display: flex; gap: 2px; background: #e9ecef; border-radius: 8px; padding: 2px; }
      .theme-btn {
        width: 30px; height: 28px; border: none; border-radius: 6px;
        cursor: pointer; font-size: 14px;
        display: flex; align-items: center; justify-content: center;
        transition: all 0.12s ease; line-height: 1;
      }
      .theme-btn[data-theme="light"] { background: #fff; color: #333; }
      .theme-btn[data-theme="dark"]  { background: #111; color: #fff; }
      .theme-btn.active { box-shadow: 0 0 0 2px rgba(232,93,4,0.6); }
      .theme-btn:not(.active):hover { box-shadow: 0 0 0 2px rgba(232,93,4,0.25); }
    </style>
    </head>
    <body>
    <div class="theme-toggle" id="themeToggle">
      <button class="theme-btn" data-theme="light" title="亮色模式">☀️</button>
      <button class="theme-btn" data-theme="dark" title="暗色模式">🌙</button>
    </div>
    <script>
    var currentTheme = localStorage.getItem('astock-theme') || 'light';
    function updateUI(theme) {
        var btns = document.querySelectorAll('.theme-btn');
        btns.forEach(function(b) {
            b.classList.toggle('active', b.getAttribute('data-theme') === theme);
        });
    }
    updateUI(currentTheme);
    document.getElementById('themeToggle').addEventListener('click', function(e) {
        var btn = e.target.closest('.theme-btn');
        if (!btn) return;
        var theme = btn.getAttribute('data-theme');
        if (theme === currentTheme) return;
        currentTheme = theme;
        // Apply instantly — zero server round-trip
        window.parent.document.documentElement.className = theme;
        localStorage.setItem('astock-theme', theme);
        updateUI(theme);
    });
    </script>
    </body>
    </html>
    """, height=36)

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
            label, color, bg = _SIG.get(s, (f"⚪ {s}", "#444", "#f5f5f5"))
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
            <div style="color: #333; font-size: 0.82rem; margin-top: 0.2rem;">
                7位AI分析师 → 质量门控 → 多空辩论 → 风控评估 → 最终决策
            </div>
            <div style="margin-top: 0.5rem; font-size: 0.7rem; color: #ff5a1f; background: #fff5f0; display: inline-block; padding: 3px 12px; border-radius: 10px; border: 1px solid #ffccb0;">
                统一平台 · 2026-05-22
            </div>
        </div>
        """, unsafe_allow_html=True)

        left, right = st.columns([1, 1])

        # Left: history
        with left:
            st.markdown('<div style="font-weight:700;font-size:1.05rem;color:var(--text-primary); margin-bottom:0.4rem;">📊 历史分析记录</div>', unsafe_allow_html=True)

            full_history = get_history()
            history_search = st.text_input(
                "历史", placeholder="搜索股票代码或日期",
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
            st.markdown('<div style="font-weight:700;font-size:1.05rem;color:var(--text-primary); margin-bottom:0.4rem;">🔍 新建分析</div>', unsafe_allow_html=True)
            ticker = st.text_input("代码", placeholder="输入 6 位代码如 000636",
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
    <div style="text-align:center;margin-top:2rem;padding:0.8rem;color:var(--text-tertiary); font-size:0.75rem; border-top:1px solid var(--border-color);">
        ⚠️ 本项目仅供学习研究，不构成任何投资建议。
    </div>
    """, unsafe_allow_html=True)


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
        .interactive()
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
        .interactive()
    )


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

            # Back-to-overview button
            if st.button("← 返回市场总览", key="clear_stock", use_container_width=False):
                st.session_state.pop("data_code", None)
                st.rerun()

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
                            chg5_color = "#e03131" if chg5 > 0 else "#2f9e44"
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
                            chg_color = "#e03131" if chg > 0 else "#2f9e44"
                            st.markdown(f'30日涨幅: <span style="color:{chg_color};font-weight:700">{chg:+.2f}%</span>  |  日均成交量: {avg_vol/10000:.1f}万手', unsafe_allow_html=True)
                        else:
                            st.caption("暂无K线数据")

                    # ── 全部历史 ──────────────────────────────────
                    else:
                        with st.spinner("加载全部历史K线..."):
                            all_k = get_kline_data(code, days=5000)
                        if not all_k.empty:
                            close_s = all_k.set_index("datetime")["close"]
                            st.altair_chart(_price_chart(close_s), use_container_width=True)
                            closes_all = all_k["close"]
                            chg_all = (closes_all.iloc[-1] / closes_all.iloc[0] - 1) * 100 if len(closes_all) >= 2 else 0
                            chga_color = "#e03131" if chg_all > 0 else "#2f9e44"
                            st.markdown(f'上市至今: <span style="color:{chga_color};font-weight:700">{chg_all:+.2f}%</span>  |  共 {len(all_k)} 个交易日', unsafe_allow_html=True)
                        else:
                            st.caption("暂无全部历史K线数据")

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
                st.markdown(f"**题材热度 TOP 8:** {tag_html}", unsafe_allow_html=True)
            st.caption(f"共 {len(df_hot)} 只强势股  |  点击 📊 查看股票详情")
            for _, row in df_hot.iterrows():
                code = str(row.get("代码", ""))
                name = str(row.get("名称", ""))
                pct_val = row.get("涨幅%", 0)
                pct_color = "#e03131" if pct_val >= 0 else "#2f9e44"
                reason_text = str(row.get(reason_col, "")) if reason_col in row.index else ""

                c_cols = st.columns([1, 2, 1.5, 5, 1.2])
                with c_cols[0]:
                    st.markdown(f'<div style="padding-top:0.4rem;font-weight:700;color:var(--text-primary);">{code}</div>', unsafe_allow_html=True)
                with c_cols[1]:
                    st.markdown(f'<div style="padding-top:0.4rem;color:var(--text-secondary);">{name}</div>', unsafe_allow_html=True)
                with c_cols[2]:
                    st.markdown(f'<div style="padding-top:0.4rem;font-weight:700;color:{pct_color};">{pct_val:+.2f}%</div>', unsafe_allow_html=True)
                with c_cols[3]:
                    st.markdown(f'<div style="padding-top:0.4rem;color:var(--text-secondary);font-size:0.82rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{reason_text}</div>', unsafe_allow_html=True)
                with c_cols[4]:
                    if st.button("📊 查看", key=f"hot_{code}", use_container_width=True):
                        st.session_state["data_code"] = normalize_code(code)
                        st.toast(f"已选择 {name}({code})，切换到「📈 个股估值」标签页查看详情", icon="📊")
                        st.rerun()

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

    st.markdown('<div class="footer-note">AStock Pro · <a href="https://github.com/zhzshuai-create" target="_blank" style="color:var(--text-tertiary); text-decoration:none;">github.com/zhzshuai-create</a> | a-stock-data V3.1 | 数据仅供参考，不构成投资建议</div>', unsafe_allow_html=True)


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
