"""
AStock Pro · zhzshuai-create 定制版
AI多智能体分析 + 实时数据看板 | Powered by TradingAgents
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv


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
    index_spot,
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
# JS: Load saved theme + WebSocket auto-reconnect
# ═══════════════════════════════════════════════════════════════════════════════
components.html("""
<script>
(function(){
    var saved = localStorage.getItem('astock-theme') || 'auto';
    var resolved = saved === 'auto'
        ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
        : saved;
    document.documentElement.className = resolved;
    window.parent.document.documentElement.className = resolved;
})();
</script>
""", height=0)

# ── WebSocket auto-reconnect (robust: polling + visibility-change trigger) ──
components.html("""
<script>
// Multi-layered health-check reconnection:
// 1. Periodic polling (may be throttled when tab is backgrounded)
// 2. Instant check when user returns to the tab (visibilitychange/focus)
// 3. Streamlit "Connection lost" overlay detection
(function() {
    var HEALTH_URL = window.parent.location.origin + '/_stcore/health';
    var CHECK_INTERVAL = 5000;     // regular poll every 5s (throttled when hidden)
    var RECONNECT_AFTER = 2;       // 2 consecutive failures → reconnect
    var MAX_RETRIES = 20;          // give up after 20 reloads
    var failCount = 0;
    var reloadCount = 0;
    var lastOk = Date.now();

    function doReload() {
        if (reloadCount >= MAX_RETRIES) {
            return; // give up, user must manually refresh
        }
        reloadCount++;
        failCount = 0;
        window.parent.location.reload();
    }

    function check() {
        try {
            var xhr = new XMLHttpRequest();
            xhr.open('GET', HEALTH_URL, true);
            xhr.timeout = 3000;
            xhr.onload = function() {
                if (xhr.status === 200) {
                    failCount = 0;
                    reloadCount = 0;
                    lastOk = Date.now();
                } else {
                    failCount++;
                    if (failCount >= RECONNECT_AFTER) doReload();
                }
            };
            xhr.onerror = function() {
                failCount++;
                if (failCount >= RECONNECT_AFTER) doReload();
            };
            xhr.ontimeout = function() {
                failCount++;
                if (failCount >= RECONNECT_AFTER) doReload();
            };
            xhr.send(null);
        } catch(e) {
            failCount++;
            if (failCount >= RECONNECT_AFTER) doReload();
        }
    }

    // Layer 1: periodic polling
    setInterval(check, CHECK_INTERVAL);
    setTimeout(check, 3000);  // initial check after page loads

    // Layer 2: instant check when user returns to tab (NOT throttled)
    var handleVisibility = function() {
        if (!document.hidden) {
            // Tab just became visible — aggressive re-check
            // If last successful ping was > 30s ago, the connection is prob dead
            if (Date.now() - lastOk > 30000) {
                failCount = RECONNECT_AFTER; // force reconnect on next failed check
            }
            check();
        }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('focus', handleVisibility);

    // Layer 3: Streamlit "Connection lost" overlay — click "Try again" if visible
    setInterval(function() {
        try {
            var d = window.parent.document;
            // Streamlit's built-in reconnect prompt
            var alerts = d.querySelectorAll('[data-testid="stAlert"]');
            for (var i = 0; i < alerts.length; i++) {
                var text = alerts[i].textContent || '';
                if (text.indexOf('Connection') !== -1 || text.indexOf('reconnect') !== -1) {
                    // Click the "Try again" or reload button
                    var btn = alerts[i].querySelector('button');
                    if (btn) btn.click();
                    else doReload();
                }
            }
        } catch(e) {}
    }, 3000);
})();
</script>
""", height=0)

# ═══════════════════════════════════════════════════════════════════════════════
# CSS — Single Source of Truth (web/theme.py)
# ═══════════════════════════════════════════════════════════════════════════════

from web.theme import CSS
from streamlit_autorefresh import st_autorefresh

st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

# ── Autorefresh for header index quotes ──
def _is_trading_time() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return (9 * 60 + 30 <= t <= 11 * 60 + 30) or (13 * 60 <= t <= 15 * 60 + 5)

_auto_interval = 45 if _is_trading_time() else 3600
st_autorefresh(interval=_auto_interval * 1000, key="idx_autorefresh")


# ── Sidebar content ──────────────────────────────────────────────────────────
with st.sidebar:
    render_sidebar()

# ── Top navigation bar ──
# 单行：logo | segmented nav | index quotes | theme
col_logo, col_nav, col_index, col_theme = st.columns([1, 2.2, 3, 0.7], vertical_alignment="center")
with col_logo:
    st.markdown("""
    <span class="brand-logo">AStock</span>
    <span style="font-size:var(--font-lg); font-weight:800; color:var(--text);"> Pro</span>
    """, unsafe_allow_html=True)
    import os as _os
    _prov = (st.session_state.get("llm_provider")
             or _os.getenv("LLM_PROVIDER", "deepseek")).upper()
    _model = (st.session_state.get("quick_think_llm")
              or _os.getenv("QUICK_THINK_LLM", "")).split("/")[-1]
    _model = _model or "未配置"
    _par = " · 并行" if st.session_state.get("parallel_analysts") else ""
    st.markdown(
        f'<span class="model-badge">⚡ {_prov} · {_model}{_par}</span>',
        unsafe_allow_html=True,
    )
    st.markdown("""
    <style>
    .model-badge {
      font-size: 0.72rem; color: var(--muted);
      border: 1px solid var(--muted); border-radius: 999px;
      padding: 0.05rem 0.5rem; white-space: nowrap;
    }
    </style>
    """, unsafe_allow_html=True)
with col_nav:
    mode = st.segmented_control(
        "模式",
        ["AI分析报告", "实时数据看板"],
        default="AI分析报告" if st.session_state.get("app_mode") == "analysis" else "实时数据看板",
        key="top_mode", label_visibility="collapsed",
    )
    if mode and "AI分析" in mode and st.session_state.get("app_mode") != "analysis":
        st.session_state["app_mode"] = "analysis"
        st.rerun()
    elif mode and "数据看板" in mode and st.session_state.get("app_mode") != "data":
        st.session_state["app_mode"] = "data"
        st.rerun()

with col_index:
    _indices = index_spot()
    _order = [("000001", "上证指数"), ("399001", "深证成指"), ("399006", "创业板指")]
    _parts = []
    for i, (code, label) in enumerate(_order):
        d = _indices.get(code) if _indices else None
        if d and d.get("price", 0) > 0:
            pct = d.get("change_pct", 0)
            if pct > 0:
                arrow = "↑"
                cls = "up"
            elif pct < 0:
                arrow = "↓"
                cls = "down"
            else:
                arrow = ""
                cls = "flat"
            _parts.append(
                f'<div class="index-item">'
                f'<span class="index-name">{d["name"]}</span>'
                f'<span class="index-price">{d["price"]:.2f}</span>'
                f'<span class="index-change {cls}">{arrow}{pct:+.2f}%</span>'
                f'</div>'
            )
        else:
            _parts.append(
                f'<div class="index-item">'
                f'<span class="index-name">{label}</span>'
                f'<span class="index-price">--</span>'
                f'<span class="index-change flat">--</span>'
                f'</div>'
            )
        if i < 2:
            _parts.append('<div class="index-sep"></div>')
    if not _is_trading_time():
        _parts.append('<span class="index-closed-tag">已收盘</span>')
    st.markdown(f'<div class="index-bar">{"".join(_parts)}</div>', unsafe_allow_html=True)

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
        cursor: pointer; font-size: 12px; font-weight: 600;
        display: flex; align-items: center; justify-content: center;
        line-height: 1; background: transparent; color: #888;
        transition: all 0.12s ease;
      }
      .theme-btn:hover { color: #333; background: #ddd; }
      .theme-btn.active { background: #e85d04; color: #fff; }
    </style>
    </head>
    <body>
    <div class="theme-toggle" id="themeToggle">
      <button class="theme-btn" data-theme="light" title="亮色模式">亮</button>
      <button class="theme-btn" data-theme="dark" title="暗色模式">暗</button>
      <button class="theme-btn" data-theme="auto" title="跟随系统">A</button>
    </div>
    <script>
    var currentTheme = localStorage.getItem('astock-theme') || 'auto';
    function resolveTheme(t) {
        return t === 'auto'
            ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
            : t;
    }
    function applyTheme(t) {
        var r = resolveTheme(t);
        // Apply to both iframe and parent — Streamlit renders CSS in main doc
        document.documentElement.className = r;
        window.parent.document.documentElement.className = r;
    }
    function updateUI(theme) {
        var btns = document.querySelectorAll('.theme-btn');
        btns.forEach(function(b) {
            b.classList.toggle('active', b.getAttribute('data-theme') === theme);
        });
    }
    applyTheme(currentTheme);
    updateUI(currentTheme);
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', function() {
        if (currentTheme === 'auto') applyTheme('auto');
    });
    document.getElementById('themeToggle').addEventListener('click', function(e) {
        var btn = e.target.closest('.theme-btn');
        if (!btn) return;
        var theme = btn.getAttribute('data-theme');
        if (theme === currentTheme) return;
        currentTheme = theme;
        applyTheme(theme);
        localStorage.setItem('astock-theme', theme);
        updateUI(theme);
    });
    </script>
    </body>
    </html>
    """, height=36)

