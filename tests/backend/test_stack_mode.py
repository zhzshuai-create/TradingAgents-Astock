"""P6-06 acceptance tests: the dual-stack switch (ST-01 .. ST-04).

Everything is pure: ports arrive as booleans or stubbed probes, the backend
restart is never invoked, and no test opens 8501/8600. The real start/stop run
is the drill evidence, not the suite.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
STACK_SCRIPT = ROOT / "scripts" / "stack_mode.py"
LAUNCH_SCRIPT = ROOT / "scripts" / "stack_launch.py"
BACKEND = ROOT / "backend"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def stack():
    return _load("stack_mode_under_test", STACK_SCRIPT)


@pytest.fixture(scope="module")
def launch():
    return _load("stack_launch_under_test", LAUNCH_SCRIPT)


def _file(tmp_path: Path, stack, monkeypatch, content: str) -> Path:
    path = tmp_path / ".env.stack"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(stack, "STACK_FILE", path)
    return path


# ST-01 -------------------------------------------------------------------


def test_st01_illegal_modes_are_refused(tmp_path, stack, monkeypatch):
    for raw in ("", "   ", "both", "nextt", "legacy-ui"):
        with pytest.raises(ValueError):
            stack.parse_write_mode(raw)

    bad_value = tmp_path / "bad.env"
    bad_value.write_text("ACTIVE_ANALYSIS_UI=both\n", encoding="utf-8")
    with pytest.raises(stack.StackError) as caught:
        stack.read_mode(bad_value)
    assert "ACTIVE_ANALYSIS_UI" in str(caught.value)

    missing_key = tmp_path / "empty.env"
    missing_key.write_text("# no key here\n", encoding="utf-8")
    with pytest.raises(stack.StackError):
        stack.read_mode(missing_key)

    target = tmp_path / ".env.stack"
    monkeypatch.setattr(stack, "STACK_FILE", target)
    with pytest.raises(SystemExit) as exit_code:
        stack.main(["set", "both"])
    assert exit_code.value.code == 2  # argparse choices, before any write
    assert not target.exists()

    with pytest.raises(stack.StackError):
        stack.plan_change("both", legacy_listening=False, backend_listening=False)


def test_st01_missing_file_means_legacy_and_roundtrips(tmp_path, stack):
    missing = tmp_path / "absent.env"
    assert stack.read_mode(missing) == "legacy"

    stack.write_mode_file("next", missing)
    assert missing.read_text(encoding="utf-8").strip() == "ACTIVE_ANALYSIS_UI=next"
    assert stack.read_mode(missing) == "next"

    stack.write_mode_file("legacy", missing)
    assert stack.read_mode(missing) == "legacy"


# ST-02 -------------------------------------------------------------------


def test_st02_next_is_refused_while_legacy_listens(tmp_path, stack, monkeypatch):
    with pytest.raises(stack.StackError) as caught:
        stack.plan_change("next", legacy_listening=True, backend_listening=False)
    assert "8501" in str(caught.value)

    path = _file(
        tmp_path, stack, monkeypatch, "ACTIVE_ANALYSIS_UI=legacy\n"
    )
    monkeypatch.setattr(
        stack,
        "port_open",
        lambda port, *args, **kwargs: port == stack.LEGACY_PORT,
    )
    assert stack.main(["set", "next"]) == 1
    assert path.read_text(encoding="utf-8").strip() == "ACTIVE_ANALYSIS_UI=legacy"


def test_st02_next_is_written_when_8501_is_free(tmp_path, stack, monkeypatch):
    path = _file(tmp_path, stack, monkeypatch, "ACTIVE_ANALYSIS_UI=legacy\n")
    monkeypatch.setattr(stack, "port_open", lambda port, *args, **kwargs: False)
    assert stack.main(["set", "next"]) == 0
    assert path.read_text(encoding="utf-8").strip() == "ACTIVE_ANALYSIS_UI=next"

    assert stack.plan_change(
        "next", legacy_listening=False, backend_listening=False
    ).restart_backend is False
    assert stack.plan_change(
        "legacy", legacy_listening=True, backend_listening=True
    ).restart_backend is True


def test_st02_only_run_backend_may_be_stopped(stack):
    backend = r"C:\py\python.exe scripts\run_backend.py --real-models"
    dev = r"C:\py\python.exe scripts\dev_backend.py"
    assert stack.is_owned_backend(backend)
    assert not stack.is_owned_backend(dev)
    assert not stack.is_owned_backend(None)
    assert not stack.is_owned_backend("")

    assert stack.require_owned_backend(
        8600,
        pid_lookup=lambda port: 7,
        command_lookup=lambda pid: "python scripts/run_backend.py",
    ) == 7
    with pytest.raises(stack.StackError):
        stack.require_owned_backend(
            8600,
            pid_lookup=lambda port: 7,
            command_lookup=lambda pid: "python scripts/dev_backend.py",
        )


def test_st02_set_refuses_a_foreign_8600_before_writing(tmp_path, stack, monkeypatch):
    path = _file(tmp_path, stack, monkeypatch, "ACTIVE_ANALYSIS_UI=next\n")
    monkeypatch.setattr(
        stack, "port_open", lambda port, *args, **kwargs: port == stack.BACKEND_PORT
    )
    monkeypatch.setattr(stack, "listener_pid", lambda port: 4242)
    monkeypatch.setattr(
        stack, "process_command", lambda pid: r"C:\py\python.exe scripts\dev_backend.py"
    )
    assert stack.main(["set", "legacy"]) == 1
    assert path.read_text(encoding="utf-8").strip() == "ACTIVE_ANALYSIS_UI=next"


# ST-03 -------------------------------------------------------------------


def _meta_client(tmp_path, monkeypatch, write_mode: str) -> dict:
    from backend.app.core.config import JOBS_DB_ENV
    from backend.app.core.db import build_engine
    from backend.app.core.journal_probe import JournalProbe
    from backend.app.core.server_config import ServerConfig
    from backend.app.main import create_app
    from backend.app.services.job_service import JobService
    from backend.app.services.report_store import ReportStore

    monkeypatch.setenv(JOBS_DB_ENV, str(tmp_path / "jobs" / "jobs.db"))
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(config, "head")

    engine = build_engine()
    reports = ReportStore(tmp_path / "reports")
    server_config = ServerConfig(write_mode=write_mode)
    service = JobService(engine, server_config, reports=reports)
    client = TestClient(
        create_app(
            service=service,
            server_config=server_config,
            report_store=reports,
            journal_probe=JournalProbe(
                entry_url="http://127.0.0.1:8522",
                install_dir=tmp_path / "missing-journal",
                connect=lambda host, port, timeout: None,
                health=lambda url, timeout: "ok",
            ),
        )
    )
    try:
        return client.get("/api/v1/meta/options").json()
    finally:
        client.close()
        engine.dispose()


def test_st03_status_agrees_with_meta_options(tmp_path, stack, monkeypatch):
    payload = _meta_client(tmp_path, monkeypatch, "next")
    assert payload["write_mode"] == "next"

    same = stack.evaluate_status(
        "next",
        legacy_listening=False,
        backend_listening=True,
        backend_meta=payload,
    )
    assert same.consistent
    assert same.backend_write_mode == "next"

    stale = stack.evaluate_status(
        "legacy",
        legacy_listening=False,
        backend_listening=True,
        backend_meta=payload,
    )
    assert not stale.consistent
    assert "write_mode" in stale.reason

    down = stack.evaluate_status(
        "legacy",
        legacy_listening=True,
        backend_listening=False,
        backend_meta=None,
    )
    assert down.consistent

    silent = stack.evaluate_status(
        "next",
        legacy_listening=False,
        backend_listening=True,
        backend_meta=None,
    )
    assert not silent.consistent


def test_st03_status_exit_code_follows_the_mismatch(tmp_path, stack, monkeypatch, capsys):
    path = _file(tmp_path, stack, monkeypatch, "ACTIVE_ANALYSIS_UI=next\n")
    monkeypatch.setattr(
        stack,
        "port_open",
        lambda port, *args, **kwargs: port == stack.BACKEND_PORT,
    )
    monkeypatch.setattr(
        stack, "fetch_meta", lambda port=stack.BACKEND_PORT, timeout=2.0: {
            "write_mode": "next", "contract_version": "api-v1"
        }
    )
    assert stack.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "stack mode  : next" in out
    assert "write_mode=next" in out

    monkeypatch.setattr(
        stack, "fetch_meta", lambda port=stack.BACKEND_PORT, timeout=2.0: {
            "write_mode": "legacy", "contract_version": "api-v1"
        }
    )
    assert stack.main(["status"]) == 1
    assert "mismatch" in capsys.readouterr().out

    path.write_text("ACTIVE_ANALYSIS_UI=legacy\n", encoding="utf-8")
    monkeypatch.setattr(stack, "port_open", lambda port, *args, **kwargs: False)
    assert stack.main(["status"]) == 0
    assert "backend 8600: closed" in capsys.readouterr().out


# ST-04 -------------------------------------------------------------------


def test_st04_legacy_keeps_todays_command(launch):
    command = launch.build_command(
        "legacy", python="C:/py/python.exe", venv_python="C:/venv/python.exe"
    )
    assert command == [
        "C:/py/python.exe",
        str(ROOT / "web" / "launch.py"),
        "--with-journal",
    ]
    assert Path(command[1]).exists()
    assert "run_backend" not in command[1]
    assert launch.build_command("legacy", python="py.exe", with_journal=False) == [
        "py.exe",
        str(ROOT / "web" / "launch.py"),
    ]
    expected = str(launch.VENV_PY) if launch.VENV_PY.exists() else sys.executable
    assert launch.legacy_command()[0] == expected

    env = launch.child_env("legacy", {"PATH": "x"})
    assert "ACTIVE_ANALYSIS_UI" not in env
    assert launch.child_env("next", {"PATH": "x"})["ACTIVE_ANALYSIS_UI"] == "next"


def test_st04_launch_dry_run_and_guards(tmp_path, launch, monkeypatch, capsys):
    path = tmp_path / ".env.stack"
    path.write_text("ACTIVE_ANALYSIS_UI=legacy\n", encoding="utf-8")
    monkeypatch.setattr(launch.stack_mode, "STACK_FILE", path)
    monkeypatch.setattr(
        launch.stack_mode, "port_open", lambda port, *args, **kwargs: False
    )
    assert launch.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "ACTIVE_ANALYSIS_UI=legacy" in out
    assert "web" in out and "launch.py" in out

    with pytest.raises(RuntimeError):
        launch.check_guards(
            "next", legacy_listening=True, backend_listening=False, backend_meta=None
        )
    with pytest.raises(RuntimeError):
        launch.check_guards(
            "next", legacy_listening=False, backend_listening=True, backend_meta=None
        )
    with pytest.raises(RuntimeError):
        launch.check_guards(
            "legacy",
            legacy_listening=False,
            backend_listening=True,
            backend_meta={"write_mode": "next"},
        )
    launch.check_guards(
        "legacy", legacy_listening=True, backend_listening=False, backend_meta=None
    )
    launch.check_guards(
        "legacy",
        legacy_listening=True,
        backend_listening=True,
        backend_meta={"write_mode": "legacy"},
    )

    next_command = launch.build_command(
        "next", venv_python=ROOT / ".venv" / "Scripts" / "python.exe"
    )
    assert next_command[-1] == str(ROOT / "scripts" / "run_backend.py")
    assert "--real-models" not in next_command
    assert "--real-models" in launch.build_command("next", real_models=True)
