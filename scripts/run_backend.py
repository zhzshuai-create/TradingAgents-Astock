"""Real data-root entry: FastAPI and one worker against ``~/.tradingagents``.

P6-04pre. Unlike ``dev_backend.py`` this entry never points the store at a
temp directory; ``TA_DATA_ROOT`` moves it, and ``TA_JOBS_DB`` /
``TA_JOB_REPORTS_DIR`` override the individual paths.

The repo ``.env`` is loaded first so provider credentials reach the model
clients. Real models stay behind the AD-01 double switch:

* ``--real-models`` sets ``ServerConfig.real_runner_enabled``;
* ``TA_ENABLE_REAL_RUNNER=1`` stays in the operator's environment.

Without both, the worker runs the fake graph. ``--real-models`` without the
environment flag exits instead of silently running the fake.

``ACTIVE_ANALYSIS_UI`` is read from the environment and never rewritten here,
and there is no 8501 interlock yet; both belong to P6-06. This entry is meant
for supervised runs (Canary) until that ticket lands.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import (  # noqa: E402
    EXPORTS_DIR_ENV,
    JOBS_DB_ENV,
    get_exports_dir,
)
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import load_server_config  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.services.analysis_runner import (  # noqa: E402
    REAL_RUNNER_ENV,
    REAL_RUNNER_ENV_VALUE,
    AnalysisExecutor,
    AnalysisRunError,
    create_analysis_executor,
)
from backend.app.services.chart_snapshot import MarketChartSnapshotter  # noqa: E402
from backend.app.services.job_service import JobService  # noqa: E402
from backend.app.services.lease import LeaseService  # noqa: E402
from backend.app.services.market_cache import MarketCache  # noqa: E402
from backend.app.services.market_providers import DefaultMarketProviders  # noqa: E402
from backend.app.services.real_runner import DATA_ROOT_ENV  # noqa: E402
from backend.app.services.report_store import (  # noqa: E402
    JOB_REPORTS_ENV,
    ReportStore,
)
from backend.app.services.stock_service import StockService  # noqa: E402
from backend.app.worker.main import Worker  # noqa: E402
from backend.app.worker.runloop import (  # noqa: E402
    install_shutdown_handlers,
    worker_loop,
)

DEFAULT_PORT = 8600
DEFAULT_ROOT = Path.home() / ".tradingagents"
CHART_SNAPSHOT_ENV = "TA_CHART_SNAPSHOT"

logger = logging.getLogger("astock.backend")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AStock Pro real API + worker")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-worker", action="store_true")
    parser.add_argument(
        "--real-models",
        action="store_true",
        help="set the server-config half of the AD-01 switch",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    return args


def data_root(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    override = env.get(DATA_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_ROOT


def resolve_paths(
    root: Path, environ: Mapping[str, str] | None = None
) -> tuple[Path, Path]:
    """Database and job-report paths; explicit env vars win over the root."""
    env = os.environ if environ is None else environ
    db_override = env.get(JOBS_DB_ENV)
    reports_override = env.get(JOB_REPORTS_ENV)
    db_path = Path(db_override).expanduser() if db_override else root / "jobs.db"
    reports_path = (
        Path(reports_override).expanduser() if reports_override else root / "job_reports"
    )
    return db_path, reports_path


def migrate() -> None:
    """Upgrade the configured database to head (reads JOBS_DB_ENV)."""
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    command.upgrade(config, "head")


def chart_snapshot_enabled(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """On by default; ``TA_CHART_SNAPSHOT=0`` is the RPT-01 rollback switch."""
    env = os.environ if environ is None else environ
    return env.get(CHART_SNAPSHOT_ENV, "1") != "0"


def build_chart_snapshotter(
    providers: DefaultMarketProviders,
    cache: MarketCache,
    environ: Mapping[str, str] | None = None,
) -> MarketChartSnapshotter | None:
    if not chart_snapshot_enabled(environ):
        return None
    return MarketChartSnapshotter(StockService(providers, cache))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Credentials only: model clients read them lazily when the graph is built.
    load_dotenv(ROOT / ".env")

    if args.real_models and os.environ.get(REAL_RUNNER_ENV) != REAL_RUNNER_ENV_VALUE:
        raise SystemExit(
            f"[backend] --real-models also needs {REAL_RUNNER_ENV}=1 (AD-01)"
        )

    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    db_path, reports_path = resolve_paths(root)
    os.environ.setdefault(DATA_ROOT_ENV, str(root))
    os.environ[JOBS_DB_ENV] = str(db_path)
    os.environ[JOB_REPORTS_ENV] = str(reports_path)
    os.environ.setdefault(EXPORTS_DIR_ENV, str(root / "exports"))

    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrate()
    reports = ReportStore(reports_path)
    engine = build_engine(db_path)
    server_config = load_server_config()
    if args.real_models:
        server_config = replace(server_config, real_runner_enabled=True)
    jobs = JobService(engine, server_config, reports=reports)
    market_providers = DefaultMarketProviders()
    market_cache = MarketCache()
    app = create_app(
        service=jobs,
        server_config=server_config,
        report_store=reports,
        market_providers=market_providers,
        market_cache=market_cache,
    )

    stop = threading.Event()
    thread: threading.Thread | None = None
    if not args.no_worker:
        try:
            executor: AnalysisExecutor = create_analysis_executor(server_config)
        except AnalysisRunError as exc:
            engine.dispose()
            raise SystemExit(f"[backend] {exc.message}") from exc
        if executor.name != "real":
            logger.warning(
                "worker runs the fake graph: --real-models and %s=1 are both required",
                REAL_RUNNER_ENV,
            )
        snapshotter = build_chart_snapshotter(market_providers, market_cache)
        if snapshotter is None:
            logger.info("chart snapshot off (%s=0)", CHART_SNAPSHOT_ENV)
        worker = Worker(
            LeaseService(engine),
            jobs=jobs,
            reports=reports,
            owner="backend-worker",
            executor=executor,
            chart_snapshotter=snapshotter,
        )
        thread = threading.Thread(
            target=worker_loop,
            args=(worker, stop),
            name="backend-worker",
            daemon=True,
        )
        thread.start()

    logger.info("API      http://127.0.0.1:%d", args.port)
    logger.info("data root %s", root)
    logger.info("database %s", db_path)
    logger.info("reports  %s", reports_path)
    logger.info("exports  %s", get_exports_dir())
    logger.info("write    %s", server_config.write_mode)
    logger.info(
        "worker   %s",
        "off (--no-worker)"
        if args.no_worker
        else ("real" if args.real_models else "fake"),
    )

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=args.port,
            log_level="info",
        )
    )
    install_shutdown_handlers(server, stop)
    server_thread = threading.Thread(target=server.run, name="backend-api", daemon=True)
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
