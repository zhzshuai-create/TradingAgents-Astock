"""Worker shell: global lease ownership, heartbeat, execution and stage writes.

P1-05 covers ownership and claiming; P1-06 adds the executor call; P1-07
persists every stage boundary (row + stage_changed + stats) and writes each
stage report before its ``done`` commit. Control requests (P1-08) and terminal
transitions (P1-09) extend this seam instead of replacing it.

* exactly one worker owns the lease at a time; a second worker's acquire
  returns False and it must not claim anything;
* the heartbeat renews the row at a fixed interval and flags `lost` on the
  first failure, so the owning loop can stop touching jobs;
* shutdown releases the lease only if this owner still holds it;
* the executor defaults to the deterministic fake graph; real models need
  both the environment variable and the server config flag (AD-01);
* stage commit order is started -> report file -> done -> stats, so the only
  crash window is a written file without its done event (B3), never a done
  event without its report.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import timedelta

from backend.app.core.server_config import ServerConfig
from backend.app.models.job import Job
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

logger = logging.getLogger(__name__)


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
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    @property
    def lost(self) -> bool:
        return self._heartbeat.lost

    def acquire(self) -> bool:
        """Take the global lease and start renewing it; False if taken."""
        if self._acquired:
            return True
        if not self._lease.acquire(self.owner):
            return False
        self._acquired = True
        self._heartbeat.start()
        return True

    def claim(self) -> Job | None:
        if not self._acquired or self._heartbeat.lost:
            return None
        return self._lease.claim_next_job(self.owner)

    def run_once(self) -> tuple[Job, RunResult] | None:
        """Claim one queued job, run it, and persist every stage boundary."""
        job = self.claim()
        if job is None:
            return None
        cumulative = StatsSnapshot()

        def on_stage(progress: StageProgress) -> None:
            nonlocal cumulative
            if progress.phase == "started":
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

        result = self._executor.run(
            AnalysisRequest(
                ticker_code=job.ticker_code, analysis_date=job.analysis_date
            ),
            on_stage=on_stage,
        )
        # The 13th stats event lands before the terminal transition (P1-09).
        self._jobs.record_stats(
            job.id,
            StatsSnapshot(
                model_calls=result.stats.model_calls,
                tokens_in=result.stats.tokens_in,
                tokens_out=result.stats.tokens_out,
                elapsed_ms=result.stats.elapsed_ms,
            ),
        )
        return job, result

    def shutdown(self) -> None:
        if not self._acquired:
            return
        self._heartbeat.stop()
        self._lease.release(self.owner)
        self._acquired = False
