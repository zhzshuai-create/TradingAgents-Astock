"""Real-time progress display for the analysis pipeline."""

from __future__ import annotations

import streamlit as st

from web.progress import PIPELINE_STAGES, ProgressTracker


def _status_badge(status: str) -> str:
    if status == "done":
        return '<span style="color:#22c55e; font-size:1.3rem;">●</span>'
    if status == "active":
        return '<span style="color:#ff5a1f; font-size:1.3rem;">◉</span>'
    return '<span style="color:#333; font-size:1.3rem;">○</span>'


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def render_progress(tracker: ProgressTracker) -> None:
    """Render the pipeline progress panel."""

    st.markdown(
        f"""
        <div style="text-align:center; margin:1rem 0 0.5rem;">
            <span style="font-size:1.6rem; font-weight:700; color:#f5f1eb;">
                分析进行中
            </span>
            <span style="font-size:1.1rem; color:#888; margin-left:0.8rem;">
                {tracker.ticker}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    completed = len(tracker.completed_stages)
    total = len(PIPELINE_STAGES)
    pct = completed / total if total else 0
    st.progress(pct, text=f"{completed}/{total} 阶段完成  ·  {_format_time(tracker.elapsed)}")

    analyst_stages = PIPELINE_STAGES[:7]
    post_stages = PIPELINE_STAGES[7:]

    st.markdown(
        '<div style="margin:0.5rem 0 0.3rem; font-size:0.85rem; color:#888;">ANALYSTS</div>',
        unsafe_allow_html=True,
    )

    cols = st.columns(len(analyst_stages))
    for col, stage in zip(cols, analyst_stages):
        status = tracker.stage_status(stage["id"])
        badge = _status_badge(status)
        label_color = "#f5f1eb" if status == "active" else "#888" if status == "pending" else "#22c55e"
        col.markdown(
            f"""
            <div style="text-align:center; padding:0.5rem 0;">
                {badge}<br>
                <span style="font-size:0.75rem; color:{label_color};">{stage['name']}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div style="margin:0.8rem 0 0.3rem; font-size:0.85rem; color:#888;">PIPELINE</div>',
        unsafe_allow_html=True,
    )

    cols2 = st.columns(len(post_stages))
    for col, stage in zip(cols2, post_stages):
        status = tracker.stage_status(stage["id"])
        badge = _status_badge(status)
        label_color = "#f5f1eb" if status == "active" else "#888" if status == "pending" else "#22c55e"
        col.markdown(
            f"""
            <div style="text-align:center; padding:0.5rem 0;">
                {badge}<br>
                <span style="font-size:0.75rem; color:{label_color};">{stage['name']}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("LLM 调用", tracker.llm_calls)
    c2.metric("工具调用", tracker.tool_calls)
    c3.metric("输入 Tokens", f"{tracker.tokens_in:,}")
    c4.metric("输出 Tokens", f"{tracker.tokens_out:,}")

    if tracker.error:
        st.error(f"错误: {tracker.error}")

    # ── Stall detection warning ──────────────────────────────────────────
    stall = tracker.stall_info(threshold_seconds=120)
    if stall:
        stage_map = {s["id"]: s["name"] for s in PIPELINE_STAGES}
        stuck_name = stage_map.get(stall["stalled_stage"], stall["stalled_stage"])
        stall_min = int(stall["stall_seconds"] // 60)
        stall_sec = int(stall["stall_seconds"] % 60)

        with st.container(border=True):
            st.markdown(f"""
            <div style="background:#fff8e6; border:1px solid #f0c040; border-radius:10px; padding:1rem 1.2rem; margin:0.8rem 0;">
                <div style="font-size:1rem; font-weight:700; color:#b06000; margin-bottom:0.5rem;">
                    ⚠️ 分析疑似卡死 — 已停滞 {stall_min}分{stall_sec:02d}秒
                </div>
                <div style="font-size:0.85rem; color:#555; line-height:1.7;">
                    当前阶段：<b>{stuck_name}</b> |
                    LLM调用 {stall['llm_calls']} 次 |
                    Token 消耗 {stall['tokens_in']:,} / {stall['tokens_out']:,}
                </div>
                <div style="font-size:0.82rem; color:#888; margin-top:0.6rem; line-height:1.8;">
                    <b>可能原因：</b><br>
                    &nbsp;&nbsp;1. LLM API 超时或限流（高峰时段常见）<br>
                    &nbsp;&nbsp;2. 网络不稳，请求挂起<br>
                    &nbsp;&nbsp;3. 数据源连接失败（mootdx / 东财接口）<br><br>
                    <b>建议操作：</b><br>
                    &nbsp;&nbsp;• 点击上方 <b>停止 + 重新开始</b> 分析<br>
                    &nbsp;&nbsp;• 在 <code>.env</code> 中切换到 <b>MiniMax</b> 替代 DeepSeek（高峰不限流）<br>
                    &nbsp;&nbsp;• 检查网络连接，确认能否访问 <code>api.deepseek.com</code>
                </div>
            </div>
            """, unsafe_allow_html=True)

    last_report = ""
    last_name = ""
    for stage in reversed(PIPELINE_STAGES):
        if stage["id"] in tracker.stage_reports:
            last_report = tracker.stage_reports[stage["id"]]
            last_name = stage["name"]
            break

    if last_report:
        with st.expander(f"最新完成: {last_name}", expanded=False):
            st.markdown(last_report[:3000])