_q_style = """
<style>
.quote-bar {
  text-align: center; font-size: var(--font-md);
  padding: 0.15rem 0 0.35rem; letter-spacing: 0.02em;
}
.quote-link {
  color: var(--muted); text-decoration: none;
  transition: color 0.15s ease; cursor: pointer;
}
.quote-link:hover { color: var(--brand); }
</style>
"""
_q_date = datetime.now().timetuple().tm_yday
_QUOTES = [
    ("别人贪婪时我恐惧，别人恐惧时我贪婪。", "沃伦·巴菲特"),
    ("价格是你付出的，价值是你得到的。", "沃伦·巴菲特"),
    ("股市是一种把钱从没耐心的人转移到有耐心的人手中的装置。", "沃伦·巴菲特"),
    ("时间是好生意的朋友，是平庸生意的敌人。", "沃伦·巴菲特"),
    ("只有退潮的时候，你才知道谁在裸泳。", "沃伦·巴菲特"),
    ("市场短期是投票机，长期是称重机。", "本杰明·格雷厄姆"),
    ("投资的风险不在于市场，而在于投资者自身。", "本杰明·格雷厄姆"),
    ("你无法预测，但你可以准备。", "霍华德·马克斯"),
    ("如果你知道自己会死在哪里，你就永远不要去那里。", "查理·芒格"),
    ("反过来想，总是反过来想。", "查理·芒格"),
    ("华尔街没有新鲜事，因为人性永远不变。", "杰西·利弗莫尔"),
    ("知道你拥有什么，并且知道你为什么拥有它。", "彼得·林奇"),
    ("不积跬步，无以至千里；不积小流，无以成江海。", "《荀子》"),
    ("知人者智，自知者明。", "《道德经》"),
    ("谋定而后动，知止而有得。", "《孙子兵法》"),
    ("工欲善其事，必先利其器。", "《论语》"),
    ("胜兵先胜而后求战，败兵先战而后求胜。", "《孙子兵法》"),
    ("人弃我取，人取我与。", "《史记·货殖列传》"),
]

