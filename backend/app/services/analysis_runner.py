"""Analysis executor factory and the default fake-graph adapter.

P1 runs the deterministic Day 6 fake graph. It lives under ``tests/`` on
purpose: it is a development default, not the product's real executor, and it
never imports a model SDK. Real model execution needs BOTH
``TA_ENABLE_REAL_RUNNER=1`` and a server config with ``real_runner_enabled``;
P1 ships no real adapter, so that combination fails fast instead of quietly
running the fake graph while an operator believes models are on.

The adapter consumes the same cumulative chunks the legacy runner consumes,
so callers can hook the stream into an existing progress tracker (GF-06)
without the backend importing ``web``.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from backend.app.core.server_config import ServerConfig
from backend.app.models.stage import STAGE_IDS

REAL_RUNNER_ENV = "TA_ENABLE_REAL_RUNNER"
REAL_RUNNER_ENV_VALUE = "1"
FAKE_MODULE = "tests.fake_analysis_graph"


class AnalysisRunError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AnalysisRequest:
    ticker_code: str
    analysis_date: str
    resume_from_stage: str | None = None
    # Job identity is optional so adapter-level tests can run a bare graph.
    # The worker always supplies it together with generated_at; the adapter
    # only builds a ReportDTO when both are present.
    job_id: str | None = None
    generated_at: datetime | None = None
    retry_of_job_id: str | None = None


@dataclass(frozen=True)
class StageProgress:
    stage_id: str
    stage_name: str
    phase: str
    index: int
    total: int
    report_text: str | None = None
    model_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0


@dataclass(frozen=True)
class RunStats:
    model_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    elapsed_ms: int = 0


@dataclass(frozen=True)
class RunResult:
    signal: str
    stats: RunStats
    stages_completed: tuple[str, ...]
    last_chunk: dict[str, Any] = field(repr=False, compare=False)
    report: dict[str, Any] | None = field(default=None, repr=False, compare=False)


StageHook = Callable[[StageProgress], None]
ChunkHook = Callable[[dict[str, Any]], None]


@runtime_checkable
class AnalysisExecutor(Protocol):
    name: str

    def run(
        self,
        request: AnalysisRequest,
        *,
        on_stage: StageHook | None = None,
        on_chunk: ChunkHook | None = None,
    ) -> RunResult: ...


class FakeAnalysisExecutor:
    """Runs the fake graph stage by stage and reports deterministic stats."""

    name = "fake"

    def __init__(self, fake_module: Any | None = None) -> None:
        self._fake = fake_module

    def _module(self) -> Any:
        if self._fake is not None:
            return self._fake
        try:
            self._fake = importlib.import_module(FAKE_MODULE)
        except ImportError as exc:
            raise AnalysisRunError(
                "fake_graph_missing",
                "找不到 tests.fake_analysis_graph；请在仓库根目录运行",
            ) from exc
        return self._fake

    def run(
        self,
        request: AnalysisRequest,
        *,
        on_stage: StageHook | None = None,
        on_chunk: ChunkHook | None = None,
    ) -> RunResult:
        fake = self._module()
        stage_ids = tuple(spec.id for spec in fake.STAGES)
        if stage_ids != tuple(STAGE_IDS):
            raise AnalysisRunError(
                "stage_catalog_mismatch",
                "假图阶段目录与冻结契约不一致",
            )

        start_index = 0
        if request.resume_from_stage is not None:
            try:
                start_index = stage_ids.index(request.resume_from_stage)
            except ValueError as exc:
                raise AnalysisRunError(
                    "resume_stage_unknown",
                    "续跑起始阶段不在冻结阶段目录里",
                ) from exc

        graph = fake.FakeAnalysisGraph(request.ticker_code, request.analysis_date)

        init_state, args, _meta = graph.prepare_graph_run(
            request.ticker_code, request.analysis_date, callbacks=[]
        )
        total = len(fake.STAGES)
        model_calls = tokens_in = tokens_out = elapsed_ms = 0
        completed: list[str] = []
        last_chunk: dict[str, Any] = {}

        try:
            stream = graph.stream(init_state, **args)
            for index, spec in enumerate(fake.STAGES, 1):
                if index <= start_index:
                    # Checkpoint prefix: advance the stream so the graph state
                    # is whole, but never re-report or re-count a done stage.
                    try:
                        last_chunk = next(stream)
                    except StopIteration:
                        raise AnalysisRunError(
                            "graph_stream_ended", "假图在阶段完成前结束"
                        ) from None
                    continue
                if on_stage is not None:
                    on_stage(
                        StageProgress(
                            stage_id=spec.id,
                            stage_name=spec.name,
                            phase="started",
                            index=index,
                            total=total,
                        )
                    )
                try:
                    chunk = next(stream)
                except StopIteration:
                    raise AnalysisRunError(
                        "graph_stream_ended", "假图在阶段完成前结束"
                    ) from None
                last_chunk = chunk
                if on_chunk is not None:
                    on_chunk(chunk)

                text = fake.extract_stage_text(chunk, spec)
                model_calls += spec.model_calls
                tokens_in += spec.tokens_in
                tokens_out += spec.tokens_out
                elapsed_ms += spec.duration_ms
                completed.append(spec.id)
                if on_stage is not None:
                    on_stage(
                        StageProgress(
                            stage_id=spec.id,
                            stage_name=spec.name,
                            phase="done",
                            index=index,
                            total=total,
                            report_text=text,
                            model_calls=spec.model_calls,
                            tokens_in=spec.tokens_in,
                            tokens_out=spec.tokens_out,
                            duration_ms=spec.duration_ms,
                        )
                    )

            signal = graph.finalize_graph_run(
                request.ticker_code, request.analysis_date, last_chunk
            )
        finally:
            graph.close_graph_run()

        report = None
        if request.job_id is not None and request.generated_at is not None:
            report = graph.build_report(
                request.job_id,
                generated_at=request.generated_at,
                retry_of_job_id=request.retry_of_job_id,
            )

        return RunResult(
            signal=str(signal),
            stats=RunStats(
                model_calls=model_calls,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                elapsed_ms=elapsed_ms,
            ),
            stages_completed=tuple(completed),
            last_chunk=last_chunk,
            report=report,
        )


def real_runner_enabled(
    server_config: ServerConfig,
    *,
    environ: Mapping[str, str] | None = None,
) -> bool:
    env = os.environ if environ is None else environ
    return (
        env.get(REAL_RUNNER_ENV) == REAL_RUNNER_ENV_VALUE
        and server_config.real_runner_enabled
    )


def create_analysis_executor(
    server_config: ServerConfig | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> AnalysisExecutor:
    config = server_config or ServerConfig()
    if real_runner_enabled(config, environ=environ):
        raise AnalysisRunError(
            "real_runner_unavailable",
            "真实执行器尚未接入 P1；请关闭开关或等待 P6 接入",
        )
    return FakeAnalysisExecutor()
