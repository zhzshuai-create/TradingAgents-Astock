"""P6-06 启动入口（D7）：读 .env.stack，起旧版或新版。

    python scripts\\stack_launch.py              # run_all.bat 转调这里
    python scripts\\stack_launch.py --dry-run    # 只打印将执行的命令

legacy：``web/launch.py --with-journal``（8501，日志 8502），与本次改动前
run_all.bat 的命令一致；不读后端、不读 SQLite。解释器优先取 .venv——本机系统
python 3.12 没有 streamlit，双击 run_all.bat（未激活 venv）原先起不来。
``--no-journal`` 只给演练用，避免动 trade-journal 的 8502。
next：``scripts/run_backend.py``（8600），用 .venv 解释器，子进程环境里写入
``ACTIVE_ANALYSIS_UI=next``，让 meta/options 与 409 判据同源。

两条分支都拒绝自相矛盾的启动：next 在 8501 有监听时拒绝（旧版直写数据目录），
legacy 在 8600 仍报 write_mode=next 时拒绝（会变成双写）。
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for entry in (str(ROOT), str(SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import stack_mode  # noqa: E402
from backend.app.core.write_mode import WRITE_MODE_ENV, parse_write_mode  # noqa: E402

LEGACY_SCRIPT = ROOT / "web" / "launch.py"
BACKEND_SCRIPT = ROOT / "scripts" / "run_backend.py"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"


def project_python() -> Path:
    """The venv has streamlit; the system 3.12 on this machine does not."""
    return VENV_PY if VENV_PY.exists() else Path(sys.executable)


def legacy_command(
    python: str | Path | None = None, *, with_journal: bool = True
) -> list[str]:
    interpreter = str(python) if python else str(project_python())
    command = [interpreter, str(LEGACY_SCRIPT)]
    if with_journal:
        command.append("--with-journal")
    return command


def backend_command(
    *, real_models: bool = False, venv_python: str | Path | None = None
) -> list[str]:
    interpreter = Path(venv_python) if venv_python else VENV_PY
    if not interpreter.exists():
        interpreter = Path(sys.executable)
    command = [str(interpreter), str(BACKEND_SCRIPT)]
    if real_models:
        command.append("--real-models")
    return command


def build_command(
    mode: str,
    *,
    python: str | Path | None = None,
    venv_python: str | Path | None = None,
    real_models: bool = False,
    with_journal: bool = True,
) -> list[str]:
    target = parse_write_mode(mode)
    if target == "legacy":
        return legacy_command(python, with_journal=with_journal)
    return backend_command(real_models=real_models, venv_python=venv_python)


def child_env(mode: str, environ: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    if parse_write_mode(mode) == "next":
        env[WRITE_MODE_ENV] = "next"
    return env


def check_guards(
    mode: str,
    *,
    legacy_listening: bool,
    backend_listening: bool,
    backend_meta: dict | None,
) -> None:
    if mode == "next" and legacy_listening:
        raise stack_mode.StackError(
            f"legacy 仍在 {stack_mode.LEGACY_PORT} 监听；先停旧版再启 next"
        )
    if mode == "next" and backend_listening:
        raise stack_mode.StackError(
            f"{stack_mode.BACKEND_PORT} 已被占用（可能是 AStock-UI-dev.bat）；"
            "先关掉再启 next"
        )
    if (
        mode == "legacy"
        and backend_meta is not None
        and backend_meta.get("write_mode") == "next"
    ):
        raise stack_mode.StackError(
            f"后端 {stack_mode.BACKEND_PORT} 仍以 next 运行"
            "（可能是 AStock-UI-dev.bat）；先关掉它再启 legacy"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P6-06 双栈启动入口")
    parser.add_argument("--dry-run", action="store_true", help="只打印命令")
    parser.add_argument(
        "--real-models",
        action="store_true",
        help="next 下透传 --real-models（仍需 TA_ENABLE_REAL_RUNNER=1）",
    )
    parser.add_argument(
        "--no-journal",
        action="store_true",
        help="legacy 下不拉起 8502 交易日志（默认拉起，与 run_all.bat 一致）",
    )
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        mode = stack_mode.read_mode()
        legacy_up = stack_mode.port_open(stack_mode.LEGACY_PORT)
        backend_up = stack_mode.port_open(stack_mode.BACKEND_PORT)
        backend_meta = (
            stack_mode.fetch_meta(stack_mode.BACKEND_PORT) if backend_up else None
        )
        check_guards(
            mode,
            legacy_listening=legacy_up,
            backend_listening=backend_up,
            backend_meta=backend_meta,
        )
    except stack_mode.StackError as exc:
        print(f"[stack] {exc}", file=sys.stderr)
        return 1

    command = build_command(
        mode, real_models=args.real_models, with_journal=not args.no_journal
    )
    print(f"[stack] {stack_mode.env_path().name}: {WRITE_MODE_ENV}={mode}")
    print(f"[stack] {shlex.join(command)}")
    if args.dry_run:
        return 0
    try:
        return subprocess.call(command, cwd=str(ROOT), env=child_env(mode))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
