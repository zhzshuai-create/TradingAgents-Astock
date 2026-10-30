"""Stage report files: one directory per job and stage, attempts never overwrite.

The database stores a path relative to the store root, so the root can move
without rewriting rows. Every write opens a new ``attempt-<n>.md`` with
exclusive create: a retry after a crash adds evidence instead of clobbering
the previous attempt (ST-01).

The final report is a separate ``<job>/report.json`` written just before the
terminal transaction (P1-10). If the process dies between that write and the
commit, the file is B4 evidence: reconciliation never registers it, it only
records an ``unregistered_report`` note. The write goes through a temp file and
``os.replace`` so a crash mid-write never leaves a complete-looking document.

The root is ``TA_JOB_REPORTS_DIR``, defaulting to
``~/.tradingagents/job_reports``. That is deliberately not the legacy
``~/.tradingagents/logs`` directory, which the old Streamlit runner owns.

Contract api-v1.md 1.10: a read keeps the first 128 KiB of UTF-8 and reports
``full_length`` as the original character count.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

JOB_REPORTS_ENV = "TA_JOB_REPORTS_DIR"
MAX_STAGE_REPORT_BYTES = 128 * 1024
FINAL_REPORT_NAME = "report.json"
_CST = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class StageReport:
    markdown: str
    truncated: bool
    full_length: int
    updated_at: str


class ReportStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).expanduser()

    @property
    def root(self) -> Path:
        return self._root

    @classmethod
    def from_env(cls, *, environ: Mapping[str, str] | None = None) -> "ReportStore":
        env = os.environ if environ is None else environ
        override = env.get(JOB_REPORTS_ENV)
        if override:
            return cls(Path(override).expanduser())
        return cls(Path.home() / ".tradingagents" / "job_reports")

    def write_stage_report(self, job_id: str, stage_id: str, text: str) -> str:
        """Write one attempt and return its path relative to the root."""
        directory = self._root / _component(job_id) / _component(stage_id)
        directory.mkdir(parents=True, exist_ok=True)
        attempt = 1
        while True:
            path = directory / f"attempt-{attempt}.md"
            try:
                with path.open("x", encoding="utf-8", newline="") as handle:
                    handle.write(text)
            except FileExistsError:
                attempt += 1
                continue
            return path.relative_to(self._root).as_posix()

    def stage_report_paths(self, job_id: str) -> dict[str, str]:
        """Latest attempt per stage present on disk, keyed by stage id."""
        directory = self._root / _component(job_id)
        if not directory.is_dir():
            return {}
        latest: dict[str, tuple[int, Path]] = {}
        for stage_dir in directory.iterdir():
            if not stage_dir.is_dir():
                continue
            for path in stage_dir.glob("attempt-*.md"):
                try:
                    attempt = int(path.stem.removeprefix("attempt-"))
                except ValueError:
                    continue
                current = latest.get(stage_dir.name)
                if current is None or attempt > current[0]:
                    latest[stage_dir.name] = (attempt, path)
        return {
            stage_id: path.relative_to(self._root).as_posix()
            for stage_id, (_attempt, path) in latest.items()
        }

    def write_final_report(self, job_id: str, payload: Mapping[str, Any]) -> str:
        """Write the pre-commit report artifact and return its relative path."""
        directory = self._root / _component(job_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / FINAL_REPORT_NAME
        temp = directory / f"{FINAL_REPORT_NAME}.tmp"
        temp.write_text(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            encoding="utf-8",
            newline="",
        )
        os.replace(temp, target)
        return target.relative_to(self._root).as_posix()

    def read_final_report(self, job_id: str) -> dict[str, Any] | None:
        """Return the artifact only when it is a complete report document."""
        path = self._root / _component(job_id) / FINAL_REPORT_NAME
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        meta = data.get("meta")
        sections = data.get("sections")
        if not isinstance(meta, dict) or not isinstance(sections, dict):
            return None
        if not sections:
            return None
        return data

    def read_stage_report(self, relative_path: str) -> StageReport | None:
        path = self._resolve(relative_path)
        if not path.is_file():
            return None
        data = path.read_bytes()
        raw_text = data.decode("utf-8", errors="replace")
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, _CST).isoformat(
            timespec="seconds"
        )
        truncated = len(data) > MAX_STAGE_REPORT_BYTES
        text = (
            data[:MAX_STAGE_REPORT_BYTES].decode("utf-8", errors="ignore")
            if truncated
            else raw_text
        )
        return StageReport(
            markdown=text,
            truncated=truncated,
            full_length=len(raw_text),
            updated_at=updated_at,
        )

    def _resolve(self, relative_path: str) -> Path:
        if not relative_path:
            raise ValueError("empty stage report path")
        root = self._root.resolve()
        candidate = (self._root / relative_path).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("stage report path escapes the store root")
        return candidate


def _component(value: str) -> str:
    if not value or value in {".", ".."} or any(
        separator in value for separator in ("/", "\\", ":", "\x00")
    ):
        raise ValueError(f"invalid report path component: {value!r}")
    return value
