"""Import legacy ``full_states_log_*.json`` files into ``reports`` (P3-02).

Path layout and identity mirror ``web/history.py``: every
``<root>/<ticker>/TradingAgentsStrategy_logs/full_states_log_<YYYY-MM-DD>.json``
belongs to ``<ticker>`` on the date in its file name. The path wins over the
JSON's ``company_of_interest`` / ``trade_date`` so a copied or renamed file
cannot silently change identity.

Idempotency lives in ``legacy_imports`` keyed by ``(source_path,
content_hash)``: the same file and same sections add nothing, changed sections
add one report and one ledger row. A concurrent import loses the primary-key
race and is reported as skipped. Legacy imports never create jobs, events or
generated timestamps: ``generated_at`` stays null, the mtime is never read.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.legacy_import import LegacyImport
from backend.app.models.report import Report
from backend.app.services.report_document import SCHEMA_VERSION
from backend.app.services.report_schema import build_legacy_report

CST = timezone(timedelta(hours=8))
FILE_RE = re.compile(r"^full_states_log_(\d{4}-\d{2}-\d{2})\.json$")
TICKER_RE = re.compile(r"^[0-9]{6}$")

IMPORTED = "imported"
WOULD_IMPORT = "would_import"
SKIPPED = "skipped"
INVALID = "invalid"


@dataclass(frozen=True)
class LegacyFile:
    path: Path
    ticker: str
    analysis_date: str


@dataclass(frozen=True)
class ImportEntry:
    source_path: str
    status: str
    ticker: str | None = None
    analysis_date: str | None = None
    report_id: str | None = None
    content_hash: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ImportSummary:
    mode: str
    entries: tuple[ImportEntry, ...]

    def counts(self) -> dict[str, int]:
        counts = {IMPORTED: 0, WOULD_IMPORT: 0, SKIPPED: 0, INVALID: 0}
        for entry in self.entries:
            counts[entry.status] = counts.get(entry.status, 0) + 1
        return counts


def scan_legacy_files(root: Path | str) -> list[LegacyFile]:
    """Every file matching the legacy layout, in a stable path order."""
    base = Path(root).expanduser()
    if not base.is_dir():
        return []
    base = base.resolve()
    files = []
    for path in base.rglob("full_states_log_*.json"):
        if not path.is_file():
            continue
        match = FILE_RE.match(path.name)
        if match is None:
            continue
        files.append(
            LegacyFile(
                path=path,
                ticker=path.parent.parent.name,
                analysis_date=match.group(1),
            )
        )
    return sorted(files, key=lambda item: str(item.path))


def run_import(
    root: Path | str,
    *,
    apply: bool,
    engine: Engine | None = None,
    ledger: set[tuple[str, str]] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ImportSummary:
    """Classify every legacy file; write only when ``apply`` is true.

    ``ledger`` supplies ``(source_path, content_hash)`` pairs for a dry run so
    it can say what would be skipped without opening (or creating) the
    database. An apply run reads the same pairs from ``legacy_imports`` in the
    same transaction as the inserts.
    """
    if apply and engine is None:
        raise ValueError("apply mode needs an engine")
    now = (clock or (lambda: datetime.now(CST)))()
    known = ledger or set()
    entries = []
    for file in scan_legacy_files(root):
        source_path = str(file.path)
        dto, reason = _load_dto(file)
        if dto is None:
            entries.append(
                ImportEntry(
                    source_path=source_path,
                    status=INVALID,
                    ticker=file.ticker,
                    analysis_date=file.analysis_date,
                    reason=reason,
                )
            )
            continue
        content_hash = dto["meta"]["content_hash"]
        if apply:
            entry = _insert(engine, source_path, content_hash, dto, now)
        else:
            status = SKIPPED if (source_path, content_hash) in known else WOULD_IMPORT
            entry = ImportEntry(
                source_path=source_path,
                status=status,
                ticker=file.ticker,
                analysis_date=file.analysis_date,
                content_hash=content_hash,
                reason="already_imported" if status == SKIPPED else None,
            )
        entries.append(entry)
    return ImportSummary(mode="apply" if apply else "dry-run", entries=tuple(entries))


def _load_dto(file: LegacyFile) -> tuple[dict[str, Any] | None, str | None]:
    if not TICKER_RE.match(file.ticker):
        return None, "invalid_ticker"
    try:
        date.fromisoformat(file.analysis_date)
    except ValueError:
        return None, "invalid_date"
    try:
        data = json.loads(file.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "unreadable_json"
    if not isinstance(data, dict):
        return None, "not_an_object"

    dto = build_legacy_report(data)
    dto["meta"]["ticker_code"] = file.ticker
    dto["meta"]["analysis_date"] = file.analysis_date
    if not dto["sections"]:
        return None, "empty_report"
    return dto, None


def _insert(
    engine: Engine,
    source_path: str,
    content_hash: str,
    dto: dict[str, Any],
    now: datetime,
) -> ImportEntry:
    imported_at = now.isoformat(timespec="seconds")
    meta = dto["meta"]
    with Session(engine) as session:
        existing = session.get(LegacyImport, (source_path, content_hash))
        if existing is not None:
            return ImportEntry(
                source_path=source_path,
                status=SKIPPED,
                ticker=meta["ticker_code"],
                analysis_date=meta["analysis_date"],
                report_id=existing.report_id,
                content_hash=content_hash,
                reason="already_imported",
            )
        report_id = meta["report_id"]
        try:
            # The ledger row carries a foreign key to the report; without a
            # relationship SQLAlchemy inserts in mapper order, so flush the
            # parent explicitly.
            session.add(
                Report(
                    report_id=report_id,
                    job_id=None,
                    ticker_code=meta["ticker_code"],
                    ticker_name=meta.get("ticker_name"),
                    analysis_date=meta["analysis_date"],
                    generated_at=None,
                    generated_at_source="unknown",
                    origin="legacy_import",
                    schema_version=SCHEMA_VERSION,
                    content_hash=content_hash,
                    config_digest=None,
                    data_quality_status="absent",
                    chart_snapshot_status="none",
                    retry_of_job_id=None,
                    rating=meta["rating"],
                    signal=meta["signal"],
                    payload=dto,
                    created_at=imported_at,
                )
            )
            session.flush()
            session.add(
                LegacyImport(
                    source_path=source_path,
                    content_hash=content_hash,
                    report_id=report_id,
                    imported_at=imported_at,
                )
            )
            session.commit()
        except IntegrityError:
            # A concurrent importer won the primary key; the report insert in
            # this transaction is rolled back with it.
            session.rollback()
            return ImportEntry(
                source_path=source_path,
                status=SKIPPED,
                ticker=meta["ticker_code"],
                analysis_date=meta["analysis_date"],
                content_hash=content_hash,
                reason="duplicate",
            )
    return ImportEntry(
        source_path=source_path,
        status=IMPORTED,
        ticker=meta["ticker_code"],
        analysis_date=meta["analysis_date"],
        report_id=report_id,
        content_hash=content_hash,
    )
