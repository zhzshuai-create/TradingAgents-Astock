"""SQLite engine factory for the job kernel.

Every connection is opened through this factory so the PRAGMAs that matter for
task correctness (foreign keys, WAL, busy wait) are set before any query runs.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL

from backend.app.core.config import get_jobs_db_path

BUSY_TIMEOUT_MS = 5000


def jobs_db_url(db_path: Path | None = None) -> URL:
    path = get_jobs_db_path() if db_path is None else Path(db_path)
    return URL.create("sqlite+pysqlite", database=str(path))


def build_engine(db_path: Path | None = None, *, echo: bool = False) -> Engine:
    path = get_jobs_db_path() if db_path is None else Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(jobs_db_url(path), echo=echo)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine
