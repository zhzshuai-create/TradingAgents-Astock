"""P6-06/P6-08 启动入口（D7）：读 .env.stack，起旧版或新版。

    python scripts\\stack_launch.py              # run_all.bat 转调这里
    python scripts\\stack_launch.py --dry-run    # 只打印将执行的命令

legacy：``web/launch.py --with-journal``（8501，日志 8502），与本次改动前
run_all.bat 的命令一致；不读后端、不读 SQLite。解释器优先取 .venv——本机系统
python 3.12 没有 streamlit，双击 run_all.bat（未激活 venv）原先起不来。
``--no-journal`` 只给演练用，避免动 trade-journal 的 8502。
next：三条子进程——``scripts/run_backend.py``（8600）、``vite preview``（5173，
托管已构建的 dist 并把 /api 代理到 8600）、``trade-journal/app.py``（8502）。
后端子进程环境里写入 ``ACTIVE_ANALYSIS_UI=next``，让 meta/options 与 409 判据同源。
后端不托管 SPA：``GET /`` 返回 404 是设计，界面走 5173。

两条分支都拒绝自相矛盾的启动：next 在 8501 有监听时拒绝（旧版直写数据目录），
legacy 在 8600 仍报 write_mode=next 时拒绝（会变成双写）。next 另外拒绝 5173
被占、缺 .venv 解释器与缺前端构建。Ctrl+C 在 finally 里逐个回收子进程。
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
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

PREVIEW_PORT = 5173
JOURNAL_PORT = 8502
FRONTEND_DIR = ROOT / "frontend"
VITE_ENTRY = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
DIST_INDEX = FRONTEND_DIR / "dist" / "index.html"
JOURNAL_DIR = ROOT.parent / "trade-journal"
JOURNAL_APP = JOURNAL_DIR / "app.py"

ADDRESS = {
    "backend": f"http://127.0.0.1:{stack_mode.BACKEND_PORT}",
    "ui": f"http://127.0.0.1:{PREVIEW_PORT}",
    "journal": f"http://127.0.0.1:{JOURNAL_PORT}",
}


@dataclass(frozen=True)
class Step:
    """One child process. ``cwd`` matters: vite and streamlit resolve assets
    relative to their own directories."""

    name: str
    command: list[str]
    cwd: Path


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


def preview_command() -> list[str]:
    # --host 127.0.0.1: without it vite preview binds [::1] only and every
    # 127.0.0.1 probe (status, e2e, the printed address) refuses.
    return [
        "node",
        str(VITE_ENTRY),
        "preview",
        "--port",
        str(PREVIEW_PORT),
        "--host",
        "127.0.0.1",
        "--strictPort",
    ]


def journal_command(venv_python: str | Path | None = None) -> list[str]:
    # web/journal_service.start_journal() uses the caller's sys.executable;
    # run_all.bat is the system 3.12 which lacks streamlit, so name the venv
    # interpreter explicitly instead of importing that helper.
    interpreter = Path(venv_python) if venv_python else VENV_PY
    return [
        str(interpreter),
        "-m",
        "streamlit",
        "run",
        str(JOURNAL_APP),
        "--server.headless",
        "true",
        "--server.port",
        str(JOURNAL_PORT),
    ]


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


def build_plan(
    mode: str,
    *,
    python: str | Path | None = None,
    venv_python: str | Path | None = None,
    real_models: bool = False,
    with_journal: bool = True,
    with_ui: bool = True,
) -> list[Step]:
    target = parse_write_mode(mode)
    if target == "legacy":
        return [
            Step(
                "legacy",
                legacy_command(python, with_journal=with_journal),
                ROOT,
            )
        ]
    steps = [
        Step(
            "backend",
            backend_command(real_models=real_models, venv_python=venv_python),
            ROOT,
        )
    ]
    if with_ui:
        steps.append(Step("ui", preview_command(), FRONTEND_DIR))
    if with_journal and JOURNAL_APP.is_file():
        steps.append(Step("journal", journal_command(venv_python), JOURNAL_DIR))
    return steps


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
    preview_listening: bool = False,
    venv_python: Path | str | None = None,
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
    if mode == "next" and preview_listening:
        raise stack_mode.StackError(
            f"{PREVIEW_PORT} 已被占用（开发服务器或上次残留的预览）；"
            "先关掉再启 next，不要复用或杀未知进程"
        )
    if mode == "next" and venv_python is not None and not Path(venv_python).exists():
        raise stack_mode.StackError(
            f"{venv_python} 不存在：系统 Python 3.12 没有 uvicorn / streamlit，"
            "后端与日志都必须用 .venv 解释器"
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


def require_ui() -> None:
    if not VITE_ENTRY.is_file() or not DIST_INDEX.is_file():
        raise stack_mode.StackError(
            "前端未构建：先执行 cd frontend && npm run build"
        )


def stale_ui_warning() -> str | None:
    """The preview serves a build, not sources; a stale dist looks like a bug."""
    if not DIST_INDEX.exists():
        return None
    built = DIST_INDEX.stat().st_mtime
    newest = max(
        (
            path.stat().st_mtime
            for path in (FRONTEND_DIR / "src").rglob("*")
            if path.is_file()
        ),
        default=0.0,
    )
    if newest > built:
        return (
            "[stack] 警告: frontend/src 比 frontend/dist 新，预览的是旧构建；"
            "先 cd frontend && npm run build"
        )
    return None


def stop_all(procs: list[tuple[Step, subprocess.Popen]], wait: float = 10.0) -> None:
    for _step, proc in procs:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.monotonic() + wait
    for _step, proc in procs:
        try:
            proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()


def run_plan(plan: list[Step], env: dict[str, str]) -> int:
    procs: list[tuple[Step, subprocess.Popen]] = []
    try:
        for step in plan:
            procs.append(
                (
                    step,
                    subprocess.Popen(
                        step.command,
                        cwd=str(step.cwd),
                        env=env,
                        stdin=subprocess.DEVNULL,
                    ),
                )
            )
        for step, _proc in procs:
            print(f"[stack] {step.name:<7} {ADDRESS[step.name]}", flush=True)
        print("[stack] Ctrl+C 结束全部子进程", flush=True)
        while True:
            for step, proc in procs:
                code = proc.poll()
                if code is not None:
                    print(
                        f"[stack] {step.name} 退出（码 {code}），停止其余子进程",
                        file=sys.stderr,
                        flush=True,
                    )
                    return code or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("[stack] 收到 Ctrl+C，停止子进程...", flush=True)
        return 130
    finally:
        stop_all(procs)


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
        help="不拉起 8502 交易日志（legacy 与 next 都生效）",
    )
    parser.add_argument(
        "--no-ui",
        action="store_true",
        help="next 下只起后端，不起 5173 预览",
    )
    parser.add_argument(
        "--build-ui",
        action="store_true",
        help="next 起预览前先 vite build（默认用已有 dist）",
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
            preview_listening=stack_mode.port_open(PREVIEW_PORT),
            venv_python=VENV_PY if mode == "next" else None,
        )
        if mode == "next" and not args.no_ui:
            # --build-ui produces the dist, so only the toolchain is required then.
            if args.build_ui:
                if not VITE_ENTRY.is_file():
                    raise stack_mode.StackError(
                        "前端依赖缺失：先在 frontend 里执行 npm install"
                    )
            else:
                require_ui()
    except stack_mode.StackError as exc:
        print(f"[stack] {exc}", file=sys.stderr)
        return 1

    print(f"[stack] {stack_mode.env_path().name}: {WRITE_MODE_ENV}={mode}")
    if mode == "next" and not args.no_ui and not args.build_ui:
        warning = stale_ui_warning()
        if warning:
            print(warning)

    if mode == "next" and args.build_ui:
        build = subprocess.call(
            ["node", str(VITE_ENTRY), "build"], cwd=str(FRONTEND_DIR)
        )
        if build != 0:
            print(f"[stack] 前端构建失败（码 {build}）", file=sys.stderr)
            return 1

    plan = build_plan(
        mode,
        real_models=args.real_models,
        with_journal=not args.no_journal,
        with_ui=not args.no_ui,
    )
    for step in plan:
        print(f"[stack] {step.name}: {shlex.join(step.command)}")
    if (
        mode == "next"
        and not args.no_journal
        and not any(step.name == "journal" for step in plan)
    ):
        print(
            f"[stack] 交易日志未安装：{JOURNAL_APP} 不存在，跳过 {JOURNAL_PORT}；"
            "/journal 页有安装/启动引导",
            file=sys.stderr,
        )
    if args.dry_run:
        return 0

    env = child_env(mode)
    if mode == "legacy":
        try:
            return subprocess.call(plan[0].command, cwd=str(plan[0].cwd), env=env)
        except KeyboardInterrupt:
            return 130
    return run_plan(plan, env)


if __name__ == "__main__":
    raise SystemExit(main())
