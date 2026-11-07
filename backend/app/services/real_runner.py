"""Real model executor: ``TradingAgentsGraph`` behind the job protocol.

The legacy Streamlit runner drives the same graph from ``web/runner.py``. The
backend may not import ``web``, so this module owns its own lifecycle and
restates the legacy state-dict mapping in :mod:`backend.app.services.stage_map`
(kept honest by a sync test).

Configuration precedence is ``llm_config.json`` > environment >
``DEFAULT_CONFIG``, then the job snapshot overrides ``parallel_analysts`` and
``selected_analysts``. ``llm_profile`` is only a contract label and does not
pick a provider; the actual models come from ``llm_config.json`` or the
environment.

Resume is not supported: the graph would replay or skip nodes on its own
checkpoint, which this executor cannot map onto the 12-stage contract, so a
resume request fails fast instead of silently rerunning a stage.

Statistics are cumulative from :class:`cli.stats_handler.StatsCallbackHandler`.
Each super-step's delta is attributed to the stages that completed in that
step; a parallel analyst step completes several stages at once, so its delta
is split evenly. Per-stage numbers are approximate, the job total is not.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from tradingagents.default_config import DEFAULT_CONFIG

from backend.app.models.stage import STAGE_IDS
from backend.app.services.analysis_runner import (
    AnalysisRequest,
    AnalysisRunError,
    RunResult,
    RunStats,
    StageHook,
    StageProgress,
)
from backend.app.services.report_schema import build_legacy_report
from backend.app.services.stage_map import (
    detected_stages,
    expected_stages,
    selected_analysts,
    stage_name,
)

DATA_ROOT_ENV = "TA_DATA_ROOT"
LLM_CONFIG_NAME = "llm_config.json"

A_SHARE_VENDORS: dict[str, str] = {
    "core_stock_apis": "a_stock",
    "technical_indicators": "a_stock",
    "fundamental_data": "a_stock",
    "news_data": "a_stock",
    "signal_data": "a_stock",
}

# Legacy ``web/app.py::_build_config`` reads the same variables.
MODEL_ENV_KEYS: tuple[tuple[str, str], ...] = (
    ("llm_provider", "LLM_PROVIDER"),
    ("quick_think_llm", "QUICK_THINK_LLM"),
    ("deep_think_llm", "DEEP_THINK_LLM"),
)
DOTENV_MODEL_KEYS = ("llm_provider", "quick_think_llm", "deep_think_llm")


def default_config_path(
    environ: Mapping[str, str] | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    root = env.get(DATA_ROOT_ENV)
    base = Path(root).expanduser() if root else Path.home() / ".tradingagents"
    return base / LLM_CONFIG_NAME


def _load_llm_config(path: Path) -> dict[str, Any]:
    """Missing or malformed file means "no overrides", as in the legacy UI."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _apply_model_fields(config: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key in DOTENV_MODEL_KEYS:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            config[key] = value.strip()


