"""Alembic environment for the job-kernel database.

The database location comes from backend.app.core.config, not from
sqlalchemy.url, so migrations always hit the same file the app uses.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from alembic import context

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.db import build_engine, jobs_db_url  # noqa: E402
from backend.app.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-5.5s [%(name)s] %(message)s",
    )

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=jobs_db_url().render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = build_engine()
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
