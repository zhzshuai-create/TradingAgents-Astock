"""Sidebar: stock input, LLM config, and history list."""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

import streamlit as st

from tradingagents.default_config import DEFAULT_CONFIG
from web.history import (
    clear_incomplete_task,
    get_history,
    get_incomplete_history,
    record_incomplete_task,
)

logger = logging.getLogger(__name__)

# 注意: checkpointer 与 model_catalog 不在这里导入 —— 它们会拉起整条 langgraph /
# langsmith 依赖链(实测约 3.2s), 而首屏遮罩要在 sidebar 导入之前上屏.
# 两者都只在函数体内用到, 见 _clear_analysis_artifacts / _render_llm_config.

# Provider display names in recommended order
_PROVIDERS: list[tuple[str, str]] = [
    ("小米 MiMo（国内直连）", "mimo"),
    ("NVIDIA NIM（免费·国内直连）", "nvidia"),
    ("MiniMax（推荐·国内直连）", "minimax"),
    ("DeepSeek", "deepseek"),
    ("通义千问 Qwen", "qwen"),
    ("智谱 GLM", "glm"),
    ("OpenAI", "openai"),
    ("Anthropic", "anthropic"),
    ("Google Gemini", "google"),
    ("xAI Grok", "xai"),
    ("OpenRouter（聚合·填 vendor/model 形式 ID）", "openrouter"),
    ("Ollama（本地）", "ollama"),
]

_PROVIDER_DISPLAY = [name for name, _ in _PROVIDERS]
_PROVIDER_KEYS = [key for _, key in _PROVIDERS]

# 模型选择写用户目录，不进包目录/仓库：pip 装的 site-packages 常只读，git clone
# 则会多出未跟踪文件。~/.tradingagents 已承载 logs/cache/memory。
_DEFAULT_LLM_CONFIG_PATH = (
    Path(os.path.expanduser("~")) / ".tradingagents" / "llm_config.json"
)
_LLM_CONFIG_PATH = _DEFAULT_LLM_CONFIG_PATH


