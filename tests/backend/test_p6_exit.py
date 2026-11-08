"""P6-07 exit checks: the two aggregators keep their documented contract.

PY-01 pins the new ``--skip-python`` switch on ``e2e/e2e_p5.py``: it must skip
only the backend groups, never the suites, the migration head or the preflight.
PY-02 pins ``e2e/e2e_p6.py``: one build for the whole walkthrough (every child
aggregator gets ``--skip-build``, P4 also ``--skip-python-full``), the P5 child
gets the four skips, and P4's only tolerated self-failure is the ``--skip-build``
one that the aggregate's own build gate replaces.

Commands: .venv/Scripts/python.exe -m pytest tests/backend/test_p6_exit.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from e2e import e2e_p5, e2e_p6  # noqa: E402


def _stub_p5(monkeypatch, tmp_path, calls: list[str]) -> None:
    monkeypatch.setattr(e2e_p5, "ROOT", tmp_path)
    monkeypatch.setattr(e2e_p5, "EVIDENCE", tmp_path / "p5.json")
    monkeypatch.setattr(e2e_p5, "SHOTS", tmp_path / "shots")
    monkeypatch.setattr(e2e_p5, "LOGS", tmp_path / "shots" / "logs")
    monkeypatch.setattr(e2e_p5, "gates", [])
    monkeypatch.setattr(e2e_p5, "results", {})
    monkeypatch.setattr(
        e2e_p5,
        "python_groups",
        lambda: calls.append("python") or {"passed": 840, "skipped": 4, "ok": True},
    )
    monkeypatch.setattr(
        e2e_p5,
        "frontend_chain",
        lambda _temp: calls.append("build") or {},
    )
    monkeypatch.setattr(e2e_p5, "regression", lambda: calls.append("regression") or {})
    monkeypatch.setattr(e2e_p5, "suites", lambda: calls.append("suites") or {})
    monkeypatch.setattr(e2e_p5, "migrations", lambda: calls.append("heads") or "0007")
    monkeypatch.setattr(
        e2e_p5,
        "restore_generated",
        lambda: calls.append("restore") or [],
    )
    monkeypatch.setattr(
        e2e_p5,
        "preflight",
        lambda: calls.append("preflight") or {"passed": 10, "failed": 0, "smoke": True, "ok": True},
    )


def test_py01_skip_python_skips_only_the_python_groups(monkeypatch, tmp_path):
    calls: list[str] = []
    _stub_p5(monkeypatch, tmp_path, calls)

    e2e_p5.main(["--skip-build", "--skip-python", "--skip-regression", "--skip-preflight"])

    assert "python" not in calls
    assert calls == ["suites", "heads"]
    written = json.loads((tmp_path / "p5.json").read_text(encoding="utf-8"))
    assert written["legacy"]["python_passed"] is None
    assert written["legacy"]["python_skipped"] is None
    assert written["legacy"]["migration_head"] == "0007"


def test_py01_without_the_flag_the_python_groups_still_run(monkeypatch, tmp_path):
    calls: list[str] = []
    _stub_p5(monkeypatch, tmp_path, calls)

    e2e_p5.main(["--skip-build", "--skip-regression", "--skip-preflight"])

    assert calls == ["python", "suites", "heads"]
    written = json.loads((tmp_path / "p5.json").read_text(encoding="utf-8"))
    assert written["legacy"]["python_passed"] == 840
    assert written["legacy"]["python_skipped"] == 4


def test_py02_one_build_for_the_whole_walkthrough():
    assert e2e_p6.REGRESSION
    for name, _script, args, _floor in e2e_p6.REGRESSION:
        assert "--skip-build" in args, name
    p4_args = next(args for name, _s, args, _f in e2e_p6.REGRESSION if name == "p4")
    assert "--skip-python-full" in p4_args
    assert set(e2e_p6.P5_ARGS) == {
        "--skip-build",
        "--skip-python",
        "--skip-regression",
        "--skip-preflight",
    }
    assert e2e_p6.MIGRATION_HEAD == "0007"


def test_py02_p4_tolerates_only_the_skip_build_failure():
    floor = next(floor for name, _s, _a, floor in e2e_p6.REGRESSION if name == "p4")
    good = {
        "checks": floor + 10,
        "failures": ["exit criterion 4"],
        "criteria": {"1": True, "2": True, "3": True, "4": False},
        "route_switch": {"passed": True},
        "perf": {"passed": True},
    }

    assert e2e_p6.p4_passed(1, good, floor) is True
    assert e2e_p6.p4_passed(0, {**good, "failures": []}, floor) is True
    assert e2e_p6.p4_passed(1, {**good, "failures": ["exit criterion 4", "x"]}, floor) is False
    assert e2e_p6.p4_passed(1, {**good, "bundle": {"passed": True}}, floor) is False
    assert e2e_p6.p4_passed(
        1, {**good, "criteria": {"1": True, "2": False, "3": True}}, floor
    ) is False
    assert e2e_p6.p4_passed(1, {**good, "checks": floor - 1}, floor) is False
    assert e2e_p6.p4_passed(2, {**good, "failures": ["timeout"]}, floor) is False


def _run_p5_aggregate(
    monkeypatch, root: Path, doc: dict | None, returncode: int = 1
) -> bool:
    import types

    root.mkdir(parents=True, exist_ok=True)

    def fake_run(_label, _command, **_kwargs):
        if doc is not None:
            (root / "2026-11-07_P5出口证据.json").write_text(
                json.dumps(doc), encoding="utf-8"
            )
        return types.SimpleNamespace(returncode=returncode, stdout="", stderr=""), 0.1

    monkeypatch.setattr(e2e_p6, "REVIEWS", root)
    monkeypatch.setattr(e2e_p6, "run", fake_run)
    monkeypatch.setattr(e2e_p6, "gates", [])
    return e2e_p6.p5_aggregate()["passed"]


def test_py02_p5_tolerates_only_the_skipped_criterion(monkeypatch, tmp_path):
    gates = [{"name": f"g{i}", "passed": True} for i in range(8)]
    base = {
        "gates": gates,
        "failed_gates": [],
        "failed_criteria": ["1"],
        "passed": False,
        "criteria": [{"id": str(i), "passed": i != 1} for i in range(1, 5)],
        "suites": {},
    }

    assert _run_p5_aggregate(monkeypatch, tmp_path / "ok", base) is True
    all_green = {
        **base,
        "failed_criteria": [],
        "passed": True,
        "criteria": [{"id": str(i), "passed": True} for i in range(1, 5)],
    }
    assert _run_p5_aggregate(monkeypatch, tmp_path / "all", all_green, 0) is True

    bad_gate = {
        **base,
        "gates": gates[:-1] + [{"name": "g7", "passed": False}],
        "failed_gates": ["g7"],
    }
    assert _run_p5_aggregate(monkeypatch, tmp_path / "gate", bad_gate) is False
    assert _run_p5_aggregate(
        monkeypatch, tmp_path / "crit", {**base, "failed_criteria": ["1", "2"]}
    ) is False
    assert _run_p5_aggregate(monkeypatch, tmp_path / "missing", None) is False
