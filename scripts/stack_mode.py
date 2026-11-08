"""P6-06 双栈开关（D7）：写 .env.stack、端口互锁、切回后校验后端。

    .venv/Scripts/python.exe scripts/stack_mode.py status
    .venv/Scripts/python.exe scripts/stack_mode.py set next
    .venv/Scripts/python.exe scripts/stack_mode.py set legacy

仓库根的 ``.env.stack`` 只有一行 ``ACTIVE_ANALYSIS_UI=legacy|next``，不入库：
切模式不该弄脏工作区，文件缺失时按 legacy 处理，与后端默认一致。

只有端口能拦住第二个写入者：旧版 Streamlit 直写 ``~/.tradingagents``，后端拦不住。
所以 ``set next`` 在 8501 有监听时拒绝且不写文件；本脚本从不启停 8501。

``set legacy`` 会重启正在运行的后端（8600），然后要求
``GET /api/v1/meta/options`` 报 ``write_mode == "legacy"``；不符即报错退出。
重启失败时不回滚文件：留在 legacy 比回到双写安全，由操作者处理。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.write_mode import (  # noqa: E402
    DEFAULT_WRITE_MODE,
    WRITE_MODE_ENV,
    WRITE_MODES,
    parse_write_mode,
)

STACK_FILE = ROOT / ".env.stack"
LEGACY_PORT = 8501
BACKEND_PORT = 8600
BACKEND_ENTRY = ROOT / "scripts" / "run_backend.py"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
API_VERSION = "api-v1"
META_PATH = "/api/v1/meta/options"


class StackError(RuntimeError):
    """可预期的失败：打印后以非零码退出，不留下半截状态。"""


# --- .env.stack ------------------------------------------------------------


def env_path() -> Path:
    return STACK_FILE


def read_mode(path: Path | None = None) -> str:
    """Missing file means legacy; a present file must name the key once."""
    path = path or env_path()
    if not path.exists():
        return DEFAULT_WRITE_MODE
    seen: str | None = None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep and key.strip() == WRITE_MODE_ENV:
            seen = value
    if seen is None:
        raise StackError(f"{path} 缺少 {WRITE_MODE_ENV}= 行")
    try:
        return parse_write_mode(seen)
    except ValueError as exc:
        raise StackError(f"{path}: {exc}") from exc


def write_mode_file(mode: str, path: Path | None = None) -> Path:
    target = parse_write_mode(mode)  # ValueError: callers refuse before writing
    path = path or env_path()
    path.write_text(f"{WRITE_MODE_ENV}={target}\n", encoding="utf-8")
    return path


# --- 端口与后端探针 --------------------------------------------------------


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def listener_pid(port: int) -> int | None:
    """Windows: first LISTENING pid on the port, None elsewhere or not found."""
    if os.name != "nt":
        return None
    out = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        errors="replace",
    ).stdout
    for line in out.splitlines():
        parts = line.split()
        if (
            len(parts) >= 5
            and parts[0] == "TCP"
            and parts[1].endswith(f":{port}")
            and parts[3] == "LISTENING"
        ):
            return int(parts[4])
    return None


def fetch_meta(port: int = BACKEND_PORT, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{META_PATH}", timeout=timeout
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def process_command(pid: int) -> str | None:
    """Windows command line of a pid; None elsewhere or unreadable."""
    if os.name != "nt":
        return None
    out = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' "
            "| Select-Object -ExpandProperty CommandLine",
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=20,
    )
    return out.stdout.strip() or None


def is_owned_backend(command_line: str | None) -> bool:
    """Only run_backend.py may be stopped; dev_backend.py is the dev bat."""
    if not command_line:
        return False
    return "run_backend.py" in command_line.replace("\\", "/")


# --- 决策与状态（纯函数，测试注入输入） ------------------------------------


@dataclass(frozen=True)
class ChangePlan:
    mode: str
    restart_backend: bool


def plan_change(
    mode: str, *, legacy_listening: bool, backend_listening: bool
) -> ChangePlan:
    try:
        target = parse_write_mode(mode)
    except ValueError as exc:
        raise StackError(str(exc)) from exc
    if target == "next" and legacy_listening:
        raise StackError(
            f"{LEGACY_PORT} 仍在监听：旧版还在写 ~/.tradingagents，"
            "先停旧版再切 next"
        )
    return ChangePlan(mode=target, restart_backend=backend_listening)


@dataclass(frozen=True)
class Status:
    mode: str
    legacy_listening: bool
    backend_listening: bool
    backend_write_mode: str | None
    reason: str

    @property
    def consistent(self) -> bool:
        return not self.reason


def evaluate_status(
    mode: str,
    *,
    legacy_listening: bool,
    backend_listening: bool,
    backend_meta: dict | None,
) -> Status:
    if not backend_listening:
        return Status(mode, legacy_listening, False, None, "")
    if backend_meta is None:
        return Status(
            mode,
            legacy_listening,
            True,
            None,
            f"{BACKEND_PORT} 在监听但 {META_PATH} 无响应；不是本服务或未就绪",
        )
    reported = backend_meta.get("write_mode")
    if reported != mode:
        return Status(
            mode,
            legacy_listening,
            True,
            reported,
            f".env.stack={mode}，后端仍报 write_mode={reported}；先重启后端",
        )
    return Status(mode, legacy_listening, True, reported, "")


def status_lines(status: Status) -> list[str]:
    legacy = "listening" if status.legacy_listening else "closed"
    if not status.backend_listening:
        backend = "closed"
    elif status.backend_write_mode is None:
        backend = "listening, meta/options 无响应"
    else:
        backend = f"listening, write_mode={status.backend_write_mode}"
    verdict = "consistent" if status.consistent else f"mismatch: {status.reason}"
    return [
        f"stack mode  : {status.mode}  ({env_path().name})",
        f"legacy {LEGACY_PORT} : {legacy}",
        f"backend {BACKEND_PORT}: {backend}",
        f"verdict     : {verdict}",
    ]


# --- 后端重启 --------------------------------------------------------------


def backend_command(real_models: bool = False, python: Path | None = None) -> list[str]:
    py = Path(python) if python else VENV_PY
    if not py.exists():
        py = Path(sys.executable)
    cmd = [str(py), str(BACKEND_ENTRY)]
    if real_models:
        cmd.append("--real-models")
    return cmd


def log_path(mode: str) -> Path:
    directory = Path(tempfile.gettempdir()) / "astock-stack"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"backend-{mode}.log"


def require_owned_backend(port: int = BACKEND_PORT, *, pid_lookup=None, command_lookup=None) -> int:
    """Refuse to touch a listener that is not scripts/run_backend.py."""
    pid = (pid_lookup or listener_pid)(port)
    if pid is None:
        raise StackError(f"找不到 {port} 的监听进程")
    command = (command_lookup or process_command)(pid)
    if not is_owned_backend(command):
        raise StackError(
            f"{port} 上不是 scripts/run_backend.py（{command or '命令行不可读'}），"
            "拒绝结束；先关掉该入口（如 AStock-UI-dev.bat）"
        )
    return pid


def stop_backend(port: int = BACKEND_PORT, wait: float = 25.0) -> None:
    """Kill whatever is listening on the backend port, but only if it is ours."""
    meta = fetch_meta(port)
    if meta is None:
        raise StackError(
            f"{port} 在监听但读不到 {META_PATH}，拒绝结束未知进程"
        )
    if meta.get("contract_version") != API_VERSION:
        raise StackError(
            f"{port} 上的服务 contract_version={meta.get('contract_version')!r}，"
            f"不是 {API_VERSION}，拒绝结束"
        )
    pid = require_owned_backend(port)
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        check=False,
    )
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not port_open(port):
            return
        time.sleep(0.2)
    raise StackError(f"{port} 在 {wait:.0f}s 内没有释放")


def start_backend(
    mode: str,
    *,
    real_models: bool = False,
    port: int = BACKEND_PORT,
    wait: float = 90.0,
) -> dict:
    target = parse_write_mode(mode)
    env = dict(os.environ)
    env[WRITE_MODE_ENV] = target
    log = log_path(target)
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    with open(log, "ab") as handle:
        proc = subprocess.Popen(
            backend_command(real_models),
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise StackError(f"后端启动即退出（码 {proc.returncode}），日志 {log}")
        meta = fetch_meta(port)
        if meta is not None and meta.get("write_mode") == target:
            return meta
        time.sleep(0.5)
    raise StackError(f"后端 {wait:.0f}s 内未报 write_mode={target}，日志 {log}")


# --- CLI -------------------------------------------------------------------


def _cmd_set(args: argparse.Namespace) -> int:
    path = env_path()
    legacy_up = port_open(LEGACY_PORT)
    backend_up = port_open(BACKEND_PORT)
    plan = plan_change(
        args.mode, legacy_listening=legacy_up, backend_listening=backend_up
    )
    if plan.restart_backend:
        require_owned_backend()  # refuse before writing, not after
    write_mode_file(plan.mode, path)
    print(f"written {path}: {WRITE_MODE_ENV}={plan.mode}")

    if plan.mode == "legacy" and not legacy_up:
        print(f"[warn] {LEGACY_PORT} 未监听：legacy 下没有入口能发起分析")
    if not plan.restart_backend:
        print(f"backend {BACKEND_PORT} not running; start it and run status")
        return 0

    stop_backend()
    meta = start_backend(plan.mode, real_models=args.real_models)
    reported = meta.get("write_mode")
    if reported != plan.mode:
        raise StackError(
            f"重启后 {META_PATH} 报 write_mode={reported!r}，应为 {plan.mode!r}"
        )
    print(f"backend restarted: {META_PATH} write_mode={reported}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    mode = read_mode()
    legacy_up = port_open(LEGACY_PORT)
    backend_up = port_open(BACKEND_PORT)
    meta = fetch_meta(BACKEND_PORT) if backend_up else None
    status = evaluate_status(
        mode,
        legacy_listening=legacy_up,
        backend_listening=backend_up,
        backend_meta=meta,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "mode": status.mode,
                    "legacy_listening": status.legacy_listening,
                    "backend_listening": status.backend_listening,
                    "backend_write_mode": status.backend_write_mode,
                    "consistent": status.consistent,
                    "reason": status.reason,
                },
                ensure_ascii=False,
            )
        )
    else:
        for line in status_lines(status):
            print(line)
    return 0 if status.consistent else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P6-06 双栈开关")
    sub = parser.add_subparsers(dest="command", required=True)
    status_parser = sub.add_parser("status", help="打印模式与 8501/8600 监听")
    status_parser.add_argument("--json", action="store_true")
    set_parser = sub.add_parser("set", help="写 .env.stack（next 前查 8501）")
    set_parser.add_argument("mode", choices=WRITE_MODES)
    set_parser.add_argument(
        "--real-models",
        action="store_true",
        help="重启后端时带上 --real-models（仍需 TA_ENABLE_REAL_RUNNER=1）",
    )
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        if args.command == "status":
            return _cmd_status(args)
        return _cmd_set(args)
    except StackError as exc:
        print(f"[stack] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
