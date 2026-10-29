"""Deterministic fake analysis graph and job runner for P0/P1 lifecycle tests.

The module mirrors the execution surface of the product runner:
``prepare_graph_run`` / ``stream`` / ``finalize_graph_run`` for the graph layer,
plus a state-machine runner that emits contract-shaped events.

Hard rules:
- no network, no model calls, no market data, no writes to the user report dir;
- a virtual clock replaces wall time, so runs are reproducible without sleeps;
- faults are addressable by stage id, so P1 can test failure and crash paths.

Usage documentation: docs/upgrade/fake-graph/README.md
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

CST = timezone(timedelta(hours=8))
START_AT = datetime(2026, 10, 24, 9, 30, tzinfo=CST)
STAGE_DURATION_MS = 30 * 60 * 1000
FAILURE_DELAY_MS = 5 * 1000
TOTAL_STAGES = 12

TERMINAL_STATUSES = frozenset({"cancelled", "succeeded", "failed", "interrupted"})
ACTIVE_STATUSES = frozenset(
    {"queued", "running", "pause_requested", "paused", "cancel_requested"}
)

ALLOWED_ACTIONS: dict[str, tuple[str, ...]] = {
    "queued": ("cancel",),
    "running": ("pause", "cancel"),
    "pause_requested": ("cancel",),
    "paused": ("resume", "cancel"),
    "cancel_requested": (),
    "cancelled": ("reanalyze",),
    "succeeded": ("retry", "reanalyze"),
    "failed": ("retry", "reanalyze"),
    "interrupted": ("resume_from_checkpoint", "retry", "reanalyze"),
}

GOLDEN_REPORT_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "upgrade" / "final_state_v1.json"
)
GOLDEN_REPORT_ID = "0f1e2d3c-4b5a-6978-8765-4321fedcba98"


@dataclass(frozen=True)
class StageSpec:
    id: str
    name: str
    report_key: str
    model_calls: int
    tokens_in: int
    tokens_out: int
    duration_ms: int = STAGE_DURATION_MS


STAGES: tuple[StageSpec, ...] = (
    StageSpec("market", "技术分析", "market_report", 1, 28000, 4200),
    StageSpec("social", "情绪分析", "sentiment_report", 1, 22000, 5100),
    StageSpec("news", "新闻舆情", "news_report", 1, 25000, 5800),
    StageSpec("fundamentals", "基本面", "fundamentals_report", 1, 21000, 4800),
    StageSpec("policy", "政策分析", "policy_report", 1, 19000, 4300),
    StageSpec("hot_money", "游资追踪", "hot_money_report", 1, 17000, 3900),
    StageSpec("lockup", "解禁监控", "lockup_report", 1, 16000, 3600),
    StageSpec("quality_gate", "质量门控", "data_quality_summary", 0, 0, 0),
    StageSpec("debate", "多空辩论", "investment_debate_state", 2, 12000, 3100),
    StageSpec("trader", "交易决策", "trader_investment_plan", 1, 9000, 2200),
    StageSpec("risk", "风控评估", "risk_debate_state", 3, 10000, 2700),
    StageSpec("pm", "最终决策", "final_trade_decision", 1, 3430, 1508),
)

STAGE_IDS: tuple[str, ...] = tuple(spec.id for spec in STAGES)
_STAGE_BY_ID = {spec.id: spec for spec in STAGES}

# Simple stages map one report section to one legacy chunk key.
_SECTION_BY_STAGE = {
    "market": ("sec-market", "market_report"),
    "social": ("sec-sentiment", "sentiment_report"),
    "news": ("sec-news", "news_report"),
    "fundamentals": ("sec-fundamentals", "fundamentals_report"),
    "policy": ("sec-policy", "policy_report"),
    "hot_money": ("sec-hot-money", "hot_money_report"),
    "lockup": ("sec-lockup", "lockup_report"),
    "quality_gate": ("sec-quality", "data_quality_summary"),
    "trader": ("sec-trader", "trader_investment_plan"),
    "pm": ("sec-decision", "final_trade_decision"),
}


class FakeGraphError(Exception):
    """Injected stage failure. The runner maps it to ``failed`` (T04)."""

    def __init__(self, stage_id: str, code: str = "internal_error",
                 message: str = "分析执行失败") -> None:
        super().__init__(message)
        self.stage_id = stage_id
        self.code = code
        self.message = message


class SimulatedInterrupt(BaseException):
    """Process death at a named point. Deliberately not an ``Exception``."""

    def __init__(self, point: str) -> None:
        super().__init__(point)
        self.point = point


class IllegalTransition(Exception):
    """Control action rejected before any state change. P1 maps it to HTTP 409."""

    def __init__(self, rule: str | None, from_status: str, action: str) -> None:
        super().__init__(f"{action} rejected in {from_status} ({rule or 'no rule'})")
        self.rule = rule
        self.from_status = from_status
        self.action = action


@dataclass
class VirtualClock:
    now: datetime = START_AT

    def advance(self, ms: int) -> None:
        self.now = self.now + timedelta(milliseconds=ms)

    def iso(self) -> str:
        return self.now.isoformat(timespec="seconds")


@dataclass
class RunOutcome:
    job: dict[str, Any]
    events: list[dict[str, Any]]
    audit: list[dict[str, Any]]
    report: dict[str, Any] | None
    report_written: bool
    report_committed: bool
    reconcile_notes: list[dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        stages = self.job["stages"]
        return {
            "scenario": self.meta.get("scenario"),
            "status": self.job["status"],
            "stages_done": sum(1 for s in stages if s["status"] == "done"),
            "stages_failed": sum(1 for s in stages if s["status"] == "failed"),
            "events": len(self.events),
            "model_calls": self.job["stats"]["model_calls"],
            "tokens_in": self.job["stats"]["tokens_in"],
            "tokens_out": self.job["stats"]["tokens_out"],
            "report_id": self.job["report_id"],
            "report_written": self.report_written,
            "report_committed": self.report_committed,
            "reconcile_notes": [n["code"] for n in self.reconcile_notes],
            "meta": self.meta,
        }


def load_golden_report() -> dict[str, Any]:
    return json.loads(GOLDEN_REPORT_PATH.read_text(encoding="utf-8"))


def compute_content_hash(sections: dict[str, Any]) -> str:
    payload = json.dumps(
        sections, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def report_id_for(job_id: str) -> str:
    if job_id == "job-0001":
        return GOLDEN_REPORT_ID
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"astock:{job_id}"))


def build_stage_chunk(report: dict[str, Any], spec: StageSpec) -> dict[str, Any]:
    if spec.id == "debate":
        parts = report["sections"]["sec-debate"]["parts"]
        return {
            "investment_debate_state": {
                "bull_history": parts["bull"],
                "bear_history": parts["bear"],
                "history": parts["history"],
                "current_response": parts["current"],
                "judge_decision": parts["judge"],
            }
        }
    if spec.id == "risk":
        parts = report["sections"]["sec-risk"]["parts"]
        ref = report["sections"]["sec-risk"].get("parts_ref", {}).get("judge")
        judge = report["sections"][ref]["body"] if ref else parts.get("judge", "")
        return {
            "risk_debate_state": {
                "aggressive_history": parts["aggressive"],
                "conservative_history": parts["conservative"],
                "neutral_history": parts["neutral"],
                "history": "",
                "judge_decision": judge,
            }
        }
    section_id, key = _SECTION_BY_STAGE[spec.id]
    return {key: report["sections"][section_id]["body"]}


def extract_stage_text(chunk: dict[str, Any], spec: StageSpec) -> str:
    if spec.id == "debate":
        return str(chunk["investment_debate_state"]["judge_decision"])
    if spec.id == "risk":
        return str(chunk["risk_debate_state"]["judge_decision"])
    return str(chunk[spec.report_key])


class FakeAnalysisGraph:
    """Graph layer: fixed 12-stage stream plus a golden ReportDTO.

    The stream yields cumulative state chunks, matching the shape the product
    runner consumes. ``finalize_graph_run`` returns only the signal; the report
    is built in memory and never written to the user report directory.
    """

    def __init__(
        self,
        ticker: str = "000629",
        analysis_date: str = "2026-10-24",
        *,
        fail_at: str | None = None,
        golden_report: dict[str, Any] | None = None,
    ) -> None:
        self.ticker = ticker
        self.analysis_date = analysis_date
        self.fail_at = fail_at
        self._golden = golden_report or load_golden_report()
        self.closed = False

    def prepare_graph_run(
        self,
        ticker: str,
        trade_date: str,
        callbacks: list[Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        self.ticker = ticker
        self.analysis_date = trade_date
        init_state = {"company_of_interest": ticker, "trade_date": trade_date}
        args = {"fake": True, "callbacks": callbacks or []}
        meta = {"ticker": ticker, "trade_date": trade_date}
        return init_state, args, meta

    def stream(
        self, init_state: dict[str, Any], **args: Any
    ) -> Iterator[dict[str, Any]]:
        state = dict(init_state)
        for spec in STAGES:
            if self.fail_at == spec.id:
                raise FakeGraphError(spec.id)
            state.update(build_stage_chunk(self._golden, spec))
            yield dict(state)

    def finalize_graph_run(
        self,
        ticker: str,
        trade_date: str,
        last_chunk: dict[str, Any],
    ) -> str:
        return str(self._golden["meta"]["signal"])

    def close_graph_run(self) -> None:
        self.closed = True

    def build_report(
        self,
        job_id: str,
        *,
        generated_at: datetime,
        report_id: str | None = None,
        retry_of_job_id: str | None = None,
    ) -> dict[str, Any]:
        report = copy.deepcopy(self._golden)
        meta = report["meta"]
        meta["report_id"] = report_id or report_id_for(job_id)
        meta["job_id"] = job_id
        meta["ticker_code"] = self.ticker
        meta["ticker_name"] = "攀钢钒钛" if self.ticker == "000629" else None
        meta["analysis_date"] = self.analysis_date
        meta["generated_at"] = generated_at.isoformat(timespec="seconds")
        meta["generated_at_source"] = "job_clock"
        meta["origin"] = "new"
        meta["retry_of_job_id"] = retry_of_job_id
        meta["content_hash"] = compute_content_hash(report["sections"])
        return report


class FakeJobRunner:
    """State-machine runner around :class:`FakeAnalysisGraph`.

    Control requests take effect at the next stage boundary. Calling
    ``pause()`` or ``cancel()`` and then ``advance()`` therefore stops before
    a new stage starts. This is the safe-boundary semantics from the contract.
    """

    def __init__(
        self,
        *,
        job_id: str = "job-0001",
        ticker: str = "000629",
        analysis_date: str = "2026-10-24",
        graph: FakeAnalysisGraph | None = None,
        config: dict[str, Any] | None = None,
        config_digest: str = "cfg-test-0001",
        graph_version: str = "graph-v1",
        interrupt_at: str | None = None,
        fail_after: str | None = None,
        auto_finalize: bool = True,
        checkpoint_present: bool = True,
        retry_of_job_id: str | None = None,
        resume_of_job_id: str | None = None,
        resume_from_stage: str | None = None,
        clock_start: datetime = START_AT,
    ) -> None:
        self.job_id = job_id
        self.ticker = ticker
        self.analysis_date = analysis_date
        self.graph = graph or FakeAnalysisGraph(ticker, analysis_date)
        self.config = copy.deepcopy(config or {})
        self.config_digest = config_digest
        self.graph_version = graph_version
        self.interrupt_at = interrupt_at
        self.fail_after = fail_after
        self.auto_finalize = auto_finalize
        self.checkpoint_present = checkpoint_present
        self.retry_of_job_id = retry_of_job_id
        self.resume_of_job_id = resume_of_job_id
        self.resume_from_stage = resume_from_stage

        self.clock = VirtualClock(clock_start)
        self.created_at = self.clock.iso()
        self.updated_at = self.created_at
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self._started_dt: datetime | None = None

        self.status = "queued"
        self.pending_action: str | None = None
        self.current_stage: str | None = None
        self.stage_pointer = 0
        self.stage_state = {
            spec.id: {
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "duration_ms": None,
            }
            for spec in STAGES
        }
        self.stage_outputs: dict[str, str] = {}

        self.seq = 0
        self.events: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = [
            {
                "audit_id": 1,
                "type": "created",
                "at": self.created_at,
                "payload": {
                    "status": "queued",
                    "ticker_code": ticker,
                    "analysis_date": analysis_date,
                },
            }
        ]
        self.stats = {"model_calls": 0, "tokens_in": 0, "tokens_out": 0}
        self.error: dict[str, str] | None = None
        self.report: dict[str, Any] | None = None
        self.report_written = False
        self.report_committed = False
        self.reconcile_notes: list[dict[str, Any]] = []
        self._stream: Iterator[dict[str, Any]] | None = None

    # -- events ---------------------------------------------------------
    def _emit(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.seq += 1
        event = {
            "seq": self.seq,
            "job_id": self.job_id,
            "type": event_type,
            "at": self.clock.iso(),
            "payload": payload,
        }
        self.events.append(event)
        self.updated_at = event["at"]
        return event

    def _audit(self, record_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = {
            "audit_id": len(self.audit) + 1,
            "type": record_type,
            "at": self.clock.iso(),
            "payload": payload,
        }
        self.audit.append(record)
        return record

    def _transition(
        self,
        to: str,
        reason: str,
        *,
        detail: str | None = None,
        pending_action: str | None = None,
        error: dict[str, str] | None = None,
    ) -> None:
        payload = {
            "from": self.status,
            "to": to,
            "reason": reason,
            "detail": detail,
            "pending_action": pending_action,
            "error": error,
        }
        self.status = to
        self.pending_action = pending_action
        if to in TERMINAL_STATUSES:
            self.finished_at = self.clock.iso()
            self.current_stage = None
        self._emit("status_changed", payload)

    def _stats_payload(self) -> dict[str, int]:
        elapsed_ms = 0
        if self._started_dt is not None:
            elapsed_ms = int((self.clock.now - self._started_dt).total_seconds() * 1000)
        return {
            "model_calls": self.stats["model_calls"],
            "tokens_in": self.stats["tokens_in"],
            "tokens_out": self.stats["tokens_out"],
            "elapsed_ms": elapsed_ms,
        }

    def _report_ready_payload(self) -> dict[str, Any]:
        assert self.report is not None
        meta = self.report["meta"]
        return {
            "report_id": meta["report_id"],
            "content_hash": meta["content_hash"],
            "rating": meta["rating"],
            "signal": meta["signal"],
            "url": f"/api/v1/reports/{meta['report_id']}",
        }

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        if self.status != "queued":
            raise IllegalTransition("I10", self.status, "start")
        self._started_dt = self.clock.now
        self.started_at = self.clock.iso()
        init_state, args, _meta = self.graph.prepare_graph_run(
            self.ticker, self.analysis_date, callbacks=[]
        )
        self._stream = self.graph.stream(init_state, **args)
        self._transition("running", "worker")

    def advance(self) -> bool:
        """Run at most one stage boundary. Returns True when a stage ran."""
        if self.status in TERMINAL_STATUSES or self.status == "paused":
            return False
        if self.status == "pause_requested":
            self._transition("paused", "worker", detail="pause")
            return False
        if self.status == "cancel_requested":
            self._finish_cancel()
            return False
        if self.status != "running":
            return False
        if self.stage_pointer >= TOTAL_STAGES:
            if self.auto_finalize:
                self.finalize()
                return True
            return False

        spec = STAGES[self.stage_pointer]
        if self.interrupt_at == f"before:{spec.id}":
            raise SimulatedInterrupt(f"before:{spec.id}")

        self._begin_stage(spec)
        if self._stream is None:
            raise RuntimeError("stream not started")
        try:
            chunk = next(self._stream)
        except StopIteration as exc:
            raise RuntimeError("fake graph stream ended early") from exc
        except FakeGraphError as exc:
            self._fail_stage(spec, exc)
            return False

        self.clock.advance(spec.duration_ms)
        self.stage_outputs[spec.id] = extract_stage_text(chunk, spec)
        if self.interrupt_at == f"after:{spec.id}":
            raise SimulatedInterrupt(f"after:{spec.id}")

        self._finish_stage(spec)
        self.stage_pointer += 1
        if self.fail_after == spec.id:
            self._fail_after_stage()
            return False
        return True

    def run_all(self) -> RunOutcome:
        if self.status == "queued":
            self.start()
        for _ in range(TOTAL_STAGES + 4):
            if self.status in TERMINAL_STATUSES or self.status == "paused":
                break
            progressed = self.advance()
            if not progressed and self.status == "running":
                break
        return self.outcome()

    def _begin_stage(self, spec: StageSpec) -> None:
        self.current_stage = spec.id
        state = self.stage_state[spec.id]
        state["status"] = "active"
        state["started_at"] = self.clock.iso()
        self._emit(
            "stage_changed",
            {
                "stage_id": spec.id,
                "stage_name": spec.name,
                "stage_status": "started",
                "index": STAGES.index(spec) + 1,
                "total": TOTAL_STAGES,
                "started_at": state["started_at"],
                "finished_at": None,
                "duration_ms": None,
            },
        )
        self.updated_at = self.clock.iso()

    def _finish_stage(self, spec: StageSpec) -> None:
        state = self.stage_state[spec.id]
        state["status"] = "done"
        state["finished_at"] = self.clock.iso()
        state["duration_ms"] = spec.duration_ms
        self._emit(
            "stage_changed",
            {
                "stage_id": spec.id,
                "stage_name": spec.name,
                "stage_status": "done",
                "index": STAGES.index(spec) + 1,
                "total": TOTAL_STAGES,
                "started_at": state["started_at"],
                "finished_at": state["finished_at"],
                "duration_ms": spec.duration_ms,
            },
        )
        self.stats["model_calls"] += spec.model_calls
        self.stats["tokens_in"] += spec.tokens_in
        self.stats["tokens_out"] += spec.tokens_out
        self._emit("stats", self._stats_payload())
        self.current_stage = None
        self.updated_at = self.clock.iso()

    def _fail_stage(self, spec: StageSpec, exc: FakeGraphError) -> None:
        self.clock.advance(FAILURE_DELAY_MS)
        state = self.stage_state[spec.id]
        state["status"] = "failed"
        state["finished_at"] = self.clock.iso()
        state["duration_ms"] = FAILURE_DELAY_MS
        self._emit(
            "stage_changed",
            {
                "stage_id": spec.id,
                "stage_name": spec.name,
                "stage_status": "failed",
                "index": STAGES.index(spec) + 1,
                "total": TOTAL_STAGES,
                "started_at": state["started_at"],
                "finished_at": state["finished_at"],
                "duration_ms": FAILURE_DELAY_MS,
            },
        )
        self.error = {"code": exc.code, "message": exc.message}
        self._emit("stats", self._stats_payload())
        self._transition("failed", "worker", detail="stage_failed", error=self.error)

    def _fail_after_stage(self) -> None:
        self.error = {"code": "internal_error", "message": "分析执行失败"}
        self._transition(
            "failed", "worker", detail="post_stage_error", error=self.error
        )

    def pause(self) -> dict[str, Any]:
        if self.status == "running":
            self._transition(
                "pause_requested", "user", detail="pause", pending_action="pause"
            )
            return {"accepted": True, "action": "pause", "status": self.status}
        if self.status == "pause_requested":
            return {
                "accepted": False,
                "reason": "already_pending",
                "status": self.status,
            }
        rule = "I06" if self.status == "queued" else None
        raise IllegalTransition(rule, self.status, "pause")

    def resume(self) -> dict[str, Any]:
        if self.status != "paused":
            raise IllegalTransition(None, self.status, "resume")
        self._transition("running", "user", detail="resume")
        return {"accepted": True, "action": "resume", "status": self.status}

    def cancel(self) -> dict[str, Any]:
        if self.status == "queued":
            self._emit("stats", self._stats_payload())
            self._transition("cancelled", "user", detail="cancel")
            return {"accepted": True, "action": "cancel", "status": self.status}
        if self.status in ("running", "pause_requested", "paused"):
            self._transition(
                "cancel_requested",
                "user",
                detail="cancel",
                pending_action="cancel",
            )
            return {"accepted": True, "action": "cancel", "status": self.status}
        if self.status == "cancel_requested":
            return {
                "accepted": False,
                "reason": "already_pending",
                "status": self.status,
            }
        raise IllegalTransition(None, self.status, "cancel")

    def _finish_cancel(self) -> None:
        if self.status != "cancel_requested":
            raise IllegalTransition(None, self.status, "cancel_confirm")
        self.report = None
        self.report_written = False
        self.report_committed = False
        self._emit("stats", self._stats_payload())
        self._transition("cancelled", "worker", detail="cancel")

    def finalize(self, *, cancel_wins: bool = False) -> None:
        if self.status not in ("running", "pause_requested", "cancel_requested"):
            raise IllegalTransition(None, self.status, "finalize")
        if self.status == "cancel_requested" and cancel_wins:
            self._finish_cancel()
            return
        if self.stage_pointer < TOTAL_STAGES:
            raise RuntimeError("cannot finalize before all stages complete")

        self.report = self.graph.build_report(
            self.job_id,
            generated_at=self.clock.now,
            retry_of_job_id=self.retry_of_job_id,
        )
        self.report_written = True
        if self.interrupt_at == "after_report":
            raise SimulatedInterrupt("after_report")

        self.report_committed = True
        detail = None
        if self.status == "cancel_requested":
            detail = "cancel_noop"
        elif self.status == "pause_requested":
            detail = "pause_noop"
        self._emit("stats", self._stats_payload())
        self._transition("succeeded", "worker", detail=detail)
        if self.interrupt_at == "after_commit":
            raise SimulatedInterrupt("after_commit")
        self._emit("report_ready", self._report_ready_payload())

    # -- reconciliation -------------------------------------------------
    def _note(self, code: str, message: str) -> dict[str, Any]:
        note = {"code": code, "message": message, "at": self.clock.iso()}
        self.reconcile_notes.append(note)
        self.updated_at = note["at"]
        return note

    def reconcile(self) -> dict[str, Any]:
        before = self.status
        appended = False
        if before == "queued":
            pass
        elif before == "paused":
            if not self.checkpoint_present:
                self._transition(
                    "interrupted", "reconcile", detail="checkpoint_missing"
                )
        elif before in ("running", "pause_requested", "cancel_requested"):
            detail = "lease_expired"
            if self.report_written and not self.report_committed:
                detail = "unregistered_report"
                self._note("unregistered_report", "发现一份未登记的完整报告")
            else:
                for spec in STAGES:
                    if (
                        self.stage_state[spec.id]["status"] == "active"
                        and spec.id in self.stage_outputs
                    ):
                        detail = "unregistered_stage_output"
                        self._note(
                            "unregistered_stage_output",
                            f"发现未登记的阶段产物：{spec.name}",
                        )
            self._transition("interrupted", "reconcile", detail=detail)
        elif before == "succeeded":
            has_ready = any(e["type"] == "report_ready" for e in self.events)
            if self.report_committed and not has_ready:
                self._emit("report_ready", self._report_ready_payload())
                appended = True
        return {
            "before": before,
            "after": self.status,
            "report_ready_appended": appended,
            "notes": [dict(n) for n in self.reconcile_notes],
        }

    # -- read models ----------------------------------------------------
    def job_detail(self) -> dict[str, Any]:
        current = None
        if self.current_stage and self.status in (
            "running",
            "pause_requested",
            "cancel_requested",
        ):
            spec = _STAGE_BY_ID[self.current_stage]
            current = {
                "id": spec.id,
                "name": spec.name,
                "index": STAGES.index(spec) + 1,
                "total": TOTAL_STAGES,
                "status": "active",
            }
        stages = []
        for index, spec in enumerate(STAGES, 1):
            state = self.stage_state[spec.id]
            stages.append(
                {
                    "id": spec.id,
                    "name": spec.name,
                    "index": index,
                    "status": state["status"],
                    "started_at": state["started_at"],
                    "finished_at": state["finished_at"],
                    "duration_ms": state["duration_ms"],
                }
            )
        report_id = None
        if self.report is not None and self.report_committed:
            report_id = self.report["meta"]["report_id"]
        return {
            "job_id": self.job_id,
            "status": self.status,
            "pending_action": self.pending_action,
            "ticker_code": self.ticker,
            "ticker_name": "攀钢钒钛" if self.ticker == "000629" else None,
            "analysis_date": self.analysis_date,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "current_stage": current,
            "stages": stages,
            "stats": self._stats_payload(),
            "report_id": report_id,
            "error": copy.deepcopy(self.error),
            "config_digest": self.config_digest,
            "graph_version": self.graph_version,
            "retry_of_job_id": self.retry_of_job_id,
            "resume_of_job_id": self.resume_of_job_id,
            "resume_from_stage": self.resume_from_stage,
            "allowed_actions": list(ALLOWED_ACTIONS[self.status]),
            "links": {
                "self": f"/api/v1/jobs/{self.job_id}",
                "events": f"/api/v1/jobs/{self.job_id}/events",
                "report": (
                    f"/api/v1/reports/{report_id}" if report_id else None
                ),
            },
            "reconcile_notes": copy.deepcopy(self.reconcile_notes),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "job_id": self.job_id,
            "type": "snapshot",
            "at": self.clock.iso(),
            "payload": {"job": self.job_detail(), "last_seq": self.seq},
        }

    def replay(self, last_event_id: int) -> list[dict[str, Any]]:
        if last_event_id < 0:
            raise ValueError("last_event_id must be >= 0")
        return [
            copy.deepcopy(event)
            for event in self.events
            if event["seq"] > last_event_id
        ]

    def subscribe(self, last_event_id: int | None = None) -> list[dict[str, Any]]:
        frames = [self.snapshot()]
        if last_event_id is not None:
            frames.extend(self.replay(last_event_id))
        return frames

    def outcome(self, *, scenario: str | None = None, **meta: Any) -> RunOutcome:
        merged = dict(meta)
        if scenario is not None:
            merged["scenario"] = scenario
        return RunOutcome(
            job=self.job_detail(),
            events=copy.deepcopy(self.events),
            audit=copy.deepcopy(self.audit),
            report=copy.deepcopy(self.report),
            report_written=self.report_written,
            report_committed=self.report_committed,
            reconcile_notes=copy.deepcopy(self.reconcile_notes),
            meta=merged,
        )


@dataclass
class CreateResult:
    status_code: int
    job: FakeJobRunner | None
    replayed: bool = False
    existing_header: bool = False
    error_code: str | None = None
    active_job_id: str | None = None


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FakeJobLedger:
    """In-memory creation ledger for the idempotency decision table.

    Implements steps 1-5 of ``idempotency-conflicts.md``. Step 3 covers both a
    missing key and a first-seen key, so concurrent requests with distinct keys
    still resolve to one active job.
    """

    def __init__(self) -> None:
        self.jobs: dict[str, FakeJobRunner] = {}
        self._keys: dict[str, tuple[str, str]] = {}
        self._job_seq = 0

    def _active_jobs(self) -> list[FakeJobRunner]:
        return [job for job in self.jobs.values() if job.status in ACTIVE_STATUSES]

    def create(
        self,
        ticker: str,
        analysis_date: str,
        config: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> CreateResult:
        body = {
            "ticker": ticker,
            "analysis_date": analysis_date,
            "config": config,
        }
        body_hash = _stable_hash(body)

        if idempotency_key is not None and idempotency_key in self._keys:
            stored_hash, job_id = self._keys[idempotency_key]
            if stored_hash != body_hash:
                return CreateResult(
                    409, None, error_code="idempotency_mismatch"
                )
            return CreateResult(200, self.jobs[job_id], replayed=True)

        for job in self._active_jobs():
            fingerprint = _stable_hash(
                {
                    "ticker": job.ticker,
                    "analysis_date": job.analysis_date,
                    "config": job.config,
                }
            )
            if fingerprint != body_hash:
                continue
            if idempotency_key is not None:
                self._keys[idempotency_key] = (body_hash, job.job_id)
            return CreateResult(200, job, existing_header=True)

        for job in self._active_jobs():
            if job.ticker == ticker and job.analysis_date == analysis_date:
                return CreateResult(
                    409,
                    None,
                    error_code="active_conflict",
                    active_job_id=job.job_id,
                )

        self._job_seq += 1
        job = FakeJobRunner(
            job_id=f"job-{self._job_seq:04d}",
            ticker=ticker,
            analysis_date=analysis_date,
            config=copy.deepcopy(config),
        )
        self.jobs[job.job_id] = job
        if idempotency_key is not None:
            self._keys[idempotency_key] = (body_hash, job.job_id)
        return CreateResult(201, job)

    def active_jobs(self) -> list[FakeJobRunner]:
        return self._active_jobs()


# -- scenario catalog ---------------------------------------------------
def _scenario_s00() -> RunOutcome:
    runner = FakeJobRunner()
    runner.run_all()
    return runner.outcome(scenario="S00")


def _scenario_s01() -> RunOutcome:
    runner = FakeJobRunner()
    runner.cancel()
    return runner.outcome(scenario="S01")


def _scenario_s02() -> RunOutcome:
    runner = FakeJobRunner()
    runner.start()
    for _ in range(3):
        runner.advance()
    runner.pause()
    runner.advance()
    paused_done = runner.stage_pointer
    runner.resume()
    runner.run_all()
    return runner.outcome(scenario="S02", paused_after_stages=paused_done)


def _scenario_s02b() -> RunOutcome:
    runner = FakeJobRunner()
    runner.start()
    for _ in range(3):
        runner.advance()
    runner.pause()
    runner.cancel()
    runner.advance()
    return runner.outcome(scenario="S02B", paused_after_stages=3)


def _scenario_s03() -> RunOutcome:
    runner = FakeJobRunner()
    runner.start()
    for _ in range(3):
        runner.advance()
    runner.pause()
    runner.advance()
    paused_done = runner.stage_pointer
    runner.cancel()
    runner.advance()
    return runner.outcome(scenario="S03", paused_after_stages=paused_done)


def _scenario_s04() -> RunOutcome:
    runner = FakeJobRunner(fail_after="news")
    runner.run_all()
    return runner.outcome(scenario="S04")


def _scenario_s04b() -> RunOutcome:
    runner = FakeJobRunner(graph=FakeAnalysisGraph(fail_at="news"))
    runner.run_all()
    return runner.outcome(scenario="S04B")


def _scenario_with_interrupt(scenario: str, point: str) -> RunOutcome:
    runner = FakeJobRunner(interrupt_at=point)
    try:
        runner.run_all()
    except SimulatedInterrupt:
        pass
    runner.reconcile()
    return runner.outcome(scenario=scenario, interrupt_at=point)


def _scenario_s05() -> RunOutcome:
    return _scenario_with_interrupt("S05", "before:pm")


def _scenario_s06() -> RunOutcome:
    return _scenario_with_interrupt("S06", "after:news")


def _scenario_s07() -> RunOutcome:
    return _scenario_with_interrupt("S07", "after_report")


def _scenario_s08() -> RunOutcome:
    return _scenario_with_interrupt("S08", "after_commit")


def _scenario_s09() -> RunOutcome:
    runner = FakeJobRunner(auto_finalize=False)
    runner.start()
    for _ in range(TOTAL_STAGES):
        runner.advance()
    runner.cancel()
    runner.finalize()
    return runner.outcome(scenario="S09")


def _scenario_s09b() -> RunOutcome:
    runner = FakeJobRunner(auto_finalize=False)
    runner.start()
    for _ in range(TOTAL_STAGES):
        runner.advance()
    runner.cancel()
    runner.finalize(cancel_wins=True)
    return runner.outcome(scenario="S09B")


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    contract: str
    run: Callable[[], RunOutcome]


SCENARIOS: dict[str, Scenario] = {
    scenario.id: scenario
    for scenario in (
        Scenario("S00", "正常完成", "T01/T02/T03；SSE 终态顺序", _scenario_s00),
        Scenario("S01", "创建后立即取消", "T19", _scenario_s01),
        Scenario("S02", "运行中暂停", "T05/T06/T09", _scenario_s02),
        Scenario("S02B", "暂停请求已受理后取消", "T12/T13", _scenario_s02b),
        Scenario("S03", "暂停后取消", "T20/T13", _scenario_s03),
        Scenario("S04", "阶段完成后异常", "T04", _scenario_s04),
        Scenario("S04B", "阶段执行中异常", "T04", _scenario_s04b),
        Scenario("S05", "最终报告前中断", "B2/T16", _scenario_s05),
        Scenario("S06", "阶段产物已写、事件未保存", "B3/T16", _scenario_s06),
        Scenario("S07", "最终报告后、数据库提交前中断", "B4/T16", _scenario_s07),
        Scenario("S08", "报告已提交、完成事件未发", "B5", _scenario_s08),
        Scenario("S09", "取消迟到，收尾先落盘", "B6/T14", _scenario_s09),
        Scenario("S09B", "取消先确认，收尾产物丢弃", "B6/T13", _scenario_s09b),
    )
}

INTERACTION_SCENARIOS: dict[str, str] = {
    "S10": "重复启动请求",
    "S11": "多浏览器重连",
    "S12": "事件断线后补发",
}


def run_scenario(name: str) -> RunOutcome:
    key = name.upper()
    if key not in SCENARIOS:
        known = ", ".join(SCENARIOS)
        raise KeyError(f"unknown scenario {name}; known: {known}")
    return SCENARIOS[key].run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a deterministic fake-analysis scenario."
    )
    parser.add_argument("--scenario", default="S00")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.list:
        for scenario in SCENARIOS.values():
            print(f"{scenario.id:<5} {scenario.title}  [{scenario.contract}]")
        for key, title in INTERACTION_SCENARIOS.items():
            print(f"{key:<5} {title}  [见测试 GF-17/GF-18/GF-19]")
        return 0

    summary = run_scenario(args.scenario).summary()
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"{summary['scenario']} {summary['status']}")
        print(
            f"阶段完成 {summary['stages_done']}/{TOTAL_STAGES}，"
            f"事件 {summary['events']} 条，模型调用 {summary['model_calls']} 次"
        )
        print(
            f"报告写入={summary['report_written']} "
            f"提交={summary['report_committed']} "
            f"report_id={summary['report_id']}"
        )
        if summary["reconcile_notes"]:
            print("对账备注: " + ", ".join(summary["reconcile_notes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
