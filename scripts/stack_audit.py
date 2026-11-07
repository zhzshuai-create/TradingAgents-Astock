"""P6-04b 观察期审计：只读扫 jobs.db 与报告，核对五类异常。

    .venv/Scripts/python.exe scripts/stack_audit.py
    .venv/Scripts/python.exe scripts/stack_audit.py --date 2026-11-07
    .venv/Scripts/python.exe scripts/stack_audit.py --date all --json

口径见 ``docs/upgrade/P6-04b交接卡.md`` 5.2：单执行轮次、model_calls > 0、
content_hash 稳定、无重复 run_started、无自动重跑。数据库用只读 URI 打开，
脚本不写库、不启动进程、不调用模型；异常合计非零时退出码为 1。
审计范围是 ``jobs.created_at`` 的本地日期；``--date all`` 扫全库。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import get_jobs_db_path  # noqa: E402
from backend.app.services.report_document import compute_content_hash  # noqa: E402

CST = timezone(timedelta(hours=8))
TERMINAL_STATUSES = ("succeeded", "failed", "interrupted", "cancelled")
STATUS_ORDER = ("succeeded", "failed", "interrupted", "cancelled")
DEFAULT_EXCLUDED = {
    "e5e0c676-f70f-40c2-81ca-6eec0357af3e": (
        "观察期前第 1 次尝试的工具失败样本（P6-04a，interrupted/lease_expired）"
    ),
}
CHECKS = (
    ("single_round", "单执行轮次"),
    ("model_calls", "model_calls > 0"),
    ("content_hash", "content_hash 稳定"),
    ("no_duplicate_run_started", "无重复 run_started"),
    ("no_auto_rerun", "无自动重跑"),
)
CODE_TO_CHECKS = {
    "created_events": ("single_round",),
    "to_running_count": ("single_round", "no_duplicate_run_started"),
    "stage_started_duplicate": ("single_round", "no_duplicate_run_started"),
    "stage_done_duplicate": ("single_round",),
    "report_ready_duplicate": ("single_round",),
    "event_payload_invalid": ("single_round",),
    "model_calls_missing": ("model_calls",),
    "model_calls_zero": ("model_calls",),
    "report_row_duplicate": ("content_hash",),
    "report_row_missing": ("content_hash",),
    "report_payload_invalid": ("content_hash",),
    "report_hash_mismatch": ("content_hash",),
    "report_id_mismatch": ("content_hash",),
    "report_ready_hash_mismatch": ("content_hash",),
    "run_started_event": ("no_duplicate_run_started",),
    "retry_of_job_id": ("no_auto_rerun",),
    "resume_of_job_id": ("no_auto_rerun",),
    "rerun_after_terminal": ("no_auto_rerun",),
    "idempotency_duplicate": ("no_auto_rerun",),
}


@dataclass(frozen=True)
class Finding:
    code: str
    job_id: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "checks": list(CODE_TO_CHECKS[self.code]),
            "code": self.code,
            "job_id": self.job_id,
            "detail": self.detail,
        }


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"找不到任务库：{path}")
    uri = "file:" + path.resolve().as_posix() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def local_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(CST).date()
    except ValueError:
        return None


def parse_payload(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def audit_job(conn: sqlite3.Connection, job: sqlite3.Row) -> tuple[dict[str, Any], list[Finding]]:
    job_id = job["id"]
    findings: list[Finding] = []
    events = conn.execute(
        "SELECT type, payload FROM job_events WHERE job_id = ? ORDER BY id", (job_id,)
    ).fetchall()

    created = 0
    to_running = 0
    terminal_seen = False
    started: Counter[str] = Counter()
    done: Counter[str] = Counter()
    stats: list[dict[str, Any]] = []
    report_ready: list[dict[str, Any]] = []

    for event in events:
        event_type = event["type"]
        payload = parse_payload(event["payload"])
        if payload is None:
            findings.append(
                Finding("event_payload_invalid", job_id, f"{event_type} 事件的 payload 不是 JSON 对象")
            )
            continue
        if event_type == "created":
            created += 1
        elif event_type == "status_changed":
            target = payload.get("to")
            if target == "running":
                to_running += 1
                if terminal_seen:
                    findings.append(
                        Finding(
                            "rerun_after_terminal",
                            job_id,
                            f"终态之后又出现 to=running（第 {to_running} 次）",
                        )
                    )
            elif target in TERMINAL_STATUSES:
                terminal_seen = True
        elif event_type == "stage_changed":
            stage_id = str(payload.get("stage_id") or "?")
            stage_status = payload.get("stage_status")
            if stage_status == "started":
                started[stage_id] += 1
            elif stage_status == "done":
                done[stage_id] += 1
        elif event_type == "stats":
            stats.append(payload)
        elif event_type == "report_ready":
            report_ready.append(payload)
        elif event_type == "run_started":
            findings.append(
                Finding("run_started_event", job_id, "出现了契约之外的 run_started 事件")
            )

    if created != 1:
        findings.append(Finding("created_events", job_id, f"created 事件应为 1 条，实际 {created}"))
    if to_running > 1:
        findings.append(Finding("to_running_count", job_id, f"to=running 出现 {to_running} 次"))
    elif job["status"] == "succeeded" and to_running != 1:
        findings.append(Finding("to_running_count", job_id, "成功任务应有恰好 1 条 to=running，实际 0"))
    for stage_id, count in sorted(started.items()):
        if count > 1:
            findings.append(
                Finding("stage_started_duplicate", job_id, f"阶段 {stage_id} 出现 {count} 条 started")
            )
    for stage_id, count in sorted(done.items()):
        if count > 1:
            findings.append(
                Finding("stage_done_duplicate", job_id, f"阶段 {stage_id} 出现 {count} 条 done")
            )
    if len(report_ready) > 1:
        findings.append(
            Finding("report_ready_duplicate", job_id, f"report_ready 出现 {len(report_ready)} 条")
        )

    model_calls: int | None = None
    if job["status"] == "succeeded":
        if not stats:
            findings.append(Finding("model_calls_missing", job_id, "成功任务没有 stats 事件"))
        else:
            raw_calls = stats[-1].get("model_calls")
            model_calls = raw_calls if isinstance(raw_calls, int) else None
            if model_calls is None or model_calls <= 0:
                findings.append(
                    Finding("model_calls_zero", job_id, f"最后一条 stats 的 model_calls 为 {raw_calls!r}")
                )
    elif stats:
        raw_calls = stats[-1].get("model_calls")
        model_calls = raw_calls if isinstance(raw_calls, int) else None

    reports = conn.execute(
        "SELECT report_id, content_hash, payload FROM reports WHERE job_id = ?", (job_id,)
    ).fetchall()
    report = reports[0] if reports else None
    if len(reports) > 1:
        findings.append(
            Finding("report_row_duplicate", job_id, f"reports 表有 {len(reports)} 行")
        )
    if job["status"] == "succeeded" and report is None:
        findings.append(Finding("report_row_missing", job_id, "成功任务没有 reports 行"))
    if report is not None:
        document = parse_payload(report["payload"])
        sections = document.get("sections") if document else None
        if not isinstance(sections, dict):
            findings.append(Finding("report_payload_invalid", job_id, "报告 payload 缺少 sections 对象"))
        else:
            recomputed = compute_content_hash(sections)
            if recomputed != report["content_hash"]:
                findings.append(
                    Finding(
                        "report_hash_mismatch",
                        job_id,
                        f"重算 {recomputed[:12]} != 行内 {str(report['content_hash'])[:12]}",
                    )
                )
        if job["report_id"] and job["report_id"] != report["report_id"]:
            findings.append(
                Finding(
                    "report_id_mismatch",
                    job_id,
                    f"jobs.report_id={job['report_id']} != reports.report_id={report['report_id']}",
                )
            )
        if report_ready:
            event_hash = report_ready[-1].get("content_hash")
            if event_hash and event_hash != report["content_hash"]:
                findings.append(
                    Finding(
                        "report_ready_hash_mismatch",
                        job_id,
                        f"report_ready {str(event_hash)[:12]} != 行内 {str(report['content_hash'])[:12]}",
                    )
                )

    if job["retry_of_job_id"]:
        findings.append(
            Finding("retry_of_job_id", job_id, f"retry_of_job_id={job['retry_of_job_id']}")
        )
    if job["resume_of_job_id"]:
        findings.append(
            Finding("resume_of_job_id", job_id, f"resume_of_job_id={job['resume_of_job_id']}")
        )

    seq_values = [
        row["seq"]
        for row in conn.execute("SELECT seq FROM job_events WHERE job_id = ?", (job_id,))
        if row["seq"] is not None
    ]
    summary = {
        "job_id": job_id,
        "ticker_code": job["ticker_code"],
        "analysis_date": job["analysis_date"],
        "status": job["status"],
        "created_at": job["created_at"],
        "finished_at": job["finished_at"],
        "events": len(events),
        "event_seq_max": max(seq_values) if seq_values else 0,
        "to_running": to_running,
        "stages_started": len(started),
        "stages_done": sum(1 for count in done.values() if count),
        "model_calls": model_calls,
        "report_id": report["report_id"] if report is not None else None,
        "content_hash": report["content_hash"] if report is not None else None,
    }
    return summary, findings


def idempotency_findings(conn: sqlite3.Connection) -> list[Finding]:
    rows = conn.execute(
        "SELECT idempotency_key, COUNT(*) AS n, GROUP_CONCAT(id) AS ids "
        "FROM jobs GROUP BY idempotency_key HAVING n > 1"
    ).fetchall()
    return [
        Finding(
            "idempotency_duplicate",
            "",
            f"idempotency_key {row['idempotency_key']} 对应 {row['n']} 个 job：{row['ids']}",
        )
        for row in rows
    ]


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).expanduser() if args.db else get_jobs_db_path()
    conn = connect_readonly(db_path)
    try:
        jobs = conn.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
        excluded: dict[str, str] = dict(DEFAULT_EXCLUDED)
        for raw in args.exclude:
            for token in raw.split(","):
                token = token.strip()
                if token:
                    excluded[token] = "命令行 --exclude"

        target: date | None = None
        if args.date != "all":
            target = date.fromisoformat(args.date) if args.date else datetime.now(CST).date()

        in_scope: list[sqlite3.Row] = []
        unparsed: list[Finding] = []
        for job in jobs:
            if target is None:
                in_scope.append(job)
                continue
            created = local_date(job["created_at"])
            if created is None:
                unparsed.append(
                    Finding("created_events", job["id"], f"created_at 不可解析：{job['created_at']!r}")
                )
            elif created == target:
                in_scope.append(job)

        audited: list[sqlite3.Row] = []
        excluded_rows: list[dict[str, str]] = []
        for job in in_scope:
            if job["id"] in excluded:
                excluded_rows.append({"job_id": job["id"], "reason": excluded[job["id"]]})
            else:
                audited.append(job)

        findings: list[Finding] = list(unparsed)
        summaries = []
        for job in audited:
            summary, job_findings = audit_job(conn, job)
            summaries.append(summary)
            findings.extend(job_findings)
        findings.extend(idempotency_findings(conn))
    finally:
        conn.close()

    by_status = Counter(job["status"] for job in in_scope)
    per_check = {key: [] for key, _label in CHECKS}
    for finding in findings:
        for key in CODE_TO_CHECKS[finding.code]:
            per_check[key].append(finding)

    scope_label = "全库" if target is None else target.isoformat()
    return {
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "db": str(db_path),
        "read_only": True,
        "scope": {
            "mode": "all" if target is None else "date",
            "date": scope_label,
            "jobs_total": len(in_scope),
            "by_status": {status: by_status.get(status, 0) for status in STATUS_ORDER},
            "audited": len(audited),
            "excluded": excluded_rows,
            "unparsed_jobs": len(unparsed),
        },
        "checks": [
            {
                "check": key,
                "label": label,
                "status": "pass" if not per_check[key] else "fail",
                "findings": len(per_check[key]),
            }
            for key, label in CHECKS
        ],
        "summary": {
            "anomalies": len(findings),
            "report_hash_stable": not per_check["content_hash"],
            "no_auto_rerun": not per_check["no_auto_rerun"],
            "single_round": not per_check["single_round"],
            "model_calls_positive": not per_check["model_calls"],
            "no_duplicate_run_started": not per_check["no_duplicate_run_started"],
        },
        "anomalies": [finding.as_dict() for finding in findings],
        "jobs": summaries,
    }


def print_report(report: dict[str, Any]) -> None:
    scope = report["scope"]
    counts = scope["by_status"]
    print("P6-04b 观察期审计")
    print(f"数据库: {report['db']}（只读）")
    print(
        f"范围: {scope['date']}；任务 {scope['jobs_total']} 个"
        f"（成功 {counts['succeeded']} / 失败 {counts['failed']} / 中断 {counts['interrupted']}"
        f" / 取消 {counts['cancelled']}）；审计 {scope['audited']} 个，排除 {len(scope['excluded'])} 个"
    )
    for item in scope["excluded"]:
        print(f"  排除 {item['job_id']}: {item['reason']}")
    for check in report["checks"]:
        mark = "PASS" if check["status"] == "pass" else "FAIL"
        print(f"[{mark}] {check['label']}（{check['findings']} 条）")
    for anomaly in report["anomalies"]:
        who = anomaly["job_id"] or "-"
        print(f"  - [{anomaly['code']}] {who}: {anomaly['detail']}")
    print(f"异常合计: {report['summary']['anomalies']}")
    print("任务明细:")
    for job in report["jobs"]:
        print(
            f"  {job['job_id']} {job['status']} {job['ticker_code']}/{job['analysis_date']}"
            f" events={job['events']}(seq≤{job['event_seq_max']})"
            f" 阶段={job['stages_done']}/{job['stages_started']}"
            f" to_running={job['to_running']} model_calls={job['model_calls']}"
            f" hash={str(job['content_hash'])[:12] if job['content_hash'] else '-'}"
        )
    if not report["jobs"]:
        print("  （范围内没有可审计任务）")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P6-04b 只读观察审计")
    parser.add_argument(
        "--date",
        default=None,
        help="审计 created_at 的本地日期（YYYY-MM-DD）；缺省今天；all 表示全库",
    )
    parser.add_argument("--db", default=None, help="任务库路径；缺省 TA_JOBS_DB 或 ~/.tradingagents/jobs.db")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="显式排除的 job id，可重复或逗号分隔；默认已排除 P6-04a 第 1 次尝试",
    )
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    try:
        report = build_report(args)
    except (FileNotFoundError, sqlite3.Error) as exc:
        print(f"审计失败：{exc}")
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 1 if report["summary"]["anomalies"] else 0


if __name__ == "__main__":
    sys.exit(main())
