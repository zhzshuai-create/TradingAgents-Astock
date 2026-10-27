"""分析任务的幂等启动与浏览器刷新重连测试。"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

APP_PATH = PROJECT_ROOT / "web" / "app.py"
APP_TIMEOUT = 120


@pytest.fixture(autouse=True)
def _isolated_jobs(monkeypatch):
    import web.jobs as jobs

    monkeypatch.setattr(jobs, "_jobs", {})


def test_concurrent_reruns_launch_same_job_once():
    import web.jobs as jobs
    from web.progress import ProgressTracker

    workers = 12
    start = threading.Barrier(workers)
    launch_count = 0
    launch_lock = threading.Lock()
    trackers = []
    results_lock = threading.Lock()

    def launch():
        nonlocal launch_count
        with launch_lock:
            launch_count += 1
        return ProgressTracker(ticker="300750", trade_date="2026-10-27")

    def reconnect():
        start.wait()
        tracker = jobs.get_or_create_job("same-job", launch)
        with results_lock:
            trackers.append(tracker)

    threads = [threading.Thread(target=reconnect) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert launch_count == 1
    assert len(trackers) == workers
    assert all(tracker is trackers[0] for tracker in trackers)


def test_distinct_jobs_launch_independently():
    import web.jobs as jobs
    from web.progress import ProgressTracker

    first = jobs.get_or_create_job("job-a", lambda: ProgressTracker(ticker="000001"))
    second = jobs.get_or_create_job("job-b", lambda: ProgressTracker(ticker="300750"))

    assert first is not second
    assert first.ticker == "000001"
    assert second.ticker == "300750"


@pytest.mark.parametrize("terminal", ["complete", "error"])
def test_terminal_job_never_relaunches(terminal):
    import web.jobs as jobs
    from web.progress import ProgressTracker

    tracker = ProgressTracker()
    if terminal == "complete":
        tracker.is_complete = True
    else:
        tracker.error = "failed"
    launches = 0

    def forbidden_launch():
        nonlocal launches
        launches += 1
        return ProgressTracker()

    assert jobs.get_or_create_job("terminal-job", lambda: tracker) is tracker
    for _ in range(3):
        assert jobs.get_or_create_job("terminal-job", forbidden_launch) is tracker
    assert launches == 0


def test_failed_launch_leaves_no_phantom_job():
    import web.jobs as jobs
    from web.progress import ProgressTracker

    def fail():
        raise RuntimeError("thread start failed")

    with pytest.raises(RuntimeError, match="thread start failed"):
        jobs.get_or_create_job("broken-job", fail)

    assert jobs.get_job("broken-job") is None
    tracker = ProgressTracker()
    assert jobs.get_or_create_job("broken-job", lambda: tracker) is tracker


def _stub_network(monkeypatch):
    import web.data_functions as df
    import web.journal_service as js

    monkeypatch.setattr(df, "index_spot", lambda: {}, raising=True)
    monkeypatch.setattr(df, "tencent_quote", lambda codes: {}, raising=True)
    monkeypatch.setattr(js, "start_journal", lambda: None, raising=True)


def _app_with_job(job_id: str):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=APP_TIMEOUT)
    at.query_params["job_id"] = job_id
    at.run()
    return at


def test_refresh_rebinds_running_tracker_without_launching(monkeypatch):
    import streamlit as st
    import web.jobs as jobs
    import web.runner as runner
    from web.progress import ProgressTracker

    _stub_network(monkeypatch)
    monkeypatch.setattr(st, "rerun", lambda: None)
    tracker = ProgressTracker(ticker="300750", trade_date="2026-10-27", is_running=True)
    jobs._jobs["refresh-running"] = tracker
    monkeypatch.setattr(
        runner,
        "run_analysis_in_thread",
        lambda **kw: pytest.fail("刷新重连不得启动分析线程"),
        raising=True,
    )

    at = _app_with_job("refresh-running")

    assert not at.exception
    assert at.session_state["tracker"] is tracker
    assert at.query_params["job_id"] == "refresh-running"


def test_missing_job_warns_and_never_restarts(monkeypatch):
    import web.runner as runner

    _stub_network(monkeypatch)
    monkeypatch.setattr(
        runner,
        "run_analysis_in_thread",
        lambda **kw: pytest.fail("失效 URL 不得自动重建付费任务"),
        raising=True,
    )

    at = _app_with_job("missing-after-restart")

    assert not at.exception
    assert "job_id" not in at.query_params
    assert at.session_state.get("tracker") is None
    assert any("未找到该分析任务" in warning.value for warning in at.warning)


def test_history_navigation_detaches_job_without_stopping_it(monkeypatch):
    import web.components.sidebar as sidebar
    import web.jobs as jobs
    from web.progress import ProgressTracker

    _stub_network(monkeypatch)
    tracker = ProgressTracker(ticker="300750", trade_date="2026-10-27", error="failed")
    jobs._jobs["history-job"] = tracker
    monkeypatch.setattr(
        sidebar,
        "get_history",
        lambda: [{"ticker": "000001", "date": "2026-10-26", "path": "missing.json"}],
        raising=True,
    )

    at = _app_with_job("history-job")
    button = next(
        button for button in at.sidebar.button
        if button.key == "hist_000001_2026-10-26"
    )
    button.click()
    at.run()

    assert not at.exception
    assert "job_id" not in at.query_params
    assert at.session_state.get("tracker") is None
    assert jobs.get_job("history-job") is tracker


def test_main_history_without_job_id_does_not_raise(monkeypatch):
    import web.components.sidebar as sidebar
    import web.history as history
    from streamlit.testing.v1 import AppTest

    _stub_network(monkeypatch)
    entries = [{"ticker": "000001", "date": "2026-10-26", "path": "missing.json"}]
    monkeypatch.setattr(history, "get_history", lambda: entries, raising=True)
    monkeypatch.setattr(sidebar, "get_history", lambda: entries, raising=True)

    at = AppTest.from_file(str(APP_PATH), default_timeout=APP_TIMEOUT)
    at.run()
    button = next(
        button for button in at.button
        if button.key == "main_hist_000001_2026-10-26"
    )
    button.click()
    at.run()

    assert not at.exception
    assert "job_id" not in at.query_params
