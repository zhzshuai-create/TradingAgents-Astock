"""Startup reconciliation: orphans become interrupted, never auto-rerun.

job-state-machine.md section 4 fixes the scan order. A live global lease means
the execution process is up, so nothing is an orphan and the scan is skipped.
Otherwise:

* terminal rows are untouched (B6 leaves whichever terminal write won);
* queued rows stay queued and are claimed normally (B1);
* paused rows stay paused while their checkpoint artifacts are readable, and
  become ``interrupted(checkpoint_missing)`` when they are not;
* running / pause_requested / cancel_requested rows become ``interrupted``.
  The detail is ``unregistered_report`` when a complete final report artifact
  exists (B4), ``unregistered_stage_output`` when an active stage has its file
  (B3), and ``lease_expired`` otherwise (B2).

B3/B4 also append ``reconcile_note`` audit rows in the same transaction. The
notes never consume a ``seq``. Resume starts after the last artifact on disk,
so a stage whose report was written but whose done event was lost is not run
again.

The one succeeded-row case is B5: the report committed but ``report_ready``
did not. Reconcile appends that event at the tail; it never rewrites status.

This module only decides; every write goes through JobService conditionals.
There is no graph call and no model call anywhere in this file.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from backend.app.models.stage import STAGE_IDS, STAGE_NAMES
from backend.app.services.job_service import (
    JobService,
    ReconcileNote,
    StageLocation,
)
from backend.app.services.lease import LeaseService
from backend.app.services.report_store import ReportStore

WORKER_HELD_STATUSES = ("running", "pause_requested", "cancel_requested")
FINAL_STATUSES = ("cancelled", "succeeded", "failed", "interrupted")


@dataclass(frozen=True)
class ReconcileOutcome:
    job_id: str
    before: str
    after: str
    detail: str | None = None
    notes: tuple[ReconcileNote, ...] = ()
    report_ready_appended: bool = False


class Reconciler:
    def __init__(
        self,
        jobs: JobService,
        reports: ReportStore,
        *,
        lease: LeaseService | None = None,
        owner: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._jobs = jobs
        self._reports = reports
        self._lease = lease
        self._owner = owner
        self._clock = clock or jobs.now

    def run(self) -> list[ReconcileOutcome]:
        live = self._lease.live_owner() if self._lease is not None else None
        if live is not None and live != self._owner:
            return []
        outcomes: list[ReconcileOutcome] = []
        for job_id, status, resume_from_stage in self._jobs.reconcile_scan():
            outcome = self.reconcile_job(
                job_id, status=status, resume_from_stage=resume_from_stage
            )
            if outcome is not None:
                outcomes.append(outcome)
        return outcomes

    def reconcile_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        resume_from_stage: str | None = None,
    ) -> ReconcileOutcome | None:
        before = status or self._jobs.job_status(job_id)
        if before is None:
            return None
        if before == "succeeded":
            if self._jobs.append_report_ready_if_missing(job_id):
                return ReconcileOutcome(
                    job_id, before, before, report_ready_appended=True
                )
            return None
        if before == "queued":
            return None
        if before == "paused":
            if self._checkpoint_present(job_id, resume_from_stage):
                return None
            detail, notes = "checkpoint_missing", ()
        elif before in WORKER_HELD_STATUSES:
            detail, notes = self._worker_held_evidence(job_id)
        elif before in FINAL_STATUSES:
            return None
        else:
            return None

        checkpoint = self._resume_point(job_id, resume_from_stage)
        if not self._jobs.mark_interrupted(
            job_id,
            detail=detail,
            notes=notes,
            resume_from_stage=checkpoint,
        ):
            return None
        return ReconcileOutcome(
            job_id,
            before,
            "interrupted",
            detail=detail,
            notes=tuple(notes),
        )

    def _worker_held_evidence(
        self, job_id: str
    ) -> tuple[str, tuple[ReconcileNote, ...]]:
        if self._reports.read_final_report(job_id) is not None:
            return (
                "unregistered_report",
                (self._note("unregistered_report", "发现一份未登记的完整报告"),),
            )
        locations = self._jobs.stage_locations(job_id)
        files = self._reports.stage_report_paths(job_id)
        notes = tuple(
            self._note(
                "unregistered_stage_output",
                f"发现未登记的阶段产物：{STAGE_NAMES[stage_id]}",
            )
            for stage_id in STAGE_IDS
            if stage_id in files
            and stage_id in locations
            and locations[stage_id].status == "active"
        )
        if notes:
            return "unregistered_stage_output", notes
        return "lease_expired", ()

    def _checkpoint_present(
        self, job_id: str, resume_from_stage: str | None
    ) -> bool:
        """A pause is resumable only while every done stage artifact is there.

        The checkpoint is the set of stage reports the done rows reference; if
        any one is gone, resuming without re-running that stage is impossible.
        """
        if resume_from_stage is None:
            return False
        locations: dict[str, StageLocation] = self._jobs.stage_locations(job_id)
        for location in locations.values():
            if location.status not in ("done", "skipped"):
                continue
            if not location.report_path:
                return False
            try:
                if self._reports.read_stage_report(location.report_path) is None:
                    return False
            except ValueError:
                return False
        return True

    def _resume_point(
        self, job_id: str, resume_from_stage: str | None
    ) -> str | None:
        """First stage with no done row and no finished artifact.

        A stored checkpoint is a lower bound: a resumed job silently consumed
        its prefix without creating stage rows, so reconciliation must not move
        the start earlier than the user's last resume point. B3 skips the
        active stage whose file already exists (crash-boundaries.md B3).
        """
        locations = self._jobs.stage_locations(job_id)
        files = self._reports.stage_report_paths(job_id)
        candidate: int | None = None
        for index, stage_id in enumerate(STAGE_IDS):
            location = locations.get(stage_id)
            state = location.status if location is not None else None
            if state in ("done", "skipped"):
                continue
            if state == "active" and stage_id in files:
                continue
            candidate = index
            break
        stored = (
            STAGE_IDS.index(resume_from_stage)
            if resume_from_stage in STAGE_IDS
            else None
        )
        if stored is not None and (candidate is None or stored > candidate):
            candidate = stored
        return STAGE_IDS[candidate] if candidate is not None else None

    def _note(self, code: str, message: str) -> ReconcileNote:
        return ReconcileNote(
            code=code,
            message=message,
            at=self._clock().isoformat(timespec="seconds"),
        )
