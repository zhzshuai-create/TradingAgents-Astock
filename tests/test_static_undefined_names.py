"""F821(未定义名)静态守卫 — 保护导入重排不漏掉任何一个名字.

为什么需要静态检查而不是只靠 AppTest:
实测把 `from web.components.report_viewer import render_report` 整行删掉, 三个模式的
AppTest 冒烟依然全过 —— 因为 render_report 只在"已有分析结果"的分支里调用, 冒烟测试
走不到那里. 这类漏项是静默的, 只有静态分析能在不执行分支的前提下抓到.

本仓库曾因这类问题吃过亏: report_viewer.py 里残留一个未定义的 `icon` 变量, 导致
查看历史分析时被上层 try/except 吞成"加载失败", 分析完成时则直接抛红色 traceback.

ruff 未安装时跳过(它不在项目运行时依赖里).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 第一方代码目录; 第三方与生成物不在范围内
SCAN_DIRS = ("web", "tradingagents", "cli", "tools", "tests")

RUFF = shutil.which("ruff")

pytestmark = pytest.mark.skipif(
    RUFF is None, reason="ruff 未安装, 跳过静态未定义名检查 (pip install ruff)"
)


def test_no_undefined_names():
    """F821 = 用了从未定义/从未导入的名字. 导入重排最容易制造这个."""
    targets = [str(PROJECT_ROOT / d) for d in SCAN_DIRS if (PROJECT_ROOT / d).exists()]
    assert targets, "没找到任何待扫描目录"

    proc = subprocess.run(
        [RUFF, "check", "--select", "F821", "--output-format", "concise", *targets],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    # ruff 通过时也会往 stdout 打 "All checks passed!", 所以只以退出码判定
    violations = "\n".join(
        ln for ln in (proc.stdout or "").splitlines() if ": F821" in ln
    )
    assert proc.returncode == 0 and not violations, (
        "发现未定义名 (F821):\n" + (violations or proc.stdout or proc.stderr) + "\n\n"
        "常见原因: 导入被挪到了使用点之后, 或重排时整行漏掉.\n"
        f"手动复现: ruff check --select F821 {' '.join(SCAN_DIRS)}"
    )


def test_ruff_itself_is_usable():
    """守卫不能因为 ruff 坏了而静默变绿."""
    proc = subprocess.run([RUFF, "--version"], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"ruff 无法执行: {proc.stderr}"
    assert "ruff" in (proc.stdout + proc.stderr).lower()
    sys.stdout.write(f"  [ruff {proc.stdout.strip()}]\n")
