"""P6-04pre entry checks: path resolution and the AD-01 guard.

The module is loaded but never started; no server, no migration, no database.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_backend.py"


@pytest.fixture(scope="module")
def entry():
    spec = importlib.util.spec_from_file_location("run_backend_entry", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_data_root_prefers_the_environment(entry, tmp_path):
    root = tmp_path / "data"
    assert entry.data_root({"TA_DATA_ROOT": str(root)}) == root.resolve()
    assert entry.data_root({}) == entry.DEFAULT_ROOT
    assert entry.DEFAULT_ROOT == Path.home() / ".tradingagents"


def test_resolve_paths_puts_store_under_the_root(entry, tmp_path):
    root = tmp_path / "data"
    assert entry.resolve_paths(root, {}) == (root / "jobs.db", root / "job_reports")

    db = tmp_path / "elsewhere" / "custom.db"
    reports = tmp_path / "elsewhere" / "reports"
    assert entry.resolve_paths(
        root,
        {"TA_JOBS_DB": str(db), "TA_JOB_REPORTS_DIR": str(reports)},
    ) == (db, reports)


def test_parse_args_switches(entry):
    args = entry._parse_args(["--real-models", "--no-worker", "--port", "8611"])
    assert args.real_models is True
    assert args.no_worker is True
    assert args.port == 8611
    assert entry._parse_args([]).port == entry.DEFAULT_PORT

    with pytest.raises(SystemExit):
        entry._parse_args(["--port", "0"])


def test_real_models_requires_the_environment_half(entry, monkeypatch):
    monkeypatch.delenv("TA_ENABLE_REAL_RUNNER", raising=False)
    monkeypatch.setattr(entry, "load_dotenv", lambda *args, **kwargs: None)
    with pytest.raises(SystemExit) as excinfo:
        entry.main(["--real-models", "--no-worker"])
    assert "AD-01" in str(excinfo.value)
