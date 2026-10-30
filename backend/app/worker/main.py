"""Worker shell: global lease ownership plus a background heartbeat.

P1-05 stops at claiming. Executing a claimed job arrives with P1-06, and
pause/cancel interception with P1-08, so nothing here guesses how the graph
runs. The important invariants already live here:

* exactly one worker owns the lease at a time; a second worker's acquire
  returns False and it must not claim anything;
* the heartbeat renews the row at a fixed interval and flags `lost` on the
  first failure, so the owning loop can stop touching jobs;
* shutdown releases the lease only if this owner still holds it.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import timedelta

from backend.app.models.job import Job
from backend.app.services.lease import DEFAULT_HEARTBEAT_INTERVAL, LeaseService

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
        owner: str | None = None,
        heartbeat_interval: timedelta = DEFAULT_HEARTBEAT_INTERVAL,
    ) -> None:
        self.owner = owner or f"worker-{uuid.uuid4().hex[:8]}"
        self._lease = lease
        self._heartbeat = Heartbeat(lease, self.owner, heartbeat_interval)
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

    def shutdown(self) -> None:
        if not self._acquired:
            return
        self._heartbeat.stop()
        self._lease.release(self.owner)
        self._acquired = False
