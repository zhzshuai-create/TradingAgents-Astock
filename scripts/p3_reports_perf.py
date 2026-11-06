"""P3-01 performance probe: report list and detail p95 on a 10k-row database.

Every run builds a throwaway SQLite database under the system temp directory
and fills it with 10,000 synthetic reports derived from
``tests/fixtures/upgrade/final_state_v1.json``. Nothing touches
``~/.tradingagents`` and nothing is committed except the JSON result.

    .venv/Scripts/python.exe scripts/p3_reports_perf.py \
        --reports 10000 --samples 30 \
        --out docs/upgrade/reviews/2026-11-06_P3-01性能结果.json

p95 is nearest-rank over the measured samples (3 warmups are discarded).
Hard line: both p95 values must be <= 500 ms.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import insert  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Report  # noqa: E402
from backend.app.services.job_service import JobService  # noqa: E402
from backend.app.services.report_document import compute_content_hash  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "upgrade" / "final_state_v1.json"
CST = timezone(timedelta(hours=8))
BASE_TIME = datetime(2026, 10, 24, 15, 30, tzinfo=CST)
REPORT_ID = "00000000-0000-4000-8000-{index:012d}"
HARD_LINE_MS = 500
INSERT_BATCH = 500


def _report_id(index: int) -> str:
    return REPORT_ID.format(index=index)


def _rows(count: int) -> list[dict]:
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sections = golden["sections"]
    content_hash = compute_content_hash(sections)
    rows = []
    for index in range(count):
        report_id = _report_id(index)
        meta = dict(golden["meta"])
        generated_at = (BASE_TIME - timedelta(seconds=index)).isoformat(
            timespec="seconds"
        )
        meta.update(
            {
                "report_id": report_id,
                "job_id": None,
                "ticker_code": "000629",
                "ticker_name": None,
                "analysis_date": "2026-10-24",
                "generated_at": generated_at,
                "generated_at_source": "job_clock",
                "origin": "new",
                "content_hash": content_hash,
                "rating": "Hold",
                "signal": "Hold",
            }
        )
        rows.append(
            {
                "report_id": report_id,
                "job_id": None,
                "ticker_code": "000629",
                "ticker_name": None,
                "analysis_date": "2026-10-24",
                "generated_at": generated_at,
                "generated_at_source": "job_clock",
                "origin": "new",
                "schema_version": "report-v1",
                "content_hash": content_hash,
                "config_digest": None,
                "data_quality_status": "ok",
                "chart_snapshot_status": "frozen",
                "retry_of_job_id": None,
                "rating": "Hold",
                "signal": "Hold",
                "payload": {"meta": meta, "sections": sections},
                "created_at": generated_at,
            }
        )
    return rows


def _nearest_rank_p95(values: list[float]) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[rank - 1]


def _measure(
    client: TestClient, url: str, *, warmups: int, samples: int
) -> list[float]:
    for _ in range(warmups):
        response = client.get(url)
        assert response.status_code == 200, response.text
    times = []
    for _ in range(samples):
        started = time.perf_counter()
        response = client.get(url)
        times.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200, response.text
    return times


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=int, default=10_000)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    if args.samples < 30:
        parser.error("--samples must be at least 30")

    with tempfile.TemporaryDirectory(prefix="p3_perf_") as tmp:
        temp = Path(tmp)
        os.environ["TA_JOBS_DB"] = str(temp / "jobs" / "jobs.db")
        os.environ["TA_JOB_REPORTS_DIR"] = str(temp / "reports")
        os.environ["TA_EXPORTS_DIR"] = str(temp / "exports")
        os.environ["HOME"] = str(temp / "home")
        os.environ["USERPROFILE"] = str(temp / "home")

        cfg = Config(str(ROOT / "backend" / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
        command.upgrade(cfg, "head")

        from backend.app.core.db import build_engine

        engine = build_engine()
        rows = _rows(args.reports)
        started = time.perf_counter()
        with Session(engine) as session:
            for offset in range(0, len(rows), INSERT_BATCH):
                session.execute(insert(Report), rows[offset : offset + INSERT_BATCH])
            session.commit()
        insert_seconds = time.perf_counter() - started

        reports = ReportStore(temp / "reports")
        config = ServerConfig()
        service = JobService(engine, config)
        client = TestClient(
            create_app(service=service, server_config=config, report_store=reports)
        )
        try:
            list_url = (
                "/api/v1/reports?ticker=000629"
                "&date_from=2026-09-01&date_to=2026-10-29&limit=50"
            )
            list_times = _measure(
                client, list_url, warmups=args.warmups, samples=args.samples
            )
            detail_times = _measure(
                client,
                f"/api/v1/reports/{_report_id(0)}",
                warmups=args.warmups,
                samples=args.samples,
            )
        finally:
            client.close()
            engine.dispose()

    result = {
        "ticket": "P3-01",
        "measured_at": datetime.now(CST).isoformat(timespec="seconds"),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
        },
        "dataset": {
            "reports": args.reports,
            "payload_source": "tests/fixtures/upgrade/final_state_v1.json",
            "list_page_size": 50,
            "insert_seconds": round(insert_seconds, 3),
        },
        "samples": {"warmups": args.warmups, "measured": args.samples},
        "list_filtered": {
            "median_ms": round(statistics.median(list_times), 2),
            "p95_ms": round(_nearest_rank_p95(list_times), 2),
        },
        "detail": {
            "median_ms": round(statistics.median(detail_times), 2),
            "p95_ms": round(_nearest_rank_p95(detail_times), 2),
        },
        "hard_line_ms": HARD_LINE_MS,
        "conclusion": (
            "pass"
            if _nearest_rank_p95(list_times) <= HARD_LINE_MS
            and _nearest_rank_p95(detail_times) <= HARD_LINE_MS
            else "fail"
        ),
        "command": (
            ".venv/Scripts/python.exe scripts/p3_reports_perf.py "
            f"--reports {args.reports} --samples {args.samples}"
        ),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["conclusion"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
