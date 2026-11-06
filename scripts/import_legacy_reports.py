"""Import legacy ``full_states_log_*.json`` files into the report store.

Dry run is the default: it reads the ledger through a read-only SQLite
connection, prints what would be imported or skipped, and never creates the
database, a WAL file or the reports directory. Writing requires ``--apply``,
which upgrades the configured database to head and imports.

    .venv/Scripts/python.exe scripts/import_legacy_reports.py --root ~/.tradingagents/logs
    .venv/Scripts/python.exe scripts/import_legacy_reports.py --root ~/.tradingagents/logs --apply

``TA_JOBS_DB`` overrides the database path (default ``~/.tradingagents/jobs.db``).
One JSON document is printed with ``--json``; the exit code is 0 in both modes.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from backend.app.core.config import get_jobs_db_path  # noqa: E402
from backend.app.services.legacy_import_service import run_import  # noqa: E402

DEFAULT_ROOT = Path.home() / ".tradingagents" / "logs"


def _read_ledger(db_path: Path) -> set[tuple[str, str]]:
    """Read ``(source_path, content_hash)`` without creating or writing a file."""
    if not db_path.exists():
        return set()
    try:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return set()
    try:
        rows = connection.execute(
            "SELECT source_path, content_hash FROM legacy_imports"
        ).fetchall()
    except sqlite3.OperationalError:
        # Database exists but predates 0006; every file is a candidate.
        return set()
    finally:
        connection.close()
    return {(str(source), str(digest)) for source, digest in rows}


def _upgrade_and_import(root: Path):
    from backend.app.core.db import build_engine

    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    command.upgrade(config, "head")
    engine = build_engine()
    try:
        return run_import(root, apply=True, engine=engine)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--apply", action="store_true", help="write reports (default: dry run)"
    )
    parser.add_argument("--json", action="store_true", help="print one JSON document")
    args = parser.parse_args(argv)

    root = args.root.expanduser()
    if args.apply:
        summary = _upgrade_and_import(root)
    else:
        summary = run_import(
            root, apply=False, ledger=_read_ledger(get_jobs_db_path())
        )

    payload = {
        "mode": summary.mode,
        "root": str(root),
        "database": str(get_jobs_db_path()),
        "counts": summary.counts(),
        "entries": [asdict(entry) for entry in summary.entries],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"{summary.mode}: root={root} database={payload['database']}")
    for entry in summary.entries:
        detail = entry.reason or entry.report_id or ""
        print(f"  [{entry.status}] {entry.source_path} {detail}".rstrip())
    counts = payload["counts"]
    print(
        f"imported={counts['imported']} would_import={counts['would_import']} "
        f"skipped={counts['skipped']} invalid={counts['invalid']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
