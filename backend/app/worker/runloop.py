"""Worker thread loop and shutdown handling shared by both entries.

``scripts/dev_backend.py`` and ``scripts/run_backend.py`` run the API and one
worker in the same process. The loop keeps retrying the global lease, so a
restart after a crash takes over once the previous lease expires. The first
signal stops both loops gracefully; a second one forces the server down.
"""

from __future__ import annotations

import logging
import signal
import threading

import uvicorn

from backend.app.worker.main import Worker

POLL_SECONDS = 0.1
LEASE_RETRY_SECONDS = 1.0

logger = logging.getLogger(__name__)


def worker_loop(worker: Worker, stop: threading.Event) -> None:
    try:
        while not stop.is_set():
            if not worker.acquired:
                if worker.acquire():
                    logger.info("worker %s owns the lease", worker.owner)
                else:
                    stop.wait(LEASE_RETRY_SECONDS)
                    continue
            if worker.lost:
                logger.error("worker lost the lease; stopping")
                return
            try:
                outcome = worker.run_once()
            except Exception:
                logger.exception("worker iteration failed")
                stop.wait(LEASE_RETRY_SECONDS)
                continue
            if outcome is None:
                stop.wait(POLL_SECONDS)
    finally:
        worker.shutdown()


def install_shutdown_handlers(server: uvicorn.Server, stop: threading.Event) -> None:
    """First signal stops both loops gracefully; a second one forces the server."""

    def handle(signum, _frame) -> None:
        logger.info("received signal %s; shutting down", signum)
        if stop.is_set():
            server.force_exit = True
            return
        stop.set()
        server.should_exit = True

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, handle)
