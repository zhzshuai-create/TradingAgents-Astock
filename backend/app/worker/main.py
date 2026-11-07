"""Worker shell: global lease ownership, heartbeat, execution and stage writes.

P1-05 covers ownership and claiming; P1-06 adds the executor call; P1-07
persists every stage boundary (row + stage_changed + stats) and writes each
stage report before its ``done`` commit. P1-08 turns the run into a loop that
honours control requests at stage boundaries:

* pause_requested -> paused (T06), releasing the per-job lease so the worker
  can take another job;
* cancel_requested -> cancelled (T13) with a final stats event first;
* a graph that finishes while pause/cancel is pending ends succeeded with
  detail ``pause_noop`` / ``cancel_noop`` (T07/T14), and the completed run's
  report is still committed with ``report_ready`` (P1-09);
* an executor exception lands ``failed`` with the active stage marked failed
  (detail ``stage_failed``) or, between stages, ``post_stage_error``;
* paused -> running (T09) rows are re-attached without a second T02 event and
  restart at ``resume_from_stage``, so completed stages are not re-executed;
* a cancel_requested row with no lease (T20 from paused) is claimed and
  finished without running the graph;
* every boundary checks ``lost`` first; a lost lease stops all writes and
  leaves the row for startup reconciliation (P1-10);
* ``acquire`` runs the startup reconcile once, after taking the global lease
  and before any claim: orphaned running/pause_requested/cancel_requested rows
  become ``interrupted`` (never auto-rerun), a paused row whose artifacts are
  gone becomes ``interrupted(checkpoint_missing)``, and B5 appends the missing
  ``report_ready``. ``TA_STARTUP_RECONCILE=0`` turns the scan off;
* before the terminal transaction the executor's report is written to
  ``<job>/report.json``; a crash between that write and the commit is B4, and
  reconcile records it without importing it.

Everything else stays where it was: exactly one worker owns the global lease,
the heartbeat renews it, shutdown releases only its own lease, and the default
executor is the deterministic fake graph (real models need both the env flag
and the server config flag, AD-01).
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from backend.app.core.server_config import ServerConfig
from backend.app.models.job import Job
from backend.app.models.stage import STAGE_IDS
from backend.app.services.analysis_runner import (
    AnalysisExecutor,
    AnalysisRequest,
    RunResult,
    StageProgress,
    create_analysis_executor,
)
from backend.app.services.job_service import JobService, StatsSnapshot
from backend.app.services.lease import DEFAULT_HEARTBEAT_INTERVAL, LeaseService
from backend.app.services.report_store import ReportStore
from backend.app.worker.reconcile import Reconciler

logger = logging.getLogger(__name__)

RECONCILE_ENV = "TA_STARTUP_RECONCILE"


def startup_reconcile_enabled(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """On by default; ``TA_STARTUP_RECONCILE=0`` is the rollback switch."""
    env = os.environ if environ is None else environ
    return env.get(RECONCILE_ENV, "1") != "0"


class _Stopped(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class WorkerOutcome:
    """One claim's result: a full run, a control stop, or a lost lease."""

    job: Job
    result: RunResult | None = None
    stopped: str | None = None


class Heartbeat:
    def __init__(
        self,
        lease: LeaseService,
        owner: str,
        interval: timedelta = DEFAULT_HEARTBEAT_INTERVAL,
    ) -> None:
        if interval <= timedelta(0):
            raise ValueError("heartbeat interval must be positive")
        self._lease = lease
        self._owner = owner
        self._interval = interval.total_seconds()
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"lease-heartbeat-{owner}", daemon=True
        )

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=self._interval + 1)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                renewed = self._lease.heartbeat(self._owner)
            except Exception:
                logger.exception("lease heartbeat failed for %s", self._owner)
                self._lost.set()
                return
            if not renewed:
                logger.warning("lease lost by %s; heartbeat stops", self._owner)
                self._lost.set()
                return


