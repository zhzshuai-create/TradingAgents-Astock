"""P6-03 备份与恢复：白名单快照，restore 默认 dry-run。

    .venv/Scripts/python.exe scripts/backup_restore.py backup --live
    .venv/Scripts/python.exe scripts/backup_restore.py restore <zip> --live
    .venv/Scripts/python.exe scripts/backup_restore.py restore <zip> --root <dir> --apply

备份：``jobs.db`` 用 sqlite3 backup API 导出（WAL 下直接复制会拿到撕裂快照或
漏掉 ``-wal``），其余按 WHITELIST 收文件、按 EXCLUDED 排除，zip 内附
``manifest.json``。还原：先逐项重算 sha256；默认只打印差异；``--apply`` 才把
旧文件移入 ``pre-restore-<时间戳>/`` 并按文件替换，替换后复核哈希。

脚本不启动、不停止任何进程；未加 ``--live`` 时拒绝指向真实数据根
``~/.tradingagents``。只依赖标准库与已有的 Alembic（只读取迁移头）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import (  # noqa: E402
    EXPORTS_DIR_ENV,
    get_exports_dir,
    get_jobs_db_path,
)

CST = timezone(timedelta(hours=8))
CHUNK = 1024 * 1024
MANIFEST_NAME = "manifest.json"
MANIFEST_FORMAT = 1

WHITELIST = (
    "jobs.db",
    "logs",
    "exports",
    "memory",
    "job_reports",
    "incomplete_tasks.json",
)
EXCLUDED = (
    "cache/",
    "cache_ds_*/",
    "logs_ds_*/",
    "ds_run_console.log",
    "llm_config.json",
)
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")

_MIGRATION_HEAD: str | None = None


class BackupRestoreError(RuntimeError):
    """可预期的失败：打印后以非零码退出，不做半截操作。"""


def real_data_root() -> Path:
    return get_jobs_db_path().expanduser().parent.resolve()


def _now() -> datetime:
    return datetime.now(CST)


def _stamp(moment: datetime | None = None) -> str:
    return (moment or _now()).strftime("%Y%m%d-%H%M%S")


def _write_mode() -> str:
    return os.environ.get("ACTIVE_ANALYSIS_UI", "legacy").strip().lower() or "legacy"


def _migration_head() -> str:
    global _MIGRATION_HEAD
    if _MIGRATION_HEAD is None:
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            config = Config(str(ROOT / "backend" / "alembic.ini"))
            _MIGRATION_HEAD = ScriptDirectory.from_config(config).get_current_head() or "unknown"
        except Exception:
            _MIGRATION_HEAD = "unknown"
    return _MIGRATION_HEAD


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _is_excluded(rel: PurePosixPath) -> bool:
    for part in rel.parts:
        if part == "cache" or part.startswith("cache_ds_") or part.startswith("logs_ds_"):
            return True
        if part in {"ds_run_console.log", "llm_config.json"}:
            return True
    return False


def _safe_rel(name: str) -> PurePosixPath:
    if not name or name.startswith("/") or "\\" in name:
        raise BackupRestoreError(f"zip 内路径不合法: {name!r}")
    rel = PurePosixPath(name)
    if rel.is_absolute() or ":" in rel.parts[0] or any(part in {"", ".."} for part in rel.parts):
        raise BackupRestoreError(f"zip 内路径不合法: {name!r}")
    return rel


def _resolve_root(root: Path | str | None, live: bool, *, must_exist: bool) -> Path:
    if root is None:
        path = real_data_root()
    else:
        path = Path(root).expanduser().resolve()
    if path == real_data_root() and not live:
        raise BackupRestoreError("目标指向真实数据根 ~/.tradingagents；确认后加 --live 再执行")
    if must_exist and not path.is_dir():
        raise BackupRestoreError(f"数据根不存在: {path}")
    return path


def _unique_dir(parent: Path, name: str) -> Path:
    candidate = parent / name
    index = 2
    while candidate.exists():
        candidate = parent / f"{name}-{index}"
        index += 1
    return candidate


def _snapshot_db(source: Path, snapshot: Path) -> None:
    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    dst = sqlite3.connect(str(snapshot))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _collect_files(data_root: Path) -> list[tuple[str, Path]]:
    collected: list[tuple[str, Path]] = []
    for name in WHITELIST:
        if name == "jobs.db":
            continue
        top = data_root / name
        if top.is_symlink() or not top.exists():
            continue
        if top.is_dir():
            children = sorted(
                top.rglob("*"),
                key=lambda path: path.relative_to(data_root).as_posix(),
            )
            for child in children:
                if child.is_symlink() or not child.is_file():
                    continue
                rel = PurePosixPath(child.relative_to(data_root).as_posix())
                if _is_excluded(rel):
                    continue
                collected.append((rel.as_posix(), child))
        elif top.is_file():
            collected.append((name, top))
    return collected


def backup(
    root: Path | str | None = None,
    *,
    db: Path | str | None = None,
    out: Path | str | None = None,
    live: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    data_root = _resolve_root(root, live, must_exist=True)
    db_path = Path(db).expanduser().resolve() if db else data_root / "jobs.db"
    if not live and db_path.is_relative_to(real_data_root()):
        raise BackupRestoreError("数据库指向真实数据根 ~/.tradingagents；确认后加 --live 再执行")
    if not db_path.is_file():
        raise BackupRestoreError(f"数据库不存在: {db_path}")

    out_path = (
        Path(out).expanduser()
        if out
        else Path.home() / "tradingagents-backups" / f"backup-{_stamp()}.zip"
    )
    out_path = out_path.resolve()
    print(f"[backup] 将写入: {out_path}", flush=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    exports = get_exports_dir().expanduser().resolve()
    if os.environ.get(EXPORTS_DIR_ENV) and not exports.is_relative_to(data_root):
        print(f"[backup] 提示: 导出目录配置为 {exports}，数据根外的导出文件不入包", flush=True)

    included = [name for name in WHITELIST if (data_root / name).exists()]
    collected = _collect_files(data_root)

    snapshot_dir = Path(tempfile.mkdtemp(prefix="p6-backup-db-"))
    try:
        snapshot = snapshot_dir / "jobs.db"
        sidecars = [
            db_path.with_name(db_path.name + suffix) for suffix in SIDECAR_SUFFIXES
        ]
        existed = {path: path.exists() for path in sidecars}
        try:
            _snapshot_db(db_path, snapshot)
        finally:
            for path, was_there in existed.items():
                if not was_there and path.exists():
                    try:
                        path.unlink()
                    except OSError as exc:
                        print(f"[backup] 提示: 无法清理 {path.name}: {exc}", flush=True)
        db_sha, db_bytes = _sha256_file(snapshot)

        entries: list[dict[str, Any]] = [
            {"path": "jobs.db", "bytes": db_bytes, "sha256": db_sha}
        ]
        for rel, path in collected:
            digest, size = _sha256_file(path)
            entries.append({"path": rel, "bytes": size, "sha256": digest})

        manifest = {
            "format": MANIFEST_FORMAT,
            "created_at": _now().isoformat(timespec="seconds"),
            "source_root": str(data_root),
            "write_mode": _write_mode(),
            "migration_head": _migration_head(),
            "included": included,
            "excluded": list(EXCLUDED),
            "db": {"path": "jobs.db", "bytes": db_bytes, "sha256": db_sha},
            "files": entries,
            "counts": {
                "files": len(entries),
                "bytes": sum(entry["bytes"] for entry in entries),
            },
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

        handle, temp_name = tempfile.mkstemp(
            prefix=".p6-backup-", suffix=".zip", dir=str(out_path.parent)
        )
        os.close(handle)
        try:
            with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, "jobs.db")
                for rel, path in collected:
                    archive.write(path, rel)
                archive.writestr(MANIFEST_NAME, manifest_bytes)
            _verify_backup(Path(temp_name), manifest_bytes, entries)
            os.replace(temp_name, out_path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
    finally:
        shutil.rmtree(snapshot_dir, ignore_errors=True)

    duration = round(time.perf_counter() - started, 3)
    zip_sha, zip_bytes = _sha256_file(out_path)
    counts = manifest["counts"]
    print(
        f"[backup] 入包 {counts['files']} 个文件，{counts['bytes']} B；耗时 {duration}s",
        flush=True,
    )
    print(f"[backup] 排除（固定）: {', '.join(EXCLUDED)}", flush=True)
    print(f"[backup] 校验通过: {MANIFEST_NAME} 与全部条目哈希一致", flush=True)
    print(f"[OK] {out_path}", flush=True)
    return {
        "zip": str(out_path),
        "zip_bytes": zip_bytes,
        "zip_sha256": zip_sha,
        "manifest": manifest,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "duration_seconds": duration,
    }


def _verify_backup(zip_path: Path, manifest_bytes: bytes, entries: list[dict[str, Any]]) -> None:
    expected = {entry["path"] for entry in entries} | {MANIFEST_NAME}
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        if names != expected:
            raise BackupRestoreError(
                f"备份校验失败: 条目不符（缺 {sorted(expected - names)}，多 {sorted(names - expected)}）"
            )
        if archive.read(MANIFEST_NAME) != manifest_bytes:
            raise BackupRestoreError("备份校验失败: manifest.json 回读不一致")
        for entry in entries:
            digest = hashlib.sha256()
            size = 0
            with archive.open(entry["path"]) as handle:
                for chunk in iter(lambda: handle.read(CHUNK), b""):
                    digest.update(chunk)
                    size += len(chunk)
            if size != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
                raise BackupRestoreError(f"备份校验失败: {entry['path']} 哈希不一致")


def _validate_manifest(manifest: Any) -> None:
    if not isinstance(manifest, dict) or manifest.get("format") != MANIFEST_FORMAT:
        raise BackupRestoreError("manifest.json 格式不受支持")
    files = manifest.get("files")
    db = manifest.get("db")
    if not isinstance(files, list) or not isinstance(db, dict):
        raise BackupRestoreError("manifest.json 缺少 files / db")
    for entry in files:
        if not isinstance(entry, dict) or not {"path", "bytes", "sha256"} <= set(entry):
            raise BackupRestoreError("manifest.json 的 files 条目不完整")
    paths = [entry["path"] for entry in files]
    if len(paths) != len(set(paths)):
        raise BackupRestoreError("manifest.json 存在重复条目")
    if db.get("path") not in paths:
        raise BackupRestoreError("manifest.json 的 db.path 不在 files 中")
    counts = manifest.get("counts") or {}
    if counts.get("files") != len(files) or counts.get("bytes") != sum(
        entry["bytes"] for entry in files
    ):
        raise BackupRestoreError("manifest.json 的 counts 与 files 不一致")


def _load_archive(zip_path: Path) -> dict[str, Any]:
    if not zip_path.is_file():
        raise BackupRestoreError(f"备份包不存在: {zip_path}")
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        if MANIFEST_NAME not in names:
            raise BackupRestoreError("备份包缺少 manifest.json")
        for name in names:
            _safe_rel(name)
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        _validate_manifest(manifest)
        entries = manifest["files"]
        expected = {entry["path"] for entry in entries}
        actual = set(names) - {MANIFEST_NAME}
        if expected != actual:
            raise BackupRestoreError(
                f"备份条目与 manifest 不符（缺 {sorted(expected - actual)}，多 {sorted(actual - expected)}）"
            )
        for entry in entries:
            digest = hashlib.sha256()
            size = 0
            with archive.open(entry["path"]) as handle:
                for chunk in iter(lambda: handle.read(CHUNK), b""):
                    digest.update(chunk)
                    size += len(chunk)
            if size != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
                raise BackupRestoreError(f"备份内容校验失败: {entry['path']}")
    return manifest


@dataclass
class RestorePlan:
    zip_path: Path
    root: Path
    manifest: dict[str, Any]
    targets: list[tuple[str, Path]]
    new: list[tuple[str, int]]
    replace: list[tuple[str, int, int]]
    keep: list[tuple[str, int]]
    sidecars: list[Path]

    @property
    def total_bytes(self) -> int:
        return self.manifest["counts"]["bytes"]


def _collect_keep(root: Path, archived: set[str]) -> list[tuple[str, int]]:
    keep: list[tuple[str, int]] = []
    for name in WHITELIST:
        if name == "jobs.db":
            continue
        top = root / name
        if top.is_symlink() or not top.exists():
            continue
        if top.is_dir():
            for child in sorted(top.rglob("*")):
                if child.is_symlink() or not child.is_file():
                    continue
                rel = child.relative_to(root).as_posix()
                if rel in archived or _is_excluded(PurePosixPath(rel)):
                    continue
                keep.append((rel, child.stat().st_size))
        elif top.is_file() and name not in archived:
            keep.append((name, top.stat().st_size))
    return keep


def plan_restore(
    zip_path: Path | str,
    *,
    root: Path | str | None = None,
    live: bool = False,
) -> RestorePlan:
    archive_path = Path(zip_path).expanduser().resolve()
    manifest = _load_archive(archive_path)
    target_root = _resolve_root(root, live, must_exist=False)
    resolved_root = target_root.resolve()

    targets: list[tuple[str, Path]] = []
    new: list[tuple[str, int]] = []
    replace: list[tuple[str, int, int]] = []
    for entry in manifest["files"]:
        rel = entry["path"]
        target = resolved_root / PurePosixPath(rel)
        if not target.resolve().is_relative_to(resolved_root):
            raise BackupRestoreError(f"备份条目越出目标目录: {rel}")
        targets.append((rel, target))
        if target.exists():
            replace.append((rel, target.stat().st_size, entry["bytes"]))
        else:
            new.append((rel, entry["bytes"]))

    sidecars = [
        resolved_root / f"jobs.db{suffix}"
        for suffix in SIDECAR_SUFFIXES
        if (resolved_root / f"jobs.db{suffix}").exists()
    ]
    keep = _collect_keep(resolved_root, {entry["path"] for entry in manifest["files"]})
    return RestorePlan(
        zip_path=archive_path,
        root=resolved_root,
        manifest=manifest,
        targets=targets,
        new=new,
        replace=replace,
        keep=keep,
        sidecars=sidecars,
    )


def _probe_replaceable(path: Path) -> None:
    probe = path.with_name(f"{path.name}.p6probe-{uuid.uuid4().hex[:8]}")
    try:
        os.replace(path, probe)
    except OSError as exc:
        raise BackupRestoreError(
            f"{path.name} 仍被占用：后端仍在运行，先停止 8600/8501 再还原（{exc.__class__.__name__}）"
        ) from exc
    try:
        os.replace(probe, path)
    except OSError as exc:
        raise BackupRestoreError(f"探测后无法还原 {path.name}: {exc}") from exc


def apply_restore(plan: RestorePlan) -> dict[str, Any]:
    for _rel, target in plan.targets:
        if target.exists():
            _probe_replaceable(target)
    for sidecar in plan.sidecars:
        _probe_replaceable(sidecar)

    plan.root.mkdir(parents=True, exist_ok=True)

    existing = [target for _rel, target in plan.targets if target.exists()]
    pre_restore: Path | None = None
    if existing or plan.sidecars:
        pre_restore = _unique_dir(plan.root, f"pre-restore-{_stamp()}")
        pre_restore.mkdir()
        for sidecar in plan.sidecars:
            shutil.move(str(sidecar), str(pre_restore / sidecar.name))
        for rel, target in plan.targets:
            if not target.exists():
                continue
            dest = pre_restore / PurePosixPath(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(dest))

    temp_dir = Path(tempfile.mkdtemp(prefix=".p6-restore-", dir=str(plan.root.parent)))
    try:
        with zipfile.ZipFile(plan.zip_path) as archive:
            for rel, _target in plan.targets:
                source = temp_dir / PurePosixPath(rel)
                source.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(rel) as src, source.open("wb") as dst:
                    shutil.copyfileobj(src, dst, CHUNK)
        for rel, target in plan.targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_dir / PurePosixPath(rel), target)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    mismatches: list[str] = []
    for entry in plan.manifest["files"]:
        digest, size = _sha256_file(plan.root / PurePosixPath(entry["path"]))
        if digest != entry["sha256"] or size != entry["bytes"]:
            mismatches.append(entry["path"])
    if mismatches:
        raise BackupRestoreError(
            f"还原后校验失败: {', '.join(mismatches[:5])}；旧文件保留在 {pre_restore}"
        )

    return {
        "applied": True,
        "verified": True,
        "root": str(plan.root),
        "new": [rel for rel, _bytes in plan.new],
        "replace": [rel for rel, _old, _new in plan.replace],
        "keep": [rel for rel, _bytes in plan.keep],
        "sidecars": [path.name for path in plan.sidecars],
        "pre_restore": str(pre_restore) if pre_restore else None,
        "bytes": plan.total_bytes,
    }


def restore(
    zip_path: Path | str,
    *,
    root: Path | str | None = None,
    apply: bool = False,
    live: bool = False,
) -> dict[str, Any]:
    plan = plan_restore(zip_path, root=root, live=live)
    if not apply:
        return {
            "applied": False,
            "verified": False,
            "root": str(plan.root),
            "new": [rel for rel, _bytes in plan.new],
            "replace": [rel for rel, _old, _new in plan.replace],
            "keep": [rel for rel, _bytes in plan.keep],
            "sidecars": [path.name for path in plan.sidecars],
            "pre_restore": None,
            "bytes": plan.total_bytes,
        }
    return apply_restore(plan)


def _print_plan(plan: RestorePlan) -> None:
    for rel, size in plan.new:
        print(f"[plan] new     {rel} ({size} B)", flush=True)
    for rel, old_size, new_size in plan.replace:
        print(f"[plan] replace {rel} ({old_size} B -> {new_size} B)", flush=True)
    for rel, size in plan.keep:
        print(f"[plan] keep    {rel} ({size} B，备份中无此项，保持原样)", flush=True)
    for sidecar in plan.sidecars:
        print(f"[plan] setaside {sidecar.name}（移入 pre-restore，不回放）", flush=True)
    print(
        f"[plan] 新增 {len(plan.new)} / 覆盖 {len(plan.replace)} / 保留 {len(plan.keep)}；"
        f"写入 {plan.total_bytes} B",
        flush=True,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="P6-03 白名单备份与恢复（restore 默认 dry-run）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    backup_parser = sub.add_parser("backup", help="导出 jobs.db 快照并打包白名单")
    backup_parser.add_argument("--root", help="数据根，默认取 jobs.db 所在目录")
    backup_parser.add_argument("--db", help="jobs.db 路径，默认 <root>/jobs.db")
    backup_parser.add_argument("--out", help="zip 输出路径，默认 ~/tradingagents-backups/backup-<时间戳>.zip")
    backup_parser.add_argument("--live", action="store_true", help="允许操作真实数据根 ~/.tradingagents")

    restore_parser = sub.add_parser("restore", help="校验并还原备份包")
    restore_parser.add_argument("archive", help="backup 产出的 zip")
    restore_parser.add_argument("--root", help="还原目标数据根，默认 ~/.tradingagents")
    restore_parser.add_argument("--apply", action="store_true", help="真正写入；缺省只打印差异")
    restore_parser.add_argument("--live", action="store_true", help="允许操作真实数据根 ~/.tradingagents")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "backup":
            backup(args.root, db=args.db, out=args.out, live=args.live)
            return 0
        plan = plan_restore(args.archive, root=args.root, live=args.live)
        _print_plan(plan)
        if not args.apply:
            print("[restore] dry-run：未写入任何文件；确认后加 --apply 执行", flush=True)
            return 0
        result = apply_restore(plan)
        if result["pre_restore"]:
            print(f"[apply] 旧文件保留在: {result['pre_restore']}", flush=True)
        print(
            f"[apply] 已还原 {len(plan.targets)} 个文件，复核哈希一致；"
            f"写入 {result['bytes']} B",
            flush=True,
        )
        print(f"[OK] {plan.root}", flush=True)
        return 0
    except BackupRestoreError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
