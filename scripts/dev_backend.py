"""Development entry: FastAPI and one worker in the same process.

P2-01. The entry always writes under a temp root (``TA_DEV_ROOT`` or the OS
temp directory), never ``~/.tradingagents``. The API and the worker share one
engine, one JobService and one ReportStore; ``create_app()`` is given these
objects instead of building its own.

Switches:

* ``--no-worker``       start the API only, so queued jobs stay queued;
* ``--port``            API port, default 8600;
* ``--stage-delay-ms``  sleep after each stage boundary, default 0; the fake
                        graph module itself is never modified;
* ``--ticker-fixture``  offline code -> name JSON; it becomes the in-memory
                        search directory instead of the mootdx disk cache.

The worker keeps retrying the global lease, so a restart after a crash takes
over once the previous lease expires instead of giving up on startup.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import load_server_config  # noqa: E402
from backend.app.core.write_mode import WRITE_MODE_ENV  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.services.analysis_runner import (  # noqa: E402
    AnalysisExecutor,
    AnalysisRunError,
    AnalysisRequest,
    ChunkHook,
    RunResult,
    StageHook,
    StageProgress,
    create_analysis_executor,
)
from backend.app.services.job_service import JobService  # noqa: E402
from backend.app.services.lease import LeaseService  # noqa: E402
from backend.app.services.report_store import (  # noqa: E402
    JOB_REPORTS_ENV,
    ReportStore,
)
from backend.app.services.ticker_directory import TickerDirectory  # noqa: E402
from backend.app.worker.main import Worker  # noqa: E402
from backend.app.worker.runloop import (  # noqa: E402
    install_shutdown_handlers,
    worker_loop,
)

DEV_ROOT_ENV = "TA_DEV_ROOT"
DEFAULT_PORT = 8600

logger = logging.getLogger("astock.dev")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AStock Pro dev API + worker")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-worker", action="store_true")
    parser.add_argument("--stage-delay-ms", type=int, default=0)
    parser.add_argument("--ticker-fixture", type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.stage_delay_ms < 0:
        parser.error("--stage-delay-ms must be >= 0")
    return args


def dev_root(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    override = env.get(DEV_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return Path(tempfile.gettempdir()) / "astock-dev"


def load_ticker_fixture(path: Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"[dev] cannot read --ticker-fixture {path}: {exc}") from exc
    if not isinstance(data, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in data.items()
    ):
        raise SystemExit("[dev] --ticker-fixture must be a JSON object of code: name")
    return data


def migrate_and_build(root: Path):
    """Pin the process to the temp root, upgrade to head, return (db, reports, engine)."""
    db_path = root / "jobs.db"
    reports_path = root / "reports"
    root.mkdir(parents=True, exist_ok=True)
    os.environ[JOBS_DB_ENV] = str(db_path)
    os.environ[JOB_REPORTS_ENV] = str(reports_path)

    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    command.upgrade(config, "head")
    return db_path, reports_path, build_engine(db_path)


class StageDelayExecutor:
    """Sleeps after each completed stage so E2E can observe boundaries."""

    name = "fake-delayed"

    def __init__(self, inner: AnalysisExecutor, delay_ms: int) -> None:
        self._inner = inner
        self._delay = delay_ms / 1000

    def run(
        self,
        request: AnalysisRequest,
        *,
        on_stage: StageHook | None = None,
        on_chunk: ChunkHook | None = None,
    ) -> RunResult:
        def stage(progress: StageProgress) -> None:
            if on_stage is not None:
                on_stage(progress)
            if progress.phase == "done" and self._delay > 0:
                time.sleep(self._delay)

        return self._inner.run(request, on_stage=stage, on_chunk=on_chunk)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    root = dev_root()
    db_path, reports_path, engine = migrate_and_build(root)
    fixture = load_ticker_fixture(args.ticker_fixture)
    # This entry serves the new UI, so it is a writer unless told otherwise.
    os.environ.setdefault(WRITE_MODE_ENV, "next")
    server_config = load_server_config()
    reports = ReportStore(reports_path)
    jobs = JobService(engine, server_config, reports=reports)
    directory = TickerDirectory(fixture) if fixture is not None else None
    app = create_app(
        service=jobs,
        server_config=server_config,
        report_store=reports,
        ticker_directory=directory,
    )

    stop = threading.Event()
    thread: threading.Thread | None = None
    if not args.no_worker:
        try:
            executor: AnalysisExecutor = create_analysis_executor(server_config)
        except AnalysisRunError as exc:
            engine.dispose()
            raise SystemExit(f"[dev] {exc.message}") from exc
        if args.stage_delay_ms > 0:
            executor = StageDelayExecutor(executor, args.stage_delay_ms)
        worker = Worker(
            LeaseService(engine),
            jobs=jobs,
            reports=reports,
            owner="dev-worker",
            executor=executor,
        )
        thread = threading.Thread(
            target=worker_loop,
            args=(worker, stop),
            name="dev-worker",
            daemon=True,
        )
        thread.start()

    logger.info("API      http://127.0.0.1:%d", args.port)
    logger.info("temp DB  %s", db_path)
    logger.info("reports  %s", reports_path)
    logger.info("worker   %s", "off (--no-worker)" if args.no_worker else "on")

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=args.port,
            log_level="info",
        )
    )
    install_shutdown_handlers(server, stop)
    # uvicorn runs in a thread so this process owns signal handling and can
    # release the lease after the server has actually stopped.
    server_thread = threading.Thread(target=server.run, name="dev-api", daemon=True)
    server_thread.start()
    try:
        while server_thread.is_alive() and not stop.wait(0.2):
            pass
        server_thread.join(timeout=15)
        if server_thread.is_alive():
            logger.warning("API did not stop within 15s; forcing exit")
            server.force_exit = True
            server_thread.join(timeout=5)
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=30)
            if thread.is_alive():
                logger.warning("worker did not stop within 30s; leaving it")
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