# 名言来源：内置 Python 名言库（_QUOTES）。
# 默认按当天日期轮换（同一天固定一句，刷新不闪变）；
# 点击名言 → URL 带 ?q=序号 重载，显示库里下一句（点击循环切换）。
_qp = st.query_params.get("q")
if _qp is not None and _qp.isdigit():
    _q_idx = int(_qp) % len(_QUOTES)
else:
    _q_idx = _q_date % len(_QUOTES)
_q_text, _q_author = _QUOTES[_q_idx]
_next_idx = (_q_idx + 1) % len(_QUOTES)
st.markdown(
    _q_style
    + f'<div class="quote-bar">'
      f'<a class="quote-link" href="/?q={_next_idx}" title="点击换一句">'
      f'“{_q_text}”　—— {_q_author}</a></div>',
    unsafe_allow_html=True,
)
st.markdown("---")


# ═══════════════════════════════════════════════════════════════════════════════
# Config helper (AI mode)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_config() -> dict:
    import os
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = st.session_state.get("llm_provider") or os.getenv("LLM_PROVIDER", "deepseek")
    config["deep_think_llm"] = st.session_state.get("deep_think_llm") or os.getenv("DEEP_THINK_LLM", "deepseek-chat")
    config["quick_think_llm"] = st.session_state.get("quick_think_llm") or os.getenv("QUICK_THINK_LLM", "deepseek-chat")
    base_url = st.session_state.get("llm_base_url") or os.getenv("BACKEND_URL")
    if base_url:
        config["backend_url"] = base_url
    config["data_vendors"] = {
        "core_stock_apis": "a_stock", "technical_indicators": "a_stock",
        "fundamental_data": "a_stock", "news_data": "a_stock", "signal_data": "a_stock",
    }
    config["parallel_analysts"] = bool(st.session_state.get("parallel_analysts"))
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
        run_config = _build_config()
        tracker = ProgressTracker(
            ticker=start_req["ticker"], trade_date=start_req["trade_date"],
        )
        tracker.parallel = bool(run_config.get("parallel_analysts"))
        st.session_state["tracker"] = tracker
        run_analysis_in_thread(
            ticker=start_req["ticker"], trade_date=start_req["trade_date"],
            config=run_config, tracker=tracker,
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
        render_progress(tracker, parallel=getattr(tracker, "parallel", False))
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
        # 结构批：信号→标签文案（class 映射见 _TAG_CLASS）
        _SIG = {
            "Buy": "🟢 买入",
            "Sell": "🔴 卖出",
            "Hold": "🟡 持有",
        }

        # 结构批：标签 class 映射——Buy→tag--buy, Sell→tag--sell, Hold→tag--na(TODO), N/A→tag--na
        _TAG_CLASS = {
            "Buy": "tag--buy",
            "Sell": "tag--sell",
            "Hold": "tag--na",   # TODO: 第二批新增 .tag--hold 后改为 tag--hold
            "N/A": "tag--na",
        }

        @st.cache_data(ttl=3600, show_spinner=False)
        def _signal_for(path: str) -> str:
            try:
                return extract_signal(load_analysis(path))
            except Exception:
                return "N/A"

        def _badge(s: str) -> str:
            """结构批：返回 class 化标签 HTML，零内联样式 → 引用 .tag .tag--*"""
            label = _SIG.get(s, f"⚪ {s}")
            tag_cls = _TAG_CLASS.get(s, "tag--na")
            return f'<span class="tag {tag_cls}">{label}</span>'

        # Banner
        st.markdown("""
        <div class="banner">
            <div class="banner__title">TradingAgents-Astock</div>
            <div style="color:var(--muted);font-size:var(--font-sm);margin-top:2px;">v2026-05-22 · 7位AI分析师 → 多空辩论 → 风控评估 → 投资决策</div>
        </div>
        """, unsafe_allow_html=True)

        # 左宽右窄：左栏列表，右栏表单限宽 520px
        left, right = st.columns([3, 2])

        # Left: history（折叠收纳：点击展开/收起，节约空间）
        with left:
            st.markdown('<div class="card__title">历史记录</div>', unsafe_allow_html=True)
            full_history = get_history()
            with st.expander(f"📜 历史分析记录（{len(full_history)} 条）", expanded=False):
                history_search = st.text_input(
                    "历史", placeholder="筛选历史",
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
                        # 结构批：st.columns 原生处理行布局，badge 走 .tag class
                        c1, c2 = st.columns([2.2, 1])
                        with c1:
                            if st.button(f"{t}  ·  {d}", key=f"main_hist_{t}_{d}", use_container_width=True):
                                st.session_state["viewing_history"] = p
                                st.session_state["start_analysis"] = None
                                st.rerun()
                        with c2:
                            st.markdown(f'<div>{badge_html}</div>', unsafe_allow_html=True)

        # Right: new analysis
        with right:
            st.markdown('<div class="card__title">新建分析</div>', unsafe_allow_html=True)
            c_code, c_date = st.columns([2, 1])
            with c_code:
                ticker = st.text_input("代码", placeholder="输入 6 位代码如 000636",
                                       max_chars=6, label_visibility="collapsed",
                                       key="idle_ticker")
            with c_date:
                trade_date = st.date_input("分析日期", label_visibility="collapsed")
            can_start = bool(ticker and len(ticker.strip()) >= 4)
            st.button("开始分析", type="primary", disabled=not can_start,
                      on_click=lambda: st.session_state.update({
                          "start_analysis": {"ticker": ticker.strip(), "trade_date": trade_date.strftime("%Y-%m-%d")},
                          "viewing_history": None,
                      }))

            # ── 快捷标的：历史标的一键回填 ──
            quick_codes = []
            seen = set()
            for e in full_history:
                if e["ticker"] not in seen:
                    seen.add(e["ticker"])
                    quick_codes.append(e["ticker"])
                if len(quick_codes) >= 6:
                    break
            if quick_codes:
                st.markdown(
                    '<div style="font-size:var(--font-sm);color:var(--muted);'
                    'margin:var(--space-md) 0 var(--space-xs);">⚡ 快捷标的</div>',
                    unsafe_allow_html=True,
                )
                qc = st.columns(min(len(quick_codes), 3))
                for i, qcode in enumerate(quick_codes):
                    with qc[i % min(len(quick_codes), 3)]:
                        if st.button(qcode, key=f"quick_{qcode}", use_container_width=True):
                            st.session_state["idle_ticker"] = qcode
                            st.rerun()

            # ── 历史信号分布 ──
            if full_history:
                dist = {"Buy": 0, "Hold": 0, "Sell": 0}
                other = 0
                for e in full_history[:50]:
                    sig = _signal_for(e["path"])
                    if sig in dist:
                        dist[sig] += 1
                    elif sig != "N/A":
                        other += 1
                total_sig = sum(dist.values())
                if total_sig:
                    st.markdown(
                        '<div style="font-size:var(--font-sm);color:var(--muted);'
                        'margin:var(--space-md) 0 var(--space-xs);">📊 历史信号分布（近 '
                        f'{min(len(full_history), 50)} 次）</div>',
                        unsafe_allow_html=True,
                    )
                    seg = []
                    colors = {"Buy": "var(--up)", "Hold": "var(--hold)", "Sell": "var(--sell)"}
                    for k in ("Buy", "Hold", "Sell"):
                        if dist[k]:
                            seg.append(f'<div style="flex:{dist[k]};background:{colors[k]};" '
                                       f'title="{k}: {dist[k]}"></div>')
                    st.markdown(
                        f'<div style="display:flex;height:10px;border-radius:999px;overflow:hidden;'
                        f'border:1px solid var(--line);">{"".join(seg)}</div>',
                        unsafe_allow_html=True,
                    )
                    st.caption(f"买入 {dist['Buy']} · 持有 {dist['Hold']} · 卖出 {dist['Sell']}"
                               + (f" · 其他 {other}" if other else ""))

            # ── 系统状态 ──
            import os as _os
            try:
                from importlib.metadata import version as _pkg_version
                _ver = _pkg_version("tradingagents-astock")
            except Exception:
                _ver = "0.2.18"
            _prov = (st.session_state.get("llm_provider")
                     or _os.getenv("LLM_PROVIDER", "deepseek")).upper()
            _model = (st.session_state.get("deep_think_llm")
                      or _os.getenv("DEEP_THINK_LLM", "")).split("/")[-1] or "未配置"
            _par = "并行 ⚡" if st.session_state.get("parallel_analysts") else "串行"
            _mode_color = "var(--brand)" if st.session_state.get("parallel_analysts") else "var(--muted)"
            st.markdown(
                '<div style="font-size:var(--font-sm);color:var(--muted);'
                'margin:var(--space-md) 0 var(--space-xs);">🖥️ 系统状态</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div style="font-size:var(--font-sm);color:var(--muted);line-height:1.9;">'
                f'模型：<b style="color:var(--text);">{_prov} · {_model}</b><br>'
                f'编排：<b style="color:{_mode_color};">{_par}</b><br>'
                f'版本：v{_ver}</div>',
                unsafe_allow_html=True,
            )

    # Footer
    st.markdown("""
    <div class="footer-note">
        本项目仅供学习研究，不构成任何投资建议。
    </div>
    """, unsafe_allow_html=True)



from web.components.data_dashboard import render_data_mode  # noqa: E402
# ═══════════════════════════════════════════════════════════════════════════════
# Main dispatch
# ═══════════════════════════════════════════════════════════════════════════════

main = st.empty()
if st.session_state.get("app_mode") == "analysis":
    with main.container():
        _render_analysis_mode()
else:
    with main.container():
        render_data_mode()
