"""P6-08 acceptance tests: the next launch plan (SL-01 .. SL-06).

Everything is pure: plans are command lists and guards take booleans, so no
test starts 8600 / 5173 / 8502. The real three-port start is the S2..S5
evidence, not the suite.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCH_SCRIPT = ROOT / "scripts" / "stack_launch.py"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
# Guard tests need an interpreter that exists; CI has no repo .venv.
EXISTING_PY = Path(sys.executable)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def launch():
    return _load("stack_launch_under_test_p608", LAUNCH_SCRIPT)


@pytest.fixture
def journal(launch, tmp_path, monkeypatch):
    journal_dir = tmp_path / "trade-journal"
    journal_dir.mkdir()
    app = journal_dir / "app.py"
    app.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(launch, "JOURNAL_DIR", journal_dir)
    monkeypatch.setattr(launch, "JOURNAL_APP", app)
    return journal_dir, app


# SL-01 -------------------------------------------------------------------


def test_sl01_next_plan_has_three_steps(launch, journal):
    journal_dir, app = journal
    plan = launch.build_plan("next", venv_python=VENV_PY, real_models=True)
    assert [step.name for step in plan] == ["backend", "ui", "journal"]

    backend, ui, log = plan
    assert str(launch.BACKEND_SCRIPT) in backend.command
    assert backend.command[-1] == "--real-models"
    assert backend.cwd == ROOT

    assert ui.command[0] == "node"
    assert str(launch.VITE_ENTRY) in ui.command
    assert ui.command[1:3] == [str(launch.VITE_ENTRY), "preview"]
    assert "--port" in ui.command and "5173" in ui.command
    assert "--host" in ui.command and "127.0.0.1" in ui.command
    assert "--strictPort" in ui.command
    assert ui.cwd == launch.FRONTEND_DIR

    assert log.command[1:4] == ["-m", "streamlit", "run"]
    assert str(app) in log.command
    assert log.command[-2:] == ["--server.port", "8502"]
    assert log.cwd == journal_dir


# SL-02 -------------------------------------------------------------------


def test_sl02_no_ui_and_no_journal_drop_steps(launch, journal, monkeypatch, tmp_path):
    assert [s.name for s in launch.build_plan("next", with_ui=False)] == [
        "backend",
        "journal",
    ]
    assert [s.name for s in launch.build_plan("next", with_journal=False)] == [
        "backend",
        "ui",
    ]
    plan = launch.build_plan(
        "next", with_ui=False, with_journal=False, venv_python=VENV_PY
    )
    assert [s.name for s in plan] == ["backend"]

    monkeypatch.setattr(launch, "JOURNAL_APP", tmp_path / "missing" / "app.py")
    assert [s.name for s in launch.build_plan("next")] == ["backend", "ui"]


# SL-03 -------------------------------------------------------------------


def test_sl03_preview_port_and_venv_guards(launch):
    with pytest.raises(launch.stack_mode.StackError, match="5173"):
        launch.check_guards(
            "next",
            legacy_listening=False,
            backend_listening=False,
            backend_meta=None,
            preview_listening=True,
            venv_python=VENV_PY,
        )
    launch.check_guards(
        "next",
        legacy_listening=False,
        backend_listening=False,
        backend_meta=None,
        preview_listening=False,
        venv_python=EXISTING_PY,
    )
    # legacy never owns 5173 and must not be blocked by a preview.
    launch.check_guards(
        "legacy",
        legacy_listening=True,
        backend_listening=False,
        backend_meta=None,
        preview_listening=True,
    )

    missing = LAUNCH_SCRIPT.parent / "no-such-python.exe"
    with pytest.raises(launch.stack_mode.StackError, match="uvicorn"):
        launch.check_guards(
            "next",
            legacy_listening=False,
            backend_listening=False,
            backend_meta=None,
            venv_python=missing,
        )


# SL-04 -------------------------------------------------------------------


def test_sl04_legacy_plan_is_unchanged(launch):
    plan = launch.build_plan(
        "legacy", python="C:/py/python.exe", venv_python="C:/venv/python.exe"
    )
    assert len(plan) == 1
    step = plan[0]
    assert step.name == "legacy"
    assert step.command == [
        "C:/py/python.exe",
        str(ROOT / "web" / "launch.py"),
        "--with-journal",
    ]
    assert step.cwd == ROOT

    no_journal = launch.build_plan("legacy", python="py.exe", with_journal=False)
    assert no_journal[0].command == ["py.exe", str(ROOT / "web" / "launch.py")]

    # build_command stays the flat next command the older suite asserts on.
    assert launch.build_command("next")[-1] == str(launch.BACKEND_SCRIPT)
    assert "--real-models" not in launch.build_command("next")
    assert "--real-models" in launch.build_command("next", real_models=True)


# SL-05 -------------------------------------------------------------------


def test_sl05_require_ui_points_at_npm_build(launch, tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "VITE_ENTRY", tmp_path / "vite.js")
    monkeypatch.setattr(launch, "DIST_INDEX", tmp_path / "index.html")
    with pytest.raises(launch.stack_mode.StackError, match="npm run build"):
        launch.require_ui()

    (tmp_path / "vite.js").write_text("", encoding="utf-8")
    (tmp_path / "index.html").write_text("", encoding="utf-8")
    launch.require_ui()


# SL-06 -------------------------------------------------------------------


def test_sl06_main_dry_run_prints_the_three_children(
    launch, journal, tmp_path, monkeypatch, capsys
):
    _journal_dir, app = journal
    stack_file = tmp_path / ".env.stack"
    stack_file.write_text("ACTIVE_ANALYSIS_UI=next\n", encoding="utf-8")
    monkeypatch.setattr(launch.stack_mode, "STACK_FILE", stack_file)
    monkeypatch.setattr(
        launch.stack_mode, "port_open", lambda port, *args, **kwargs: False
    )
    monkeypatch.setattr(launch.stack_mode, "fetch_meta", lambda *a, **k: None)
    vite = tmp_path / "vite.js"
    vite.write_text("", encoding="utf-8")
    dist = tmp_path / "index.html"
    dist.write_text("", encoding="utf-8")
    monkeypatch.setattr(launch, "VITE_ENTRY", vite)
    monkeypatch.setattr(launch, "DIST_INDEX", dist)
    monkeypatch.setattr(launch, "VENV_PY", EXISTING_PY)

    assert launch.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "ACTIVE_ANALYSIS_UI=next" in out
    assert "backend:" in out and "ui:" in out and "journal:" in out
    assert "preview" in out and str(app) in out

    assert launch.main(["--dry-run", "--no-ui", "--no-journal"]) == 0
    out = capsys.readouterr().out
    assert "backend:" in out
    assert "ui:" not in out and "journal:" not in out