def build_real_config(
    snapshot: Mapping[str, Any] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Assemble the graph config for one job.

    Directory settings are read from the environment at call time (rather than
    at ``DEFAULT_CONFIG`` import time) so an entry point or a test can point
    them at another root.
    """
    env = os.environ if environ is None else environ
    snap = snapshot or {}
    config = dict(DEFAULT_CONFIG)
    config["data_vendors"] = dict(A_SHARE_VENDORS)
    config["tool_vendors"] = {}
    config["results_dir"] = env.get(
        "TRADINGAGENTS_RESULTS_DIR", DEFAULT_CONFIG["results_dir"]
    )
    config["data_cache_dir"] = env.get(
        "TRADINGAGENTS_CACHE_DIR", DEFAULT_CONFIG["data_cache_dir"]
    )
    config["memory_log_path"] = env.get(
        "TRADINGAGENTS_MEMORY_LOG_PATH", DEFAULT_CONFIG["memory_log_path"]
    )

    for key, env_key in MODEL_ENV_KEYS:
        value = env.get(env_key)
        if value:
            config[key] = value
    base_url = env.get("BACKEND_URL")
    if base_url:
        config["backend_url"] = base_url

    saved = _load_llm_config(config_path or default_config_path(env))
    _apply_model_fields(config, saved)
    saved_base = saved.get("llm_base_url")
    if isinstance(saved_base, str) and saved_base.strip():
        config["backend_url"] = saved_base.strip()
    saved_parallel = saved.get("parallel_analysts")
    if isinstance(saved_parallel, bool):
        config["parallel_analysts"] = saved_parallel

    if isinstance(snap.get("parallel_analysts"), bool):
        config["parallel_analysts"] = snap["parallel_analysts"]

    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["output_language"] = "Chinese"
    # No resume support (D4); a stale checkpoint must not skip contract stages.
    config["checkpoint_enabled"] = False
    return config


def analysts_for(snapshot: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    snap = snapshot or {}
    toggles = snap.get("stage_toggles")
    return selected_analysts(toggles if isinstance(toggles, Mapping) else None)


def _default_graph_factory(
    *,
    selected_analysts: tuple[str, ...],
    config: dict[str, Any],
    callbacks: list[Any],
) -> Any:
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    return TradingAgentsGraph(
        selected_analysts=list(selected_analysts),
        debug=False,
        config=config,
        callbacks=callbacks,
    )


def _default_stats_factory() -> Any:
    from cli.stats_handler import StatsCallbackHandler

    return StatsCallbackHandler()


class RealAnalysisExecutor:
    """Runs the real graph and maps its super-steps onto contract stages."""

    name = "real"

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        config_path: Path | None = None,
        graph_factory: Callable[..., Any] | None = None,
        stats_factory: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._environ = environ
        self._config_path = config_path
        self._graph_factory = graph_factory or _default_graph_factory
        self._stats_factory = stats_factory or _default_stats_factory
        self._clock = clock

    def run(
        self,
        request: AnalysisRequest,
        *,
        on_stage: StageHook | None = None,
        on_chunk: Callable[[dict[str, Any]], None] | None = None,
    ) -> RunResult:
        if request.resume_from_stage is not None:
            raise AnalysisRunError(
                "real_resume_unsupported",
                "真实执行器暂不支持断点续跑；请重新发起分析",
            )

        snapshot = request.config or {}
        config = build_real_config(
            snapshot, environ=self._environ, config_path=self._config_path
        )
        analysts = analysts_for(snapshot)
        expected = expected_stages(analysts)

        stats = self._stats_factory()
        graph = self._graph_factory(
            selected_analysts=analysts, config=config, callbacks=[stats]
        )
        started: set[str] = set()
        reported: set[str] = set()
        completed: list[str] = []
        total = len(STAGE_IDS)
        carry = [0, 0, 0]
        carry_ms = 0
        last_stats = (0, 0, 0)
        wall_started = self._clock()
        last_clock = wall_started
        last_chunk: dict[str, Any] = {}

        def emit_started(stage_id: str) -> None:
            if stage_id in started:
                return
            started.add(stage_id)
            if on_stage is None:
                return
            on_stage(
                StageProgress(
                    stage_id=stage_id,
                    stage_name=stage_name(stage_id),
                    phase="started",
                    index=STAGE_IDS.index(stage_id) + 1,
                    total=total,
                )
            )

        def emit_done(
            stage_id: str,
            body: str,
            delta: tuple[int, int, int],
            duration_ms: int,
        ) -> None:
            emit_started(stage_id)
            if on_stage is not None:
                on_stage(
                    StageProgress(
                        stage_id=stage_id,
                        stage_name=stage_name(stage_id),
                        phase="done",
                        index=STAGE_IDS.index(stage_id) + 1,
                        total=total,
                        report_text=body,
                        model_calls=delta[0],
                        tokens_in=delta[1],
                        tokens_out=delta[2],
                        duration_ms=duration_ms,
                    )
                )

        try:
            init_state, args, _meta = graph.prepare_graph_run(
                request.ticker_code, request.analysis_date, callbacks=[stats]
            )
            if expected:
                emit_started(expected[0])
            stream = graph.graph.stream(init_state, **args)
            while True:
                try:
                    chunk = next(stream)
                except StopIteration:
                    break
                last_chunk = chunk
                if on_chunk is not None:
                    on_chunk(chunk)

                now = self._clock()
                elapsed_ms = max(0, int((now - last_clock) * 1000))
                last_clock = now

                observed = detected_stages(chunk)
                newly = [
                    stage_id
                    for stage_id in expected
                    if stage_id in observed and stage_id not in reported
                ]
                current = _stats_tuple(stats)
                step = (
                    current[0] - last_stats[0],
                    current[1] - last_stats[1],
                    current[2] - last_stats[2],
                )
                last_stats = current

                if newly:
                    delta = tuple(step[i] + carry[i] for i in range(3))
                    duration = elapsed_ms + carry_ms
                    share = len(newly)
                    per = tuple(value // share for value in delta)
                    per_ms = duration // share
                    for offset, stage_id in enumerate(newly):
                        piece = list(per)
                        if offset == 0:
                            for axis in range(3):
                                piece[axis] += delta[axis] - per[axis] * share
                            duration_piece = per_ms + duration - per_ms * share
                        else:
                            duration_piece = per_ms
                        reported.add(stage_id)
                        completed.append(stage_id)
                        emit_done(
                            stage_id,
                            observed[stage_id],
                            (piece[0], piece[1], piece[2]),
                            duration_piece,
                        )
                    carry = [0, 0, 0]
                    carry_ms = 0
                else:
                    carry = [carry[i] + step[i] for i in range(3)]
                    carry_ms += elapsed_ms

                for stage_id in expected:
                    if stage_id not in started:
                        emit_started(stage_id)
                        break

            if not last_chunk:
                raise AnalysisRunError(
                    "graph_empty_result", "分析没有返回任何结果，请清理断点后重试"
                )
            signal = graph.finalize_graph_run(
                request.ticker_code, request.analysis_date, last_chunk
            )
        finally:
            graph.close_graph_run()

        report = None
        if request.job_id is not None and request.generated_at is not None:
            report = build_legacy_report(last_chunk)

        totals = _stats_tuple(stats)
        return RunResult(
            signal=str(signal),
            stats=RunStats(
                model_calls=totals[0],
                tokens_in=totals[1],
                tokens_out=totals[2],
                elapsed_ms=max(0, int((self._clock() - wall_started) * 1000)),
            ),
            stages_completed=tuple(completed),
            last_chunk=last_chunk,
            report=report,
        )


def _stats_tuple(stats: Any) -> tuple[int, int, int]:
    data = stats.get_stats()
    return (
        int(data.get("llm_calls", 0)),
        int(data.get("tokens_in", 0)),
        int(data.get("tokens_out", 0)),
    )
