"""交易日志模式 — 以 iframe 嵌入独立的 trade-journal Streamlit 应用 (localhost:8502)。

零侵入: 本模块不读写 trade-journal 的任何代码或数据 (data/ 隐私隔离由其自身负责),
仅通过 URL 回显。若 8502 未启动, 给出启动引导而不是白屏。
"""
from __future__ import annotations

import socket
import urllib.request

import streamlit as st
import streamlit.components.v1 as components

JOURNAL_HOST = "localhost"
JOURNAL_PORT = 8502
JOURNAL_URL = f"http://{JOURNAL_HOST}:{JOURNAL_PORT}"


def _journal_alive() -> bool:
    """探测 8502 上的交易日志是否在跑 (先 TCP 再取健康端点, 短超时)。"""
    try:
        with socket.create_connection((JOURNAL_HOST, JOURNAL_PORT), timeout=0.5):
            pass
    except OSError:
        return False
    try:
        with urllib.request.urlopen(f"{JOURNAL_URL}/_stcore/health", timeout=1.0) as r:
            return r.status == 200
    except Exception:
        # TCP 通了但健康端点没回 200, 仍认为进程在 (可能刚启动), 交给 iframe 重连
        return True


def render_journal_mode() -> None:
    st.subheader("📖 交易日志 · 复盘看板")
    st.caption(
        "这是独立运行的 trade-journal 应用 (localhost:8502), 以 iframe 嵌入。"
        "资金曲线点击联动、持仓周期/仓位集中度/收益分布等指标都在下方。"
    )
    if not _journal_alive():
        st.warning(
            f"⚠️ 未检测到交易日志服务 ({JOURNAL_URL})。\n\n"
            "请先启动它, 再回到本页刷新：\n"
            "- 一键同时启动平台+日志: 运行平台根目录的 `run_all.bat`\n"
            "- 或单独启动日志: 在 `trade-journal/` 下运行 `run.bat` (已固定 8502 端口)"
        )
        return
    components.iframe(JOURNAL_URL, height=1800, scrolling=True)
