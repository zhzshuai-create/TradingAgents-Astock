"""Contract tests for the deterministic fake analysis graph (P0 Day 6).

Each test carries one stable GF id. ``test-matrix.md`` must reference exactly
the same set, and ``test_gf26_matrix_covers_every_test`` enforces it.
"""

from __future__ import annotations

import ast
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

import fake_analysis_graph as fake
from fake_analysis_graph import (
    ALLOWED_ACTIONS,
    FakeAnalysisGraph,
    FakeJobLedger,
    FakeJobRunner,
    IllegalTransition,
    SCENARIOS,
    compute_content_hash,
    load_golden_report,
    run_scenario,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "docs" / "upgrade" / "contracts"
FAKE_DOCS = ROOT / "docs" / "upgrade" / "fake-graph"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _transitions(outcome: fake.RunOutcome) -> list[tuple[str, str]]:
    return [
        (event["payload"]["from"], event["payload"]["to"])
        for event in outcome.events
        if event["type"] == "status_changed"
    ]


def _done_stages(outcome: fake.RunOutcome) -> list[str]:
    return [
        stage["id"] for stage in outcome.job["stages"] if stage["status"] == "done"
    ]


def test_gf01_stage_catalog_matches_contract() -> None:
    """GF-01: 假图 12 阶段与 web.progress、api-v1 表逐项一致。"""
    from web.progress import PIPELINE_STAGES

    assert [stage["id"] for stage in PIPELINE_STAGES] == list(fake.STAGE_IDS)
    assert [stage["name"] for stage in PIPELINE_STAGES] == [
        spec.name for spec in fake.STAGES
    ]
    api = _read(CONTRACTS / "api-v1.md")
    for index, spec in enumerate(fake.STAGES, 1):
        assert f"| {index} | {spec.id} | {spec.name} |" in api


def test_gf02_golden_report_matches_fixture_and_schema() -> None:
    """GF-02: 正常跑完生成的 ReportDTO 与黄金样本逐字段相等并通过 schema。"""
    outcome = run_scenario("S00")
    golden = load_golden_report()
    schema = json.loads(_read(CONTRACTS / "report-schema-v1.json"))

    assert outcome.report == golden
    jsonschema.validate(outcome.report, schema)
    assert outcome.report["meta"]["content_hash"] == compute_content_hash(
        outcome.report["sections"]
    )
    assert outcome.job["report_id"] == golden["meta"]["report_id"]
    assert outcome.job["links"]["report"].endswith(golden["meta"]["report_id"])


def test_gf03_happy_path_event_order_and_counts() -> None:
    """GF-03: 正常路径 40 条事件、seq 连续、终态顺序固定。"""
    outcome = run_scenario("S00")
    events = outcome.events

    assert [event["seq"] for event in events] == list(range(1, 41))
    assert len(events) == 40
    types = [event["type"] for event in events]
    assert types.count("stage_changed") == 24
    assert types.count("stats") == 13
    assert types[-3:] == ["stats", "status_changed", "report_ready"]

    stage_events = [e for e in events if e["type"] == "stage_changed"]
    assert [e["payload"]["stage_id"] for e in stage_events[::2]] == list(
        fake.STAGE_IDS
    )
    assert all(e["payload"]["stage_status"] == "started" for e in stage_events[::2])
    assert all(e["payload"]["stage_status"] == "done" for e in stage_events[1::2])
    assert all(
        e["payload"]["index"] == (i // 2) + 1 for i, e in enumerate(stage_events)
    )
    assert all(e["payload"]["total"] == 12 for e in stage_events)

    assert outcome.job["stats"] == {
        "model_calls": 14,
        "tokens_in": 182430,
        "tokens_out": 41208,
        "elapsed_ms": 21600000,
    }
    assert outcome.job["allowed_actions"] == ["retry", "reanalyze"]
    assert _done_stages(outcome) == list(fake.STAGE_IDS)


def test_gf04_repeated_runs_are_identical() -> None:
    """GF-04: 相同输入两次运行，事件、报告、任务详情逐字节一致。"""
    first = run_scenario("S00")
    second = run_scenario("S00")

    assert first.events == second.events
    assert first.report == second.report
    assert first.job == second.job
    assert first.audit == second.audit
    assert first.meta == second.meta


def test_gf05_no_network_model_or_real_report_dir(monkeypatch) -> None:
    """GF-05: 禁止网络、模型、真实报告目录、随机与睡眠。"""
    def _blocked(*args, **kwargs):
        raise AssertionError("network access is forbidden in the fake graph")

    monkeypatch.setattr(socket, "socket", _blocked)
    outcome = run_scenario("S00")
    assert outcome.job["status"] == "succeeded"

    source_path = Path(fake.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    banned = {
        "tradingagents",
        "web",
        "requests",
        "urllib",
        "http",
        "socket",
        "random",
        "time",
        "os",
    }
    assert not modules & banned, modules & banned
    for needle in (
        "write_text(",
        "write_bytes(",
        "open(",
        "expanduser(",
        "Path.home(",
        "os.environ",
        "time.sleep",
        "random.",
    ):
        assert needle not in source, needle


def test_gf06_fake_stream_drives_real_progress_tracker() -> None:
    """GF-06: 假图流可直接驱动产品 ProgressTracker 的阶段识别。"""
    from web.progress import ProgressTracker, STAGE_IDS as REAL_STAGE_IDS
    from web.runner import _detect_completed_stages, _infer_active_stage

    graph = FakeAnalysisGraph()
    tracker = ProgressTracker(ticker="000629", trade_date="2026-10-24")
    tracker.is_running = True
    init_state, args, _ = graph.prepare_graph_run("000629", "2026-10-24")
    for chunk in graph.stream(init_state, **args):
        _detect_completed_stages(chunk, tracker)
        _infer_active_stage(tracker)

    assert tracker.completed_stages == list(REAL_STAGE_IDS)
    assert set(tracker.stage_reports) == set(REAL_STAGE_IDS)
    assert tracker.stage_status("pm") == "done"
    assert tracker.stage_status("market") == "done"


def test_gf07_create_then_cancel_queued() -> None:
    """GF-07: T19 排队取消，不经过 running，不产生模型调用。"""
    outcome = run_scenario("S01")

    assert outcome.job["status"] == "cancelled"
    assert [event["type"] for event in outcome.events] == ["stats", "status_changed"]
    assert outcome.events[1]["payload"]["from"] == "queued"
    assert outcome.events[1]["payload"]["detail"] == "cancel"
    assert outcome.job["stats"]["model_calls"] == 0
    assert outcome.job["created_at"] == outcome.job["finished_at"]
    assert outcome.job["allowed_actions"] == ["reanalyze"]
    assert outcome.report is None
    assert not any(e["type"] == "stage_changed" for e in outcome.events)


def test_gf08_pause_then_resume() -> None:
    """GF-08: T05/T06/T09，暂停落在阶段边界，继续后跑完 12 阶段。"""
    outcome = run_scenario("S02")

    assert outcome.job["status"] == "succeeded"
    assert outcome.meta["paused_after_stages"] == 3
    assert _transitions(outcome) == [
        ("queued", "running"),
        ("running", "pause_requested"),
        ("pause_requested", "paused"),
        ("paused", "running"),
        ("running", "succeeded"),
    ]
    assert outcome.job["stats"]["model_calls"] == 14
    assert _done_stages(outcome) == list(fake.STAGE_IDS)
    assert len(outcome.events) == 43


def test_gf09_pause_then_cancel_uses_t20() -> None:
    """GF-09: 暂停后取消走 T20 → cancel_requested → T13 cancelled。"""
    outcome = run_scenario("S03")

    assert outcome.job["status"] == "cancelled"
    assert outcome.meta["paused_after_stages"] == 3
    assert _transitions(outcome)[-2:] == [
        ("paused", "cancel_requested"),
        ("cancel_requested", "cancelled"),
    ]
    assert outcome.job["stats"]["model_calls"] == 3
    assert len(_done_stages(outcome)) == 3
    assert outcome.report is None
    assert outcome.job["pending_action"] is None


def test_gf10_fail_after_stage_completes() -> None:
    """GF-10: 阶段完成后抛异常 → T04 failed，已完成阶段保留。"""
    outcome = run_scenario("S04")

    assert outcome.job["status"] == "failed"
    assert outcome.job["error"] == {
        "code": "internal_error",
        "message": "分析执行失败",
    }
    assert _done_stages(outcome) == ["market", "social", "news"]
    assert not [s for s in outcome.job["stages"] if s["status"] == "failed"]
    assert outcome.events[-1]["payload"]["detail"] == "post_stage_error"
    assert outcome.job["stats"]["model_calls"] == 3
    assert outcome.job["allowed_actions"] == ["retry", "reanalyze"]
    assert outcome.report is None


def test_gf11_fail_inside_stage() -> None:
    """GF-11: 阶段执行中抛异常 → 该阶段 failed，后续阶段保持 pending。"""
    outcome = run_scenario("S04B")

    assert outcome.job["status"] == "failed"
    assert [s["id"] for s in outcome.job["stages"] if s["status"] == "failed"] == [
        "news"
    ]
    assert _done_stages(outcome) == ["market", "social"]
    assert outcome.job["stats"]["model_calls"] == 2
    assert outcome.events[-1]["payload"]["detail"] == "stage_failed"


def test_gf12_b2_interrupt_before_final_report() -> None:
    """GF-12: B2 最终报告前进程中断 → 对账改判 interrupted(lease_expired)。"""
    outcome = run_scenario("S05")

    assert outcome.job["status"] == "interrupted"
    assert len(_done_stages(outcome)) == 11
    assert outcome.job["stages"][-1]["status"] == "pending"
    assert outcome.events[-1]["payload"]["detail"] == "lease_expired"
    assert outcome.reconcile_notes == []
    assert outcome.report is None
    assert outcome.job["allowed_actions"] == [
        "resume_from_checkpoint",
        "retry",
        "reanalyze",
    ]


def test_gf13_b3_stage_output_without_event() -> None:
    """GF-13: B3 阶段产物已写、done 事件未保存 → interrupted + 对账备注。"""
    outcome = run_scenario("S06")

    assert outcome.job["status"] == "interrupted"
    assert outcome.job["stages"][2]["id"] == "news"
    assert outcome.job["stages"][2]["status"] == "active"
    assert [n["code"] for n in outcome.reconcile_notes] == [
        "unregistered_stage_output"
    ]
    assert "新闻舆情" in outcome.reconcile_notes[0]["message"]
    assert outcome.events[-1]["payload"]["detail"] == "unregistered_stage_output"
    assert not [
        e
        for e in outcome.events
        if e["type"] == "stage_changed"
        and e["payload"]["stage_id"] == "news"
        and e["payload"]["stage_status"] == "done"
    ]
    assert outcome.report_written is False


def test_gf14_b4_report_written_before_db_commit() -> None:
    """GF-14: B4 报告已落盘、数据库未提交 → interrupted，不自动判成功。"""
    outcome = run_scenario("S07")

    assert outcome.job["status"] == "interrupted"
    assert outcome.report_written is True
    assert outcome.report_committed is False
    assert outcome.report is not None
    assert outcome.job["report_id"] is None
    assert outcome.job["links"]["report"] is None
    assert [n["code"] for n in outcome.reconcile_notes] == ["unregistered_report"]
    assert outcome.events[-1]["payload"]["detail"] == "unregistered_report"
    assert _done_stages(outcome) == list(fake.STAGE_IDS)


def test_gf15_b5_backfill_report_ready() -> None:
    """GF-15: B5 报告已提交、完成事件未发 → 对账补发 report_ready 新序号。"""
    outcome = run_scenario("S08")

    assert outcome.job["status"] == "succeeded"
    assert outcome.report_committed is True
    status_events = [e for e in outcome.events if e["type"] == "status_changed"]
    assert [e["payload"]["to"] for e in status_events] == ["running", "succeeded"]
    ready = [e for e in outcome.events if e["type"] == "report_ready"]
    assert len(ready) == 1
    assert ready[0]["seq"] == outcome.events[-1]["seq"]
    assert ready[0]["seq"] == 40
    assert ready[0]["payload"]["content_hash"] == outcome.report["meta"]["content_hash"]
    assert ready[0]["payload"]["report_id"] == outcome.job["report_id"]


def test_gf16_b6_cancel_loses_to_finalization() -> None:
    """GF-16: B6 收尾先落盘 → succeeded，取消记 no-op。"""
    outcome = run_scenario("S09")

    assert outcome.job["status"] == "succeeded"
    assert _transitions(outcome)[-1] == ("cancel_requested", "succeeded")
    assert outcome.events[-2]["payload"]["detail"] == "cancel_noop"
    assert outcome.report_committed is True
    assert _done_stages(outcome) == list(fake.STAGE_IDS)
    assert any(e["type"] == "report_ready" for e in outcome.events)


def test_gf17_b6_cancel_wins_before_commit() -> None:
    """GF-17: B6 取消先确认 → cancelled，收尾产物丢弃。"""
    outcome = run_scenario("S09B")

    assert outcome.job["status"] == "cancelled"
    assert _transitions(outcome)[-1] == ("cancel_requested", "cancelled")
    assert outcome.report is None
    assert outcome.report_written is False
    assert outcome.report_committed is False
    assert not any(e["type"] == "report_ready" for e in outcome.events)
    assert outcome.job["allowed_actions"] == ["reanalyze"]


def test_gf18_duplicate_create_requests() -> None:
    """GF-18: 重复创建的五步判定，最终只有一个活动 job。"""
    config = {
        "llm_profile": "deepseek-default",
        "parallel_analysts": True,
        "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
    }

    ledger = FakeJobLedger()
    first = ledger.create("000629", "2026-10-24", config, idempotency_key="k1")
    replay = ledger.create("000629", "2026-10-24", config, idempotency_key="k1")
    other_key = ledger.create("000629", "2026-10-24", config, idempotency_key="k2")
    assert first.status_code == 201
    assert replay.status_code == 200 and replay.replayed
    assert other_key.status_code == 200 and other_key.existing_header
    assert first.job is replay.job is other_key.job
    assert len(ledger.jobs) == 1

    conflict = ledger.create(
        "000629",
        "2026-10-24",
        {**config, "parallel_analysts": False},
        idempotency_key="k3",
    )
    assert conflict.status_code == 409
    assert conflict.error_code == "active_conflict"
    assert conflict.active_job_id == first.job.job_id

    mismatch = ledger.create(
        "000629",
        "2026-10-24",
        {**config, "llm_profile": "other-profile"},
        idempotency_key="k1",
    )
    assert mismatch.status_code == 409
    assert mismatch.error_code == "idempotency_mismatch"

    outcome = first.job.run_all()
    assert outcome.job["status"] == "succeeded"
    assert len(ledger.jobs) == 1
    assert ledger.active_jobs() == []

    distinct = FakeJobLedger()
    results = [
        distinct.create("000629", "2026-10-24", config, idempotency_key=f"key-{i}")
        for i in range(10)
    ]
    assert {result.job.job_id for result in results} == {"job-0001"}
    assert len(distinct.jobs) == 1


def test_gf19_multi_browser_reconnect_is_read_only() -> None:
    """GF-19: 两个浏览器重连拿到同一快照，任务与事件行数不变。"""
    runner = FakeJobRunner()
    runner.start()
    for _ in range(5):
        runner.advance()
    before_job = runner.job_detail()
    before_events = len(runner.events)
    before_seq = runner.seq

    frames_a = runner.subscribe()
    frames_b = runner.subscribe()

    assert frames_a == frames_b
    assert frames_a[0]["type"] == "snapshot"
    assert frames_a[0]["seq"] == before_seq
    assert frames_a[0]["payload"]["last_seq"] == before_seq
    assert frames_a[0]["payload"]["job"] == before_job
    assert len(runner.events) == before_events
    assert runner.seq == before_seq
    assert runner.job_detail() == before_job

    runner.run_all()
    assert runner.status == "succeeded"


def test_gf20_event_replay_after_disconnect() -> None:
    """GF-20: 断线后按 Last-Event-ID 补发，序号连续且只读。"""
    runner = FakeJobRunner()
    runner.start()
    for _ in range(5):
        runner.advance()
    mark = runner.seq
    runner.run_all()

    replayed = runner.replay(mark)
    expected = [e for e in runner.events if e["seq"] > mark]
    assert replayed == expected
    assert [e["seq"] for e in replayed] == list(range(mark + 1, runner.seq + 1))

    frames = runner.subscribe(mark)
    assert frames[0]["type"] == "snapshot"
    assert frames[1:] == replayed
    assert runner.replay(runner.seq) == []
    assert runner.seq == len(runner.events)


def test_gf21_reconcile_queued_and_checkpoint_missing() -> None:
    """GF-21: B1 保持 queued；paused 检查点缺失改判 interrupted。"""
    queued = FakeJobRunner()
    result = queued.reconcile()
    assert result["before"] == "queued"
    assert result["after"] == "queued"
    assert queued.events == []
    assert queued.run_all().job["status"] == "succeeded"

    paused = FakeJobRunner(checkpoint_present=False)
    paused.start()
    paused.advance()
    paused.pause()
    paused.advance()
    assert paused.status == "paused"
    paused.reconcile()
    assert paused.status == "interrupted"
    assert paused.events[-1]["payload"]["detail"] == "checkpoint_missing"
    assert paused.reconcile_notes == []

    running = FakeJobRunner()
    running.start()
    running.advance()
    running.reconcile()
    assert running.status == "interrupted"
    assert running.events[-1]["payload"]["from"] == "running"

    pause_requested = FakeJobRunner()
    pause_requested.start()
    pause_requested.advance()
    pause_requested.pause()
    pause_requested.reconcile()
    assert pause_requested.status == "interrupted"
    assert pause_requested.events[-1]["payload"]["from"] == "pause_requested"

    cancel_requested = FakeJobRunner()
    cancel_requested.start()
    cancel_requested.advance()
    cancel_requested.cancel()
    cancel_requested.reconcile()
    assert cancel_requested.status == "interrupted"
    assert cancel_requested.events[-1]["payload"]["from"] == "cancel_requested"


def test_gf22_allowed_actions_and_illegal_pause() -> None:
    """GF-22: allowed_actions 与契约表逐字一致；queued 暂停被拒且状态不变。"""
    assert ALLOWED_ACTIONS == {
        "queued": ("cancel",),
        "running": ("pause", "cancel"),
        "pause_requested": ("cancel",),
        "paused": ("resume", "cancel"),
        "cancel_requested": (),
        "cancelled": ("reanalyze",),
        "succeeded": ("retry", "reanalyze"),
        "failed": ("retry", "reanalyze"),
        "interrupted": ("resume_from_checkpoint", "retry", "reanalyze"),
    }
    runner = FakeJobRunner()
    with pytest.raises(IllegalTransition) as excinfo:
        runner.pause()
    assert excinfo.value.rule == "I06"
    assert runner.status == "queued"
    assert runner.events == []


def test_gf23_scenario_catalog_matches_docs() -> None:
    """GF-23: 场景目录覆盖 S00–S12，且场景清单逐条出现。"""
    expected = {
        "S00",
        "S01",
        "S02",
        "S02B",
        "S03",
        "S04",
        "S04B",
        "S05",
        "S06",
        "S07",
        "S08",
        "S09",
        "S09B",
    }
    assert set(SCENARIOS) == expected
    doc = _read(FAKE_DOCS / "scenarios.md")
    for scenario_id in expected | set(fake.INTERACTION_SCENARIOS):
        assert scenario_id in doc, scenario_id
    for title in (
        "创建后立即取消",
        "运行中暂停",
        "暂停请求已受理后取消",
        "暂停后取消",
        "阶段完成后异常",
        "最终报告前中断",
        "最终报告后、数据库提交前中断",
        "重复启动请求",
        "多浏览器重连",
        "事件断线后补发",
    ):
        assert title in doc, title


def test_gf24_contract_write_backs_present() -> None:
    """GF-24: Day 6 发现的契约缺口已回写，且互相一致。"""
    state = _read(CONTRACTS / "job-state-machine.md")
    assert "| T20 | paused | cancel_requested |" in state
    errors = _read(CONTRACTS / "error-codes-v1.md")
    assert "T20" in errors
    tests = _read(CONTRACTS / "p1-state-machine-tests.md")
    assert "SM-14" in tests and "T01–T20" in tests
    api = _read(CONTRACTS / "api-v1.md")
    assert "`reconcile_notes`" in api
    sse = _read(CONTRACTS / "sse-events-v1.md")
    assert "审计记录" in sse and "不占 `seq`" in sse
    assert '"content_hash": "sha256:' not in sse
    crash = _read(CONTRACTS / "crash-boundaries.md")
    assert "不占 SSE 序号" in crash
    idem = _read(CONTRACTS / "idempotency-conflicts.md")
    assert "幂等键未命中" in idem


def test_gf25_performance_template_is_complete() -> None:
    """GF-25: 性能模板覆盖计划 8.5 的八项指标，并有机器可读模板。"""
    perf = _read(FAKE_DOCS / "perf-template.md")
    metrics = {
        "P01": "冷启动",
        "P02": "路由切换",
        "P03": "报告 GET",
        "P04": "报告列表筛选",
        "P05": "任务事件延迟",
        "P06": "PDF 首次生成",
        "P07": "PDF 缓存命中",
        "P08": "移动视口溢出和交互耗时",
    }
    for metric_id, label in metrics.items():
        assert metric_id in perf, metric_id
        assert label in perf, label
    template = json.loads(_read(FAKE_DOCS / "perf-result-template.json"))
    assert template["schema_version"] == "perf-result-v1"
    assert set(template["metrics"]) == set(metrics)


def test_gf26_matrix_covers_every_test() -> None:
    """GF-26: 测试矩阵引用的 GF 编号与本文件逐条相等。"""
    matrix = _read(FAKE_DOCS / "test-matrix.md")
    matrix_ids = set(re.findall(r"GF-\d{2}", matrix))

    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    found: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        docstring = ast.get_docstring(node) or ""
        found.extend(re.findall(r"GF-\d{2}", docstring))

    assert len(found) == len(set(found)), "duplicated GF id"
    assert set(found) == matrix_ids
    assert len(found) == 28


def test_gf27_cli_runs_standalone() -> None:
    """GF-27: 命令行可独立运行，S00 输出与库内调用一致。"""
    process = subprocess.run(
        [
            sys.executable,
            str(Path(fake.__file__)),
            "--scenario",
            "S00",
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert process.returncode == 0, process.stderr
    summary = json.loads(process.stdout)
    assert summary["status"] == "succeeded"
    assert summary["stages_done"] == 12
    assert summary["events"] == 40
    assert summary["model_calls"] == 14
    assert summary["report_committed"] is True


def test_gf28_pause_requested_then_cancel_uses_t12() -> None:
    """GF-28: 暂停请求已受理后取消走 T12，取消优先于暂停。"""
    outcome = run_scenario("S02B")

    assert outcome.job["status"] == "cancelled"
    assert _transitions(outcome) == [
        ("queued", "running"),
        ("running", "pause_requested"),
        ("pause_requested", "cancel_requested"),
        ("cancel_requested", "cancelled"),
    ]
    assert outcome.job["stats"]["model_calls"] == 3
    assert len(_done_stages(outcome)) == 3
    assert outcome.report is None
    assert not any(
        e["payload"]["to"] == "paused"
        for e in outcome.events
        if e["type"] == "status_changed"
    )