def _load_saved_llm_config() -> dict:
    """把上次的模型选择填进 session_state 默认值；文件缺失/损坏时静默跳过。"""
    try:
        cfg = json.loads(_LLM_CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(cfg, dict):
        return {}

    provider_key = str(cfg.get("llm_provider") or "")
    if provider_key in _PROVIDER_KEYS:
        st.session_state.setdefault("llm_provider_idx", _PROVIDER_KEYS.index(provider_key))
    st.session_state.setdefault("llm_base_url", cfg.get("llm_base_url") or "")
    st.session_state.setdefault("parallel_analysts", bool(cfg.get("parallel_analysts", False)))
    for key in ("custom_quick_model", "custom_deep_model"):
        if cfg.get(key):
            st.session_state.setdefault(key, cfg[key])
    return cfg


def _saved_model_index(saved: dict, provider_key: str, key: str, values: list[str]) -> int:
    """按模型 ID 而不是旧下拉框索引恢复，模型目录顺序变化时不会串档。"""
    if str(saved.get("llm_provider") or "") != provider_key:
        return 0
    value = saved.get(key)
    return values.index(value) if value in values else 0


def _save_llm_config() -> None:
    """当前选择写入用户目录；写失败只告警，不打断分析主流程。"""
    cfg = {
        "llm_provider": st.session_state.get("llm_provider", ""),
        "quick_think_llm": st.session_state.get("quick_think_llm", ""),
        "deep_think_llm": st.session_state.get("deep_think_llm", ""),
        "llm_base_url": st.session_state.get("llm_base_url", ""),
        "parallel_analysts": bool(st.session_state.get("parallel_analysts", False)),
    }
    for key in ("custom_quick_model", "custom_deep_model"):
        val = st.session_state.get(key)
        if val:
            cfg[key] = val

    # 看板 running 态每 2s rerun，不能每次全量重写文件。
    if cfg == st.session_state.get("_llm_config_snapshot"):
        return
    try:
        _LLM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LLM_CONFIG_PATH.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        st.session_state["_llm_config_snapshot"] = cfg
    except OSError as exc:
        logger.warning("LLM 配置持久化失败（不影响本次分析）: %s", exc)


def _resolve_user_input(raw: str) -> tuple[str, str | None]:
    """Resolve raw user input to (ticker_code, error_msg).

    Accepts 6-digit codes or Chinese stock names (e.g. '宝光股份').
    Returns (code, None) on success or ("", error_msg) on failure.
    """
    from tradingagents.dataflows.a_stock import resolve_ticker

    try:
        code = resolve_ticker(raw)
        return code, None
    except ValueError as e:
        return "", str(e)


def _clear_analysis_artifacts(ticker: str, trade_date: str) -> None:
    from tradingagents.graph.checkpointer import clear_checkpoint

    clear_incomplete_task(ticker, trade_date)
    clear_checkpoint(DEFAULT_CONFIG["data_cache_dir"], ticker, trade_date)


def _render_analysis_controls(raw_ticker: str, trade_date_value: date) -> None:
    tracker = st.session_state.get("tracker")
    is_running = tracker is not None and tracker.is_running
    trade_date = trade_date_value.strftime("%Y-%m-%d")

    pause_col, resume_col, stop_col = st.columns(3)

    pause_disabled = not is_running or tracker.is_paused or tracker.stop_requested
    if pause_col.button(
        "暂停",
        key="sidebar_pause_analysis",
        use_container_width=True,
        disabled=pause_disabled,
    ):
        if tracker.pause():
            record_incomplete_task(
                tracker.ticker,
                tracker.trade_date,
                status="paused",
                completed_stages=list(tracker.completed_stages),
            )
        st.rerun()

    resume_disabled = not is_running or not tracker.is_paused or tracker.stop_requested
    if resume_col.button(
        "恢复",
        key="sidebar_resume_analysis",
        use_container_width=True,
        disabled=resume_disabled,
    ):
        if tracker.resume():
            record_incomplete_task(
                tracker.ticker,
                tracker.trade_date,
                status="running",
                completed_stages=list(tracker.completed_stages),
            )
        st.rerun()

    can_stop = tracker is not None or bool(raw_ticker.strip())
    if not can_stop:
        st.session_state.pop("confirm_stop", None)
    confirm_stop = bool(st.session_state.get("confirm_stop")) and can_stop
    stop_label = "确认停止？" if confirm_stop else "停止"
    if stop_col.button(
        stop_label,
        key="sidebar_stop_analysis",
        use_container_width=True,
        disabled=not can_stop,
        type="primary" if confirm_stop else "secondary",
    ):
        if not confirm_stop:
            st.session_state["confirm_stop"] = True
            st.rerun()
        st.session_state.pop("confirm_stop", None)
        target_ticker = tracker.ticker if tracker is not None and tracker.ticker else ""
        target_date = (
            tracker.trade_date
            if tracker is not None and tracker.trade_date
            else trade_date
        )

        if not target_ticker:
            target_ticker, err = _resolve_user_input(raw_ticker)
            if err:
                st.error(err)
                return

        if tracker is not None and tracker.is_running:
            tracker.request_stop()
            clear_incomplete_task(target_ticker, target_date)
        else:
            if tracker is not None:
                tracker.mark_stopped()
                st.session_state["tracker"] = None
            _clear_analysis_artifacts(target_ticker, target_date)

        st.session_state["viewing_history"] = None
        st.success("已清空当前进度；下一次开始分析会从头生成。")
        st.rerun()

    if tracker is not None and tracker.stop_requested:
        st.caption("正在停止并清空，收尾完成后可重新开始。")


def _render_llm_config(saved: dict | None = None) -> None:
    """Render LLM provider and model selection controls."""
    from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS

    saved = saved or {}

    # 默认选中跟随 .env 的 LLM_PROVIDER（未收录的供应商回退第 0 项），
    # 避免下拉框默认值把 .env 配置悄悄覆盖掉
    try:
        _env_default_idx = _PROVIDER_KEYS.index(
            os.getenv("LLM_PROVIDER", "").strip().lower()
        )
    except ValueError:
        _env_default_idx = 0
    provider_idx = st.selectbox(
        "LLM 供应商",
        range(len(_PROVIDERS)),
        index=_env_default_idx,
        format_func=lambda i: _PROVIDER_DISPLAY[i],
        key="llm_provider_idx",
        help="选择你配置了 API Key 的供应商",
    )
    provider_key = _PROVIDER_KEYS[provider_idx]
    st.session_state["llm_provider"] = provider_key

    if provider_key in MODEL_OPTIONS:
        quick_options = MODEL_OPTIONS[provider_key]["quick"]
        deep_options = MODEL_OPTIONS[provider_key]["deep"]

        quick_labels = [label for label, _ in quick_options]
        quick_values = [value for _, value in quick_options]
        deep_labels = [label for label, _ in deep_options]
        deep_values = [value for _, value in deep_options]

        quick_idx = st.selectbox(
            "快速思考模型",
            range(len(quick_options)),
            index=_saved_model_index(saved, provider_key, "quick_think_llm", quick_values),
            format_func=lambda i: quick_labels[i],
            key="quick_model_idx",
            help="用于常规分析任务，速度优先",
        )
        st.session_state["quick_think_llm"] = quick_values[quick_idx]

        deep_idx = st.selectbox(
            "深度思考模型",
            range(len(deep_options)),
            index=_saved_model_index(saved, provider_key, "deep_think_llm", deep_values),
            format_func=lambda i: deep_labels[i],
            key="deep_model_idx",
            help="用于辩论/决策等需要深度推理的任务",
        )
        st.session_state["deep_think_llm"] = deep_values[deep_idx]
    else:
        custom_quick = st.text_input("快速思考模型 ID", key="custom_quick_model")
        custom_deep = st.text_input("深度思考模型 ID", key="custom_deep_model")
        st.session_state["quick_think_llm"] = custom_quick
        st.session_state["deep_think_llm"] = custom_deep

    st.text_input(
        "API Base URL（第三方/代理，可选）",
        key="llm_base_url",
        placeholder="例: https://your-proxy.com/v1",
        help=(
            "通过第三方中转/代理访问 Claude、OpenAI 等模型时填写网关地址；"
            "留空则用所选供应商的官方地址。API Key 仍从 .env 读取，"
            "且每个供应商用各自的环境变量——"
            "NVIDIA=NVIDIA_API_KEY、OpenAI=OPENAI_API_KEY、DeepSeek=DEEPSEEK_API_KEY、"
            "通义=DASHSCOPE_API_KEY、智谱=ZHIPU_API_KEY、MiniMax=MINIMAX_API_KEY、"
            "小米MiMo=MIMO_API_KEY、"
            "Claude=ANTHROPIC_API_KEY、OpenRouter=OPENROUTER_API_KEY、xAI=XAI_API_KEY。"
            "也可在 .env 里设 BACKEND_URL 代替此处。"
        ),
    )
    st.toggle(
        "并行执行分析师（实验性）",
        key="parallel_analysts",
        value=st.session_state.get(
            "parallel_analysts", DEFAULT_CONFIG.get("parallel_analysts", False)
        ),
        help=(
            "开启后 7 个分析师并发采集数据，分析墙钟时间约为最慢分析师的耗时；"
            "关闭则按传统链条串行执行。两个模式结论可能因模型随机性略有差异。"
        ),
    )
    _save_llm_config()


def render_sidebar() -> None:
    """Render the sidebar with input controls and history."""

    saved_llm_config = _load_saved_llm_config()

    st.markdown(
        """
        <div style="text-align:center; margin-bottom:1.5rem;">
            <span style="font-size:1.6rem; font-weight:800; color:var(--brand);">AStock</span><span style="font-size:1.6rem; font-weight:800; color:var(--text);"> Pro</span>
            <div style="font-size:var(--font-md); color:var(--muted); margin-top:var(--space-xs);">
                A股多智能体投研系统
            </div>
            <div style="font-size:var(--font-xs); color:var(--muted); margin-top:var(--space-xs);">
                by <a href="https://github.com/zhzshuai-create" style="color:var(--brand); text-decoration:none;">zhzshuai-create</a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown("#### 新建分析")

    ticker = st.text_input(
        "股票代码",
        placeholder="例: 300750 或 宁德时代",
        key="input_ticker",
        help="输入6位A股代码或中文股票全称",
    )

    trade_date = st.date_input(
        "分析日期",
        value=date.today(),
        key="input_date",
    )

    with st.expander("模型配置", expanded=False):
        _render_llm_config(saved_llm_config)

    tracker = st.session_state.get("tracker")
    is_busy = tracker is not None and tracker.is_running
    is_stopping = is_busy and tracker.stop_requested

    if st.button(
        "开始分析" if not is_busy else "停止中..." if is_stopping else "分析进行中...",
        use_container_width=True,
        disabled=is_busy or not ticker,
        type="primary",
    ):
        resolved_code, err = _resolve_user_input(ticker)
        if err:
            st.error(err)
        else:
            if resolved_code != ticker.strip():
                st.success(f"{ticker.strip()} → {resolved_code}")
            st.session_state["start_analysis"] = {
                "ticker": resolved_code,
                "trade_date": trade_date.strftime("%Y-%m-%d"),
                "fresh": True,
            }
            st.session_state["viewing_history"] = None

    _render_analysis_controls(ticker, trade_date)

    st.markdown("---")
    st.markdown("#### 未完成任务")

    incomplete = get_incomplete_history()
    if not incomplete:
        st.caption("暂无未完成任务")
    else:
        for entry in incomplete[:10]:
            t, d = entry["ticker"], entry["trade_date"]
            status_label = {
                "error": "出错",
                "paused": "已暂停",
                "running": "进行中",
                # checkpoint_enabled 在 Web 路径从未开启(H2), 点「可继续」实际是
                # 从零全额重跑 — 文案必须如实, 待续跑真正打通后再改回。
            }.get(entry.get("status"), "重新分析")
            step = entry.get("checkpoint_step")
            step_label = f" · step {step}" if step is not None else ""
            label = f"{t}  ·  {d}  ·  {status_label}{step_label}"
            if st.button(
                label,
                key=f"resume_{t}_{d}",
                use_container_width=True,
                disabled=is_busy,
            ):
                st.session_state["start_analysis"] = {
                    "ticker": t,
                    "trade_date": d,
                }
                st.session_state["viewing_history"] = None

    st.markdown("---")
    st.markdown("#### 历史记录")

    history = get_history()
    if not history:
        st.caption("暂无历史记录")
        return

    for entry in history[:20]:
        t, d = entry["ticker"], entry["date"]
        label = f"{t}  ·  {d}"
        if st.button(label, key=f"hist_{t}_{d}", use_container_width=True):
            st.session_state["viewing_history"] = entry["path"]
            st.session_state["start_analysis"] = None
            st.session_state.pop("tracker", None)
            if "job_id" in st.query_params:
                del st.query_params["job_id"]

    st.markdown("---")
    st.caption("仅供学习研究，不构成投资建议")
