"""Sidebar: branding, search, and interactive history panel."""

from __future__ import annotations

import streamlit as st

from web.history import extract_signal, get_history, load_analysis


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_signal(path: str) -> str:
    try:
        return extract_signal(load_analysis(path))
    except Exception:
        return "N/A"


_SIGNAL_STYLE = {
    "Buy":    ("🟢 买入", "#22c55e", "#f0fdf4"),
    "Sell":   ("🔴 卖出", "#ef4444", "#fef2f2"),
    "Hold":   ("🟡 持有", "#f59e0b", "#fffbeb"),
}


def _signal_html(signal: str) -> str:
    label, color, bg = _SIGNAL_STYLE.get(signal, (f"⚪ {signal}", "#444", "#f5f5f5"))
    return (
        f'<span style="display:inline-block;font-size:0.7rem;font-weight:700;'
        f'color:{color};background:{bg};border:1px solid {color};'
        f'border-radius:4px;padding:2px 8px;white-space:nowrap;">{label}</span>'
    )


def render_sidebar() -> None:
    """Render the sidebar with branding, search, and analysis history."""

    # ── Branding ───────────────────────────────────────────────────────────
    st.markdown(
        """
        <div style="text-align:center; margin-bottom:1.5rem;">
            <span style="font-size:1.5rem; font-weight:800; color:#ff5a1f;">Trading</span><span style="font-size:1.5rem; font-weight:800; color:#1a1a1a;">Agents</span><span style="font-size:1.5rem; font-weight:800; color:#1a1a1a;">-</span><span style="font-size:1.5rem; font-weight:800; color:#ff5a1f;">Astock</span>
            <div style="font-size:0.8rem; color:#333; margin-top:0.2rem;">
                A股多Agent投研系统
            </div>
            <div style="font-size:0.65rem; color:#555; margin-top:0.3rem;">
                by simonlin1212
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # ── History section header ──────────────────────────────────────────────
    full_history = get_history()
    total = len(full_history)

    st.markdown(
        f"""
        <div style="display:flex; align-items:baseline; justify-content:space-between; margin-bottom:0.6rem;">
            <span style="font-weight:700; font-size:1.05rem; color:#1a1a1a;">
                &#x1F4CA; 分析记录
            </span>
            <span style="font-size:0.75rem; color:#555;">共 {total} 条</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Search input ───────────────────────────────────────────────────────
    search = st.text_input(
        "搜索",
        placeholder="搜索股票代码或日期（如 000636 或 2026-05）",
        label_visibility="collapsed",
        key="sidebar_history_search",
    )

    # Filter
    if search:
        q = search.strip().lower()
        history = [e for e in full_history if q in e["ticker"].lower() or q in e["date"]]
    else:
        history = full_history

    # ── Empty state ────────────────────────────────────────────────────────
    if not history:
        if search:
            st.info("没有匹配的记录")
        else:
            st.info("暂无分析记录")
            st.caption("在主页中央输入股票代码开始分析")
        st.markdown("---")
        st.caption("仅供学习研究，不构成投资建议")
        return

    # ── Record list ────────────────────────────────────────────────────────
    if search:
        st.caption(f"找到 {len(history)} 条匹配")
    elif total > 30:
        st.caption(f"显示最近 30 条（共 {total} 条）")

    max_items = 100 if search else 30
    for entry in history[:max_items]:
        t, d, p = entry["ticker"], entry["date"], entry["path"]
        signal = _cached_signal(p)
        badge = _signal_html(signal)

        # Build a richer label: ticker code prominent, date secondary
        label = f"{t}    ·    {d}"

        # Render each history item as a button with signal badge alongside
        c1, c2 = st.columns([2.2, 1])
        with c1:
            if st.button(label, key=f"hist_{t}_{d}", use_container_width=True):
                st.session_state["viewing_history"] = p
                st.session_state["start_analysis"] = None
        with c2:
            st.markdown(
                f'<div style="padding-top:6px;text-align:right;">{badge}</div>',
                unsafe_allow_html=True,
            )

    # ── Footer ─────────────────────────────────────────────────────────────
    st.markdown("---")
    st.caption("仅供学习研究，不构成投资建议")
