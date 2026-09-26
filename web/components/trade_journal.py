"""交易日志模式 — 以 iframe 嵌入独立的 trade-journal Streamlit 应用 (localhost:8502)。

零侵入: 本模块不读写 trade-journal 的任何代码或数据 (data/ 隐私隔离由其自身负责),
仅通过 URL 回显。8502 未启动时原地自动拉起(懒加载); 失败回落到手动引导, 不白屏。
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from web import journal_service


def render_journal_mode() -> None:
    st.subheader("📖 交易日志 · 复盘看板")
    st.caption(
        "这是独立运行的 trade-journal 应用 (localhost:8502), 以 iframe 嵌入。"
        "资金曲线点击联动、持仓周期/仓位集中度/收益分布等指标都在下方。"
    )
    if not journal_service.journal_alive():
        with st.spinner("首次打开, 正在启动交易日志服务…"):
            proc = journal_service.start_journal()
            if proc is None or not journal_service.wait_ready():
                st.warning(
                    f"⚠️ 交易日志服务自动启动失败 ({journal_service.JOURNAL_URL})。\n\n"
                    "请手动启动后回到本页刷新：\n"
                    "- 一键同时启动平台+日志: 运行平台根目录的 `run_all.bat`\n"
                    "- 或单独启动日志: 在 `trade-journal/` 下运行 `run.bat` (已固定 8502 端口)"
                )
                return
    components.iframe(journal_service.JOURNAL_URL, height=1800, scrolling=True)
