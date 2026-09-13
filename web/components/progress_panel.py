"""Real-time progress display for the analysis pipeline."""

from __future__ import annotations

import streamlit as st

from web.progress import PIPELINE_STAGES, ProgressTracker

_CSS = """
<style>
@keyframes pp-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(255, 90, 31, 0.45); }
  70%  { box-shadow: 0 0 0 10px rgba(255, 90, 31, 0); }
  100% { box-shadow: 0 0 0 0 rgba(255, 90, 31, 0); }
}
.pp-dot {
  display: inline-flex; align-items: center; justify-content: center;
  width: 1.35rem; height: 1.35rem; border-radius: 50%;
  font-size: 0.85rem; font-weight: 700; line-height: 1;
}
.pp-done  { background: var(--up); color: #fff; }
.pp-active{ background: var(--brand); color: #fff; animation: pp-pulse 1.6s infinite; }
.pp-pending{ border: 1.6px solid var(--muted); color: var(--muted); }
.pp-name { font-size: 0.78rem; }
.pp-name-done { color: var(--up); }
.pp-name-active { color: var(--text); font-weight: 700; }
.pp-name-pending { color: var(--muted); }
.pp-parallel {
  display: inline-block; padding: 0.1rem 0.55rem; border-radius: 999px;
  border: 1px solid var(--brand); color: var(--brand);
  font-size: 0.78rem; margin-left: 0.6rem; vertical-align: middle;
}
</style>
"""


def _badge(status: str) -> str:
    if status == "done":
        return '<span class="pp-dot pp-done">✓</span>'
    if status == "active":
        return '<span class="pp-dot pp-active">●</span>'
    return '<span class="pp-dot pp-pending">○</span>'


def _name_class(status: str) -> str:
    return {
        "done": "pp-name pp-name-done",
        "active": "pp-name pp-name-active",
    }.get(status, "pp-name pp-name-pending")


def _stage_columns(cols, stages, tracker):
    for col, stage in zip(cols, stages):
        status = tracker.stage_status(stage["id"])
        col.markdown(
            f"""
            <div style="text-align:center; padding:0.5rem 0;">
                {_badge(status)}<br>
                <span class="{_name_class(status)}">{stage['name']}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def render_progress(tracker: ProgressTracker, parallel: bool = False) -> None:
    """Render the pipeline progress panel."""

    st.markdown(_CSS, unsafe_allow_html=True)

    parallel_badge = '<span class="pp-parallel">⚡ 并行模式</span>' if parallel else ""
    st.markdown(
        f"""
        <div style="text-align:center; margin:1rem 0 0.5rem;">
            <span style="font-size:1.6rem; font-weight:700; color:var(--text);">
                分析进行中
            </span>
            <span style="font-size:1.1rem; color:var(--muted); margin-left:0.8rem;">
                {tracker.ticker}
            </span>
            {parallel_badge}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if tracker.stop_requested:
        st.caption("正在停止当前分析并清空内容；收尾完成后可重新开始。")
        return

    if tracker.is_paused:
        st.caption("当前分析已暂停。")

    completed = len(tracker.completed_stages)
    total = len(PIPELINE_STAGES)
    pct = completed / total if total else 0
    st.progress(pct, text=f"{completed}/{total} 阶段完成  ·  {_format_time(tracker.elapsed)}")

    analyst_stages = PIPELINE_STAGES[:7]
    post_stages = PIPELINE_STAGES[7:]

    st.markdown(
        '<div style="margin:0.5rem 0 0.3rem; font-size:0.85rem; color:var(--muted);">ANALYSTS</div>',
        unsafe_allow_html=True,
    )
    _stage_columns(st.columns(len(analyst_stages)), analyst_stages, tracker)

    st.markdown(
        '<div style="margin:0.8rem 0 0.3rem; font-size:0.85rem; color:var(--muted);">PIPELINE</div>',
        unsafe_allow_html=True,
    )
    _stage_columns(st.columns(len(post_stages)), post_stages, tracker)

    st.markdown("---")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("LLM 调用", tracker.llm_calls)
    c2.metric("工具调用", tracker.tool_calls)
    c3.metric("输入 Tokens", f"{tracker.tokens_in:,}")
    c4.metric("输出 Tokens", f"{tracker.tokens_out:,}")

    if tracker.error:
        st.error(f"错误: {tracker.error}")

    completed_reports = [
        (stage["name"], stage["icon"], tracker.stage_reports[stage["id"]])
        for stage in PIPELINE_STAGES
        if stage["id"] in tracker.stage_reports
    ]

    if completed_reports:
        st.markdown(
            '<div style="margin:0.5rem 0 0.3rem; font-size:0.85rem; color:var(--muted);">'
            f"REPORTS ({len(completed_reports)})</div>",
            unsafe_allow_html=True,
        )
        for name, icon, report in reversed(completed_reports):
            is_latest = (name == completed_reports[-1][0])
            with st.expander(f"{icon} {name}", expanded=is_latest):
                st.markdown(report[:3000])
