"""失败任务同参数重试与报告返回导航测试。"""

from __future__ import annotations

import sys
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


def test_retry_uses_original_config_and_launches_one_new_job(monkeypatch):
    import web.jobs as jobs
    import web.runner as runner
    from web.progress import ProgressTracker

    _stub_network(monkeypatch)
    original_config = {
        "deep_think_llm": "original-model",
        "parallel_analysts": True,
        "data_vendors": {"core_stock_apis": "a_stock"},
    }
    old_tracker = ProgressTracker(
        ticker="300750",
        trade_date="2026-10-27",
        error="failed",
        run_config=original_config,
    )
    jobs._jobs["failed-job"] = old_tracker
    started = []
    monkeypatch.setattr(
        runner,
        "run_analysis_in_thread",
        lambda **kw: started.append(kw),
        raising=True,
    )

    at = _app_with_job("failed-job")
    button = next(button for button in at.button if button.key == "retry_analysis")
    button.click()
    at.run()
    at.run()

    assert not at.exception
    assert len(started) == 1
    request = started[0]
    assert request["ticker"] == "300750"
    assert request["trade_date"] == "2026-10-27"
    assert request["config"] == original_config
    assert request["tracker"].run_config == original_config
    new_job_id = at.query_params["job_id"]
    assert new_job_id != "failed-job"
    assert jobs.get_job("failed-job") is old_tracker
    assert jobs.get_job(new_job_id) is request["tracker"]

    refreshed = _app_with_job(new_job_id)
    assert not refreshed.exception
    assert refreshed.session_state["tracker"] is request["tracker"]
    assert len(started) == 1


def test_completed_report_new_analysis_prefills_without_launching(monkeypatch):
    import web.components.report_viewer as report_viewer
    import web.jobs as jobs
    import web.runner as runner
    from web.progress import ProgressTracker

    _stub_network(monkeypatch)
    monkeypatch.setattr(report_viewer, "render_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner,
        "run_analysis_in_thread",
        lambda **kw: pytest.fail("新建分析只回填，不得自动启动"),
        raising=True,
    )
    tracker = ProgressTracker(
        ticker="300750",
        trade_date="2026-10-27",
        is_complete=True,
        final_state={},
    )
    jobs._jobs["complete-job"] = tracker

    at = _app_with_job("complete-job")
    assert {button.key for button in at.button} >= {"report_home", "report_new_analysis"}
    button = next(button for button in at.button if button.key == "report_new_analysis")
    button.click()
    at.run()
    at.run()

    assert not at.exception
    assert "job_id" not in at.query_params
    assert at.session_state.get("tracker") is None
    ticker_input = next(
        widget for widget in at.sidebar.text_input if widget.key == "input_ticker"
    )
    assert ticker_input.value == "300750"
    assert jobs.get_job("complete-job") is tracker


def test_history_report_returns_home_without_launching(monkeypatch):
    import web.components.report_viewer as report_viewer
    import web.history as history
    import web.runner as runner
    from streamlit.testing.v1 import AppTest

    _stub_network(monkeypatch)
    monkeypatch.setattr(report_viewer, "render_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(history, "load_analysis", lambda path: {}, raising=True)
    monkeypatch.setattr(history, "extract_signal", lambda state: "Hold", raising=True)
    monkeypatch.setattr(
        runner,
        "run_analysis_in_thread",
        lambda **kw: pytest.fail("返回首页不得启动分析"),
        raising=True,
    )
    path = "results/000001/2026-10-26/full_states_log_2026-10-26.json"

    at = AppTest.from_file(str(APP_PATH), default_timeout=APP_TIMEOUT)
    at.session_state["viewing_history"] = path
    at.run()
    assert {button.key for button in at.button} >= {"report_home", "report_new_analysis"}
    button = next(button for button in at.button if button.key == "report_home")
    button.click()
    at.run()

    assert not at.exception
    assert at.session_state.get("viewing_history") is None
    assert at.session_state.get("tracker") is None
    assert "job_id" not in at.query_params