class Worker:
    def __init__(
        self,
        lease: LeaseService,
        *,
        jobs: JobService,
        reports: ReportStore,
        owner: str | None = None,
        heartbeat_interval: timedelta = DEFAULT_HEARTBEAT_INTERVAL,
        executor: AnalysisExecutor | None = None,
        server_config: ServerConfig | None = None,
        reconcile_on_start: bool | None = None,
    ) -> None:
        self.owner = owner or f"worker-{uuid.uuid4().hex[:8]}"
        self._lease = lease
        self._jobs = jobs
        self._reports = reports
        self._heartbeat = Heartbeat(lease, self.owner, heartbeat_interval)
        self._executor = (
            executor
            if executor is not None
            else create_analysis_executor(server_config)
        )
        self._reconcile_on_start = (
            startup_reconcile_enabled()
            if reconcile_on_start is None
            else reconcile_on_start
        )
        self._reconciler = Reconciler(
            jobs, reports, lease=lease, owner=self.owner, clock=jobs.now
        )
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    @property
    def lost(self) -> bool:
        return self._heartbeat.lost

    def acquire(self) -> bool:
        """Take the global lease and start renewing it; False if taken.

        The startup reconcile runs once, after the lease is ours and before
        the first claim. It cannot touch the job this worker is about to run,
        because nothing is claimed yet.
        """
        if self._acquired:
            return True
        if not self._lease.acquire(self.owner):
            return False
        self._acquired = True
        self._heartbeat.start()
        if self._reconcile_on_start:
            self._reconciler.run()
        return True

    def claim(self) -> Job | None:
        """Priority: control finish, T09 re-attach, then a queued job."""
        if not self._acquired or self._heartbeat.lost:
            return None
        control = self._lease.claim_control_job(self.owner)
        if control is not None:
            return control
        resumed = self._lease.claim_resumed_job(self.owner)
        if resumed is not None:
            return resumed
        return self._lease.claim_next_job(self.owner)

    def run_once(self) -> WorkerOutcome | None:
        """Claim one job and run it until it pauses, cancels, completes or dies."""
        job = self.claim()
        if job is None:
            return None
        if job.status == "cancel_requested":
            self._jobs.cancel_at_boundary(job.id)
            return WorkerOutcome(
                job=self._jobs.get_job(job.id) or job, stopped="cancelled"
            )
        return self._run(job)

    def _run(self, job: Job) -> WorkerOutcome:
        cumulative = self._jobs.latest_stats(job.id)
        resume_from = job.resume_from_stage or self._jobs.first_unfinished_stage(
            job.id
        )
        if resume_from == STAGE_IDS[0]:
            resume_from = None

        def on_stage(progress: StageProgress) -> None:
            nonlocal cumulative
            if progress.phase == "started":
                self._check_boundary(job.id)
                self._jobs.start_stage(
                    job.id,
                    progress.stage_id,
                    index=progress.index,
                    total=progress.total,
                )
                return
            report_path = None
            if progress.report_text is not None:
                report_path = self._reports.write_stage_report(
                    job.id, progress.stage_id, progress.report_text
                )
            cumulative = StatsSnapshot(
                model_calls=cumulative.model_calls + progress.model_calls,
                tokens_in=cumulative.tokens_in + progress.tokens_in,
                tokens_out=cumulative.tokens_out + progress.tokens_out,
                elapsed_ms=cumulative.elapsed_ms + progress.duration_ms,
            )
            self._jobs.finish_stage(
                job.id,
                progress.stage_id,
                index=progress.index,
                total=progress.total,
                stats=cumulative,
                report_path=report_path,
                duration_ms=progress.duration_ms,
            )

        try:
            result = self._executor.run(
                AnalysisRequest(
                    ticker_code=job.ticker_code,
                    analysis_date=job.analysis_date,
                    resume_from_stage=resume_from,
                    job_id=job.id,
                    generated_at=self._jobs.now(),
                    retry_of_job_id=job.retry_of_job_id,
                    config=dict(job.config_snapshot or {}),
                ),
                on_stage=on_stage,
            )
        except _Stopped as stop:
            return WorkerOutcome(
                job=self._jobs.get_job(job.id) or job, stopped=stop.reason
            )
        except Exception as exc:
            if self._heartbeat.lost:
                return WorkerOutcome(
                    job=self._jobs.get_job(job.id) or job, stopped="lost"
                )
            if self._jobs.job_status(job.id) not in (
                "running",
                "pause_requested",
                "cancel_requested",
            ):
                return WorkerOutcome(
                    job=self._jobs.get_job(job.id) or job, stopped="stopped"
                )
            code = getattr(exc, "code", None) or "internal_error"
            message = getattr(exc, "message", None) or "分析执行失败"
            self._jobs.finish_failure(
                job.id, code=str(code), message=str(message), stats=cumulative
            )
            return WorkerOutcome(
                job=self._jobs.get_job(job.id) or job, stopped="failed"
            )

        # The graph finished during the request window: T07/T14 win over the
        # pending control, which is recorded as a no-op detail. The report and
        # its report_ready are committed either way.
        status = self._jobs.job_status(job.id)
        if status in ("pause_requested", "cancel_requested"):
            detail = "pause_noop" if status == "pause_requested" else "cancel_noop"
            self._publish_report(job.id, result.report)
            self._jobs.finish_success(
                job.id, detail=detail, stats=cumulative, report=result.report
            )
            return WorkerOutcome(
                job=self._jobs.get_job(job.id) or job,
                result=result,
                stopped=status,
            )
        if self._heartbeat.lost:
            return WorkerOutcome(
                job=self._jobs.get_job(job.id) or job,
                result=result,
                stopped="lost",
            )
        # T03: one transaction writes the report row, the 13th stats event,
        # the terminal status event and report_ready. The report file goes to
        # disk first; a crash in between is B4 and reconcile only notes it.
        self._publish_report(job.id, result.report)
        self._jobs.finish_success(
            job.id, detail=None, stats=cumulative, report=result.report
        )
        return WorkerOutcome(job=self._jobs.get_job(job.id) or job, result=result)

    def _publish_report(
        self, job_id: str, report: Mapping[str, Any] | None
    ) -> None:
        """Write the complete report to ``<job>/report.json`` before commit.

        The file is evidence for reconciliation (B4), never a source of truth:
        a crash after this write leaves a worker-held row next to a full
        report, which reconcile marks ``unregistered_report`` and never
        imports. A failed write must not fail the run itself; the database
        commit is authoritative.
        """
        if report is None or self._heartbeat.lost:
            return
        try:
            self._reports.write_final_report(job_id, report)
        except OSError:
            logger.exception(
                "failed to write the final report artifact for %s", job_id
            )

    def _check_boundary(self, job_id: str) -> None:
        """Must run before a stage starts; raises _Stopped to leave the loop."""
        if self._heartbeat.lost:
            raise _Stopped("lost")
        status = self._jobs.job_status(job_id)
        if status == "cancel_requested":
            self._jobs.cancel_at_boundary(job_id)
            raise _Stopped("cancelled")
        if status == "pause_requested":
            if self._jobs.pause_at_boundary(job_id):
                raise _Stopped("paused")
            if self._jobs.job_status(job_id) == "cancel_requested":
                self._jobs.cancel_at_boundary(job_id)
                raise _Stopped("cancelled")
            raise _Stopped("stopped")
        if status != "running":
            raise _Stopped("stopped")

    def shutdown(self) -> None:
        if not self._acquired:
            return
        self._heartbeat.stop()
        self._lease.release(self.owner)
        self._acquired = False
