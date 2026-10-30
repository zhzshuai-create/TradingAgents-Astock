"""Finalize an executor's ReportDTO into the immutable report row payload.

report-schema-v1 makes the server the authority for job-owned metadata and for
``content_hash``: the hash is computed over ``sections`` canonically serialized
(section 2), and ``signal`` is derived from ``rating`` (section 5). Executor
input is therefore copied, never mutated, and its meta values for these fields
are replaced. ``report_id`` is kept when the executor supplied one (each run
supplies a new id) and generated otherwise, so the id is always unique per job.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "report-v1"
RATING_TO_SIGNAL = {
    "Buy": "Buy",
    "Overweight": "Buy",
    "Hold": "Hold",
    "Underweight": "Sell",
    "Sell": "Sell",
    "unknown": "unknown",
}
DATA_QUALITY_STATUSES = ("ok", "degraded", "absent")
CHART_SNAPSHOT_STATUSES = ("frozen", "refetch_needed", "none")


def canonical_sections(sections: Mapping[str, Any]) -> str:
    return json.dumps(
        sections, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def compute_content_hash(sections: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_sections(sections).encode("utf-8")).hexdigest()


def finalize_report(
    report: Mapping[str, Any],
    *,
    job_id: str,
    ticker_code: str,
    ticker_name: str | None,
    analysis_date: str,
    generated_at: str,
    config_digest: str | None,
    retry_of_job_id: str | None,
) -> dict[str, Any]:
    payload = copy.deepcopy(dict(report))
    sections = payload.get("sections")
    if not isinstance(sections, Mapping):
        raise ValueError("report has no sections mapping")
    meta = payload.setdefault("meta", {})
    meta["report_id"] = meta.get("report_id") or str(uuid.uuid4())
    meta["job_id"] = job_id
    meta["ticker_code"] = ticker_code
    meta["ticker_name"] = ticker_name
    meta["analysis_date"] = analysis_date
    meta["generated_at"] = generated_at
    meta["generated_at_source"] = "job_clock"
    meta["origin"] = "new"
    meta["schema_version"] = SCHEMA_VERSION
    meta["config_digest"] = config_digest
    meta["retry_of_job_id"] = retry_of_job_id
    meta["rating"] = meta.get("rating") if meta.get("rating") in RATING_TO_SIGNAL else "unknown"
    meta["signal"] = RATING_TO_SIGNAL[meta["rating"]]
    meta["data_quality_status"] = (
        meta.get("data_quality_status")
        if meta.get("data_quality_status") in DATA_QUALITY_STATUSES
        else "absent"
    )
    meta["chart_snapshot_status"] = (
        meta.get("chart_snapshot_status")
        if meta.get("chart_snapshot_status") in CHART_SNAPSHOT_STATUSES
        else "none"
    )
    meta["content_hash"] = compute_content_hash(sections)
    return payload


def report_ready_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    meta = payload["meta"]
    return {
        "report_id": meta["report_id"],
        "content_hash": meta["content_hash"],
        "rating": meta["rating"],
        "signal": meta["signal"],
        "url": f"/api/v1/reports/{meta['report_id']}",
    }
