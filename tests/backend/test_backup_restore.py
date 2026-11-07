"""P6-03 验收测试：备份与恢复（BR-01 .. BR-06）。

所有用例只碰 ``tmp_path``，不读写真实 ``~/.tradingagents``，不联网。
BR-04 依赖 Windows 的文件占用语义（打开中的 SQLite 文件无法改名）。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECRET = "sk-test-do-not-copy"
WHITELIST_FILES = (
    "jobs.db",
    "logs/app.log",
    "exports/r1.pdf",
    "memory/notes.md",
    "job_reports/j1/report.json",
    "job_reports/j1/stage-1/attempt-1.md",
    "incomplete_tasks.json",
)
EXCLUDED_FILES = (
    "cache/blob.bin",
    "cache_ds_601208/kline.csv",
    "logs_ds_601208/run.log",
    "ds_run_console.log",
    "llm_config.json",
)


@pytest.fixture(scope="module")
def br():
    spec = importlib.util.spec_from_file_location(
        "p6_backup_restore", ROOT / "scripts" / "backup_restore.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)


def _make_root(root: Path, rows: tuple[str, ...] = ("j1", "j2")) -> None:
    root.mkdir(parents=True, exist_ok=True)
    db = root / "jobs.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, title TEXT)")
        for row in rows:
            conn.execute("INSERT INTO jobs (id, title) VALUES (?, ?)", (row, f"task {row}"))
        conn.commit()
    finally:
        conn.close()

    _write(root / "logs" / "app.log", "alpha\n")
    _write(root / "exports" / "r1.pdf", b"%PDF-1.4 fake export")
    _write(root / "memory" / "notes.md", "memory note\n")
    _write(root / "job_reports" / "j1" / "report.json", '{"meta":{},"sections":{}}')
    _write(root / "job_reports" / "j1" / "stage-1" / "attempt-1.md", "stage text\n")
    _write(root / "incomplete_tasks.json", '{"stale": []}')

    _write(root / "cache" / "blob.bin", b"cache payload")
    _write(root / "cache_ds_601208" / "kline.csv", "date,close\n")
    _write(root / "logs_ds_601208" / "run.log", "data-source log\n")
    _write(root / "ds_run_console.log", "console log\n")
    _write(
        root / "llm_config.json",
        json.dumps({"api_key": SECRET, "llm_base_url": "http://example.invalid"}),
    )


def _dir_state(root: Path) -> dict[str, tuple[int, int]]:
    state: dict[str, tuple[int, int]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        stat = path.stat()
        if path.is_dir():
            state[rel + "/"] = (stat.st_mtime_ns, 0)
        else:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            state[rel] = (stat.st_mtime_ns, int(digest, 16))
    return state


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _read_manifest(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as archive:
        return json.loads(archive.read("manifest.json").decode("utf-8"))


def test_br_01_whitelist_included_and_excluded(br, tmp_path):
    root = tmp_path / "data"
    _make_root(root)
    out = tmp_path / "backup.zip"

    result = br.backup(root, out=out)
    manifest = result["manifest"]

    assert set(manifest["included"]) == {
        "jobs.db",
        "logs",
        "exports",
        "memory",
        "job_reports",
        "incomplete_tasks.json",
    }
    assert list(manifest["excluded"]) == list(br.EXCLUDED)
    assert manifest["migration_head"]

    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
        manifest_text = archive.read("manifest.json").decode("utf-8")
    assert set(WHITELIST_FILES) <= names
    for name in EXCLUDED_FILES:
        assert name not in names
    assert not any(name.startswith("cache/") for name in names)

    assert SECRET not in manifest_text
    assert "api_key" not in manifest_text.lower()

    for name in names:
        assert not name.startswith("/")
        assert "\\" not in name
        assert ".." not in Path(name).parts
        assert ":" not in name


def test_br_02_wal_snapshot_restores_rows(br, tmp_path):
    root = tmp_path / "data"
    _make_root(root)
    out = tmp_path / "backup.zip"

    live = sqlite3.connect(root / "jobs.db")
    try:
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("INSERT INTO jobs (id, title) VALUES ('j3', 'task j3')")
        live.commit()
        br.backup(root, out=out)
    finally:
        live.close()

    target = tmp_path / "restored"
    result = br.restore(out, root=target, apply=True)
    assert result["applied"] is True
    assert result["verified"] is True

    conn = sqlite3.connect(target / "jobs.db")
    try:
        rows = conn.execute("SELECT id, title FROM jobs ORDER BY id").fetchall()
    finally:
        conn.close()
    assert rows == [("j1", "task j1"), ("j2", "task j2"), ("j3", "task j3")]


def test_br_03_dry_run_writes_nothing(br, tmp_path):
    source = tmp_path / "data"
    _make_root(source)
    out = tmp_path / "backup.zip"
    br.backup(source, out=out)

    target = tmp_path / "target"
    _make_root(target, rows=("old",))
    before = _dir_state(target)

    result = br.restore(out, root=target, apply=False)

    assert result["applied"] is False
    assert _dir_state(target) == before
    assert not list(target.glob("pre-restore-*"))
    assert result["replace"]
    assert (target / "logs" / "app.log").read_text(encoding="utf-8") == "alpha\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows 才以文件占用阻止替换")
def test_br_04_refuses_restore_while_backend_running(br, tmp_path):
    source = tmp_path / "data"
    _make_root(source)
    out = tmp_path / "backup.zip"
    br.backup(source, out=out)

    target = tmp_path / "target"
    _make_root(target, rows=("old",))

    conn = sqlite3.connect(target / "jobs.db")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        assert conn.execute("SELECT count(*) FROM jobs").fetchone() is not None
        before = _file_hashes(target)
        with pytest.raises(br.BackupRestoreError) as excinfo:
            br.restore(out, root=target, apply=True)
        message = str(excinfo.value)
        assert "8600" in message and "8501" in message
        assert _file_hashes(target) == before
        assert not list(target.glob("pre-restore-*"))
    finally:
        conn.close()


def test_br_05_rejects_tampered_archive(br, tmp_path):
    source = tmp_path / "data"
    _make_root(source)
    out = tmp_path / "backup.zip"
    br.backup(source, out=out)

    target = tmp_path / "target"
    _make_root(target, rows=("old",))
    before = _dir_state(target)

    bad_content = tmp_path / "bad_content.zip"
    with zipfile.ZipFile(out) as archive, zipfile.ZipFile(bad_content, "w") as tampered:
        for item in archive.infolist():
            data = archive.read(item.filename)
            if item.filename == "logs/app.log":
                data = b"tampered"
            tampered.writestr(item, data)

    with pytest.raises(br.BackupRestoreError):
        br.restore(bad_content, root=target, apply=True)

    bad_manifest = tmp_path / "bad_manifest.zip"
    with zipfile.ZipFile(out) as archive, zipfile.ZipFile(bad_manifest, "w") as tampered:
        for item in archive.infolist():
            data = archive.read(item.filename)
            if item.filename == "manifest.json":
                document = json.loads(data)
                for entry in document["files"]:
                    if entry["path"] == "jobs.db":
                        entry["sha256"] = "0" * 64
                data = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
            tampered.writestr(item, data)

    with pytest.raises(br.BackupRestoreError):
        br.restore(bad_manifest, root=target, apply=True)

    assert _dir_state(target) == before
    assert not list(target.glob("pre-restore-*"))


def test_br_06_apply_keeps_old_files_in_pre_restore(br, tmp_path):
    source = tmp_path / "data"
    _make_root(source)
    out = tmp_path / "backup.zip"
    br.backup(source, out=out)
    manifest = _read_manifest(out)

    target = tmp_path / "target"
    first = br.restore(out, root=target, apply=True)
    assert first["applied"] is True
    assert first["pre_restore"] is None

    (target / "logs" / "app.log").write_text("old content\n", encoding="utf-8")

    result = br.restore(out, root=target, apply=True)
    assert result["applied"] is True
    assert result["verified"] is True
    assert result["pre_restore"]

    pre_restore = Path(result["pre_restore"])
    assert pre_restore.is_dir()
    assert (pre_restore / "logs" / "app.log").read_text(encoding="utf-8") == "old content\n"

    for entry in manifest["files"]:
        path = target / entry["path"]
        assert path.stat().st_size == entry["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]

    assert not (target / "llm_config.json").exists()
    assert not (target / "cache").exists()
