"""P0 收工预检：只读核对进度存档里的关键声明。

    .venv/Scripts/python.exe scripts/p0_preflight.py
    .venv/Scripts/python.exe scripts/p0_preflight.py --full --smoke

默认跑结构、冻结哈希、文档、回滚点、假图 S00 与 8 条 CT 测试，约 10 秒。
--full 追加全量 pytest（约 51 秒），并核对测试数不低于 372、跳过仍为 4。
--smoke 临时在 8599 端口启动旧版 Streamlit，健康检查通过后关闭。

脚本不改仓库文件。任一项 FAIL 时退出码为 1。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "upgrade"
CONTRACTS = DOCS / "contracts"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

EXPECTED_TESTS = {"passed": 372, "skipped": 4}
EXPECTED_CT_PASSED = 8
EXPECTED_DOCS = 20
EXPECTED_CONTRACTS = 15
EXPECTED_BACKLOG_TASKS = 13
GOLDEN_HASH = "869ee791c7c3af089050e7734aa0605d6f37efddeac0dc1066f978b87f3a6202"
S00 = {
    "scenario": "S00",
    "status": "succeeded",
    "stages_done": 12,
    "events": 40,
    "model_calls": 14,
    "tokens_in": 182430,
    "tokens_out": 41208,
    "report_written": True,
    "report_committed": True,
}
CONDITIONS = [
    "旧版可恢复",
    "契约没有关键空白",
    "黄金样本可用",
    "假图可用",
    "主流程线框已走查",
    "P1 任务可以独立验收",
    "真实模型默认禁用",
]

results: list[tuple[str, str, str]] = []


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def record(name: str, status: str, detail: str) -> None:
    results.append((name, status, detail))


def check(name: str):
    def wrap(fn):
        def runner():
            try:
                detail = fn()
                record(name, "PASS", detail or "")
            except AssertionError as exc:
                record(name, "FAIL", str(exc))
            except Exception as exc:  # noqa: BLE001 - report, do not crash
                record(name, "FAIL", f"{type(exc).__name__}: {exc}")

        return runner

    return wrap


def git(*args: str) -> str:
    out = run(["git", *args], timeout=30)
    assert out.returncode == 0, f"git {' '.join(args)} failed: {out.stderr.strip()}"
    return out.stdout.strip()


@check("仓库与提交")
def check_git() -> str:
    head = git("rev-parse", "--short", "HEAD")
    status = git("status", "--porcelain")
    assert not status, f"工作区不干净：\n{status[:800]}"
    archive = read(DOCS / "进度存档.md")
    ids = sorted(set(re.findall(r"`([0-9a-f]{7})`", archive)))
    assert ids, "存档里没有提交号"
    missing = []
    for sha in ids:
        out = run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], timeout=15)
        if out.returncode != 0:
            missing.append(sha)
    assert not missing, f"存档里的提交号不存在：{missing}"
    return f"HEAD {head}，工作区干净，{len(ids)} 个存档提交号都在历史里"


@check("契约冻结哈希")
def check_freeze() -> str:
    manifest = read(CONTRACTS / "FREEZE-v1.md")
    rows = re.findall(
        r"^\|\s*`([\w.-]+\.(?:md|json))`\s*\|\s*`([0-9a-f]{64})`\s*\|",
        manifest,
        re.M,
    )
    assert len(rows) == EXPECTED_CONTRACTS, f"冻结清单 {len(rows)} 行，应为 {EXPECTED_CONTRACTS}"
    bad = []
    for name, digest in rows:
        actual = hashlib.sha256((CONTRACTS / name).read_bytes()).hexdigest()
        if actual != digest:
            bad.append(name)
    assert not bad, f"哈希不匹配：{bad}"
    mds = [p for p in CONTRACTS.glob("*.md") if p.name != "FREEZE-v1.md"]
    no_version = [p.name for p in mds if "版本：v1" not in read(p)]
    assert not no_version, f"缺版本行：{no_version}"
    return f"{EXPECTED_CONTRACTS} 份哈希一致，{len(mds)} 份 md 带 v1 版本行"


@check("报告黄金样本")
def check_samples() -> str:
    fixtures = ROOT / "tests" / "fixtures" / "upgrade"
    expected = [
        "final_state_v1.json",
        "missing_fields_report.json",
        "long_report.json",
        "unsafe_text_report.json",
        "legacy_report_v1.json",
        "market_ok.json",
        "market_empty.json",
        "market_error.json",
        "market_stale.json",
        "market_partial.json",
    ]
    missing = [n for n in expected if not (fixtures / n).exists()]
    assert not missing, f"缺样本：{missing}"
    sample = json.loads(read(fixtures / "final_state_v1.json"))
    payload = json.dumps(
        sample["sections"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    actual = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert actual == GOLDEN_HASH, f"黄金哈希 {actual} 与预期不符"
    assert sample["meta"]["content_hash"] == GOLDEN_HASH
    return "10 份样本齐全，黄金哈希重算一致"


@check("出口评审与拆票")
def check_review_backlog() -> str:
    review = read(DOCS / "p0-exit-review.md")
    assert "结论：Go" in review, "出口评审没有 Go 结论"
    missing = [name for name in CONDITIONS if name not in review]
    assert not missing, f"出口评审缺条件：{missing}"
    backlog = read(DOCS / "p1-backlog.md")
    tasks = re.findall(r"^### P1-(\d{2}) ", backlog, re.M)
    assert len(tasks) == EXPECTED_BACKLOG_TASKS, f"P1 任务 {len(tasks)} 个，应为 {EXPECTED_BACKLOG_TASKS}"
    archive = read(DOCS / "进度存档.md")
    assert "明日开工卡" in archive, "进度存档缺明日开工卡"
    assert "p0_preflight.py" in archive, "进度存档没写预检命令"
    return f"Go 结论、{len(CONDITIONS)} 条硬条件、{len(tasks)} 个 P1 任务均在文件里"


@check("阅读版与线框")
def check_html() -> str:
    reading = docs_reading_html()
    raw = reading.read_bytes()
    h1 = len(re.findall(rb"<h1[ >]", raw))
    assert h1 == EXPECTED_DOCS, f"阅读版 h1 {h1}，应为 {EXPECTED_DOCS}"
    assert not re.search(rb"<em[ >]", raw), "阅读版出现 em 标签"
    assert b"\x0c" not in raw, "阅读版含 0x0C 控制字符"
    assert b"{content}" not in raw and b"{toc}" not in raw, "阅读版有占位符残留"
    assert "契约冻结清单 v1".encode() in raw
    assert "P1 任务拆票".encode() in raw
    for name in ("core-wireframes-desktop.html", "core-wireframes-mobile.html"):
        wire = read(DOCS / "wireframes" / name)
        assert "任务不存在" not in wire, f"{name} 仍含禁用词"
        assert "任务 ID 无效（404）" in wire, f"{name} 缺 404 文案"
    return f"阅读版 {EXPECTED_DOCS} 份文档，两个线框无禁用词"


def docs_reading_html() -> Path:
    found = list(DOCS.glob("AStock_Pro_P0*阅读版.html"))
    assert len(found) == 1, f"阅读版文件数量异常：{found}"
    return found[0]


@check("回滚点")
def check_rollback() -> str:
    tag = git("tag", "--list", "pre-upgrade-p0-20261028")
    assert tag, "回滚 tag 不存在"
    bundle = Path(r"C:\Users\zhzsh\astock-pre-upgrade-p0-20261028.bundle")
    assert bundle.exists(), f"bundle 不存在：{bundle}"
    assert bundle.stat().st_size > 1_000_000, "bundle 小于 1MB"
    backup = Path(r"C:\Users\zhzsh\tradingagents-data-backup-20261028-pre-upgrade-p0")
    assert backup.is_dir(), f"数据备份目录不存在：{backup}"
    count = sum(1 for p in backup.rglob("*") if p.is_file())
    assert count > 0, "数据备份目录为空"
    return f"tag {tag}，bundle {bundle.stat().st_size // 1024} KiB，备份 {count} 个文件"


@check("假图 S00")
def check_fake_s00() -> str:
    assert VENV_PY.exists(), f"虚拟环境解释器不存在：{VENV_PY}"
    out = run([str(VENV_PY), "tests/fake_analysis_graph.py", "--scenario", "S00", "--json"], timeout=60)
    assert out.returncode == 0, f"假图退出码 {out.returncode}: {out.stderr[-500:]}"
    summary = json.loads(out.stdout)
    bad = {k: (summary.get(k), v) for k, v in S00.items() if summary.get(k) != v}
    assert not bad, f"S00 数字不符：{bad}"
    return "12 阶段、40 事件、14 调用、182430/41208 Token 全部一致"


@check("CT 交叉检查")
def check_ct() -> str:
    out = run(
        [str(VENV_PY), "-m", "pytest", "tests/test_upgrade_contract_consistency.py", "-q"],
        timeout=120,
    )
    assert out.returncode == 0, f"CT 测试失败：{out.stdout[-800:]}"
    passed = preg(out.stdout, r"(\d+) passed")
    assert passed == EXPECTED_CT_PASSED, f"CT 通过 {passed} 条，应为 {EXPECTED_CT_PASSED}"
    return f"{passed} 条 CT 测试通过"


def preg(text: str, pattern: str) -> int:
    match = re.search(pattern, text)
    assert match, f"输出里找不到 {pattern}"
    return int(match.group(1))


@check("全量测试")
def check_full_suite() -> str:
    out = run([str(VENV_PY), "-m", "pytest", "-q"], timeout=600)
    assert out.returncode == 0, f"全量测试失败：{out.stdout[-1200:]}"
    passed = preg(out.stdout, r"(\d+) passed")
    skipped = preg(out.stdout, r"(\d+) skipped")
    assert passed >= EXPECTED_TESTS["passed"], (
        f"通过 {passed}，不应少于 {EXPECTED_TESTS['passed']}"
    )
    assert skipped == EXPECTED_TESTS["skipped"], f"跳过 {skipped}，应为 {EXPECTED_TESTS['skipped']}"
    return f"{passed} passed / {skipped} skipped"


@check("旧版冒烟")
def check_smoke() -> str:
    app = ROOT / "web" / "app.py"
    assert app.exists(), "web/app.py 不存在"
    log = tempfile.TemporaryFile()
    proc = subprocess.Popen(
        [
            str(VENV_PY),
            "-m",
            "streamlit",
            "run",
            str(app),
            "--server.headless",
            "true",
            "--server.port",
            "8599",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    ok = False
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:8599/_stcore/health", timeout=2
                ) as resp:
                    if resp.read().strip() == b"ok":
                        ok = True
                        break
            except Exception:  # noqa: BLE001 - keep polling
                time.sleep(1)
    finally:
        kill_tree(proc)
        log.seek(0)
        tail = log.read()[-800:].decode("utf-8", "replace")
        log.close()
    assert ok, f"旧版健康检查未通过；日志尾部：{tail}"
    return "Streamlit 1.66.0 健康检查 ok，进程已关闭"


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P0 收工预检（只读）")
    parser.add_argument("--full", action="store_true", help="追加全量 pytest")
    parser.add_argument("--smoke", action="store_true", help="追加旧版 Streamlit 冒烟")
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("P0 收工预检")
    print(f"仓库: {ROOT}")
    print(f"HEAD: {git('rev-parse', '--short', 'HEAD')}")
    print()

    basics = [
        check_git,
        check_freeze,
        check_samples,
        check_review_backlog,
        check_html,
        check_rollback,
        check_fake_s00,
        check_ct,
    ]
    for fn in basics:
        fn()
    if args.full:
        check_full_suite()
    if args.smoke:
        check_smoke()

    for name, status, detail in results:
        line = f"[{status}] {name}"
        if detail:
            line += f": {detail}"
        print(line)

    failed = [name for name, status, _ in results if status == "FAIL"]
    print()
    print(f"通过 {len(results) - len(failed)}，失败 {len(failed)}")
    if failed:
        print("结论：不可开工，先核对失败项")
        return 1
    print("结论：可以开工")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
