"""Which UI may create analysis jobs (api-v1.md 1.8, error-codes-v1.md).

The value is read once at process start. There is deliberately no hot switch:
two UIs holding the write lock at the same time would race on the same reports.
"""

from __future__ import annotations

WRITE_MODE_ENV = "ACTIVE_ANALYSIS_UI"
WRITE_MODES = ("legacy", "next")
DEFAULT_WRITE_MODE = "legacy"


def parse_write_mode(raw: str | None) -> str:
    if raw is None:
        return DEFAULT_WRITE_MODE
    value = raw.strip().lower()
    if value not in WRITE_MODES:
        raise ValueError(
            f"{WRITE_MODE_ENV} must be one of {WRITE_MODES}, got {raw!r}"
        )
    return value
