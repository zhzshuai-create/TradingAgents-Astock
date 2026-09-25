"""首屏时序测量工具 — 启动动画项目的验收基础设施.

为什么需要它: 首屏时序依赖机器状态(磁盘暖不暖 / index_spot 网络快不快 / 有无 .pyc),
没有稳定断言可写. 这个工具把"遮罩有没有盖住真实等待"变成可重复的数字.

每次测量都重启一个全新的 streamlit 进程 —— 因为 Python 的 sys.modules 缓存意味着
只有启动后的第一次页面加载才真正付导入成本, 复用进程会量到假的快数字.

用法:
    python tools/measure_boot.py                      # 测 web/app.py, 3 次取中位数
    python tools/measure_boot.py --runs 1 --port 8503
    python tools/measure_boot.py --no-server --port 8501   # 测已在跑的实例
    python tools/measure_boot.py --json baseline.json      # 落盘
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 采样器在页面脚本之前注入, 每 40ms 记一次状态.
# 关注的三个信号:
#   overlay  — 启动遮罩 (#boot-mask) 是否已上屏
#   content  — 首帧真实内容是否出现 (默认 .model-badge, app.py 顶部导航栏)
#   spinner  — Streamlit 自带的 loading 指示是否露出 (露出即为穿帮)
SAMPLER_JS = r"""
window.__bootProbe = { samples: [], t0: Date.now() };
(function () {
  var CONTENT = %CONTENT_SELECTORS%;
  var state = window.__bootProbe;
  function hit(sel) { return !!document.querySelector(sel); }
  var id = setInterval(function () {
    var content = false;
    for (var i = 0; i < CONTENT.length; i++) { if (hit(CONTENT[i])) { content = true; break; } }
    state.samples.push({
      ms: Date.now() - state.t0,
      overlay: !!document.getElementById('boot-mask'),
      content: content,
      spinner: hit('[data-testid="stStatusWidget"], [data-testid="stAppStatusWidget"], [data-testid="stSpinner"], .stSpinner'),
      nodes: document.body ? document.body.childElementCount : 0
    });
    if (Date.now() - state.t0 > %DURATION_MS%) clearInterval(id);
  }, 40);
})();
"""

DEFAULT_CONTENT_SELECTORS = [".model-badge", '[data-testid="stSegmentedControl"]']


def _sampler_js(duration_ms: int, content_selectors: list[str]) -> str:
    return (
        SAMPLER_JS.replace("%DURATION_MS%", str(duration_ms))
        .replace("%CONTENT_SELECTORS%", json.dumps(content_selectors))
    )


def _wait_health(port: int, timeout: float = 60.0) -> float:
    """返回 health 就绪耗时(秒). Streamlit 的 health 在脚本可服务前就 ok, 所以这不是首屏时间."""
    url = f"http://localhost:{port}/_stcore/health"
    t0 = time.perf_counter()
    deadline = t0 + timeout
    while time.perf_counter() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status == 200:
                    return time.perf_counter() - t0
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.2)
    raise TimeoutError(f"health 未在 {timeout}s 内就绪: {url}")


def _summarize(samples: list[dict]) -> dict:
    """把采样序列压成关键时间点. 返回的每个值都是 ms, None 表示全程未出现."""

    def first(pred):
        for s in samples:
            if pred(s):
                return s["ms"]
        return None

    def last(pred):
        out = None
        for s in samples:
            if pred(s):
                out = s["ms"]
        return out

    overlay_first = first(lambda s: s["overlay"])
    content_first = first(lambda s: s["content"])
    spinner_first = first(lambda s: s["spinner"])
    spinner_last = last(lambda s: s["spinner"])

    # spinner 在遮罩上屏之前露出的时长 = 穿帮时长, 这是本项目的核心验收指标
    exposed = None
    if spinner_first is not None:
        end = overlay_first if overlay_first is not None else content_first
        exposed = max(0, (end or spinner_last or spinner_first) - spinner_first)

    return {
        "overlay_first_ms": overlay_first,
        "content_first_ms": content_first,
        "spinner_first_ms": spinner_first,
        "spinner_last_ms": spinner_last,
        "spinner_exposed_ms": exposed,
        "samples": len(samples),
    }


def measure_once(
    port: int,
    app: Path,
    duration_ms: int,
    content_selectors: list[str],
    no_server: bool,
    headless_browser: bool,
) -> dict:
    from playwright.sync_api import sync_playwright

    proc = None
    if not no_server:
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "streamlit", "run", str(app),
                "--server.port", str(port),
                "--server.headless", "true",
                "--browser.gatherUsageStats", "false",
            ],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    try:
        health_s = _wait_health(port)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless_browser)
            page = browser.new_page()
            page.add_init_script(_sampler_js(duration_ms, content_selectors))
            # wait_until="commit" 关键: 不能等 load, 否则采样窗口已经错过首屏
            page.goto(f"http://localhost:{port}/", wait_until="commit", timeout=60000)
            page.wait_for_timeout(duration_ms + 1500)
            samples = page.evaluate("window.__bootProbe.samples")
            browser.close()
        return {"health_ready_s": round(health_s, 2), **_summarize(samples)}
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
            time.sleep(1.0)  # 等端口释放, 否则下一轮起不来


def main() -> int:
    ap = argparse.ArgumentParser(description="测量 Streamlit 首屏时序")
    ap.add_argument("--app", default="web/app.py")
    ap.add_argument("--port", type=int, default=8503)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--duration-ms", type=int, default=15000)
    ap.add_argument("--content-selector", action="append", dest="selectors",
                    help="首帧内容判定选择器, 可重复; 默认 .model-badge 与 stSegmentedControl")
    ap.add_argument("--no-server", action="store_true", help="测已在跑的实例, 不自己起进程")
    ap.add_argument("--headed", action="store_true", help="显示浏览器窗口(调试用)")
    ap.add_argument("--json", type=Path, help="结果落盘路径")
    args = ap.parse_args()

    app = (PROJECT_ROOT / args.app).resolve()
    if not app.exists():
        print(f"[err] 找不到 app: {app}", file=sys.stderr)
        return 2
    selectors = args.selectors or DEFAULT_CONTENT_SELECTORS

    runs = []
    for i in range(args.runs):
        print(f"[{i + 1}/{args.runs}] measuring (port {args.port}) ...", flush=True)
        r = measure_once(args.port, app, args.duration_ms, selectors,
                         args.no_server, not args.headed)
        runs.append(r)
        print("   " + "  ".join(f"{k}={v}" for k, v in r.items() if k != "samples"), flush=True)

    def med(key):
        vals = [r[key] for r in runs if isinstance(r.get(key), (int, float))]
        return round(statistics.median(vals), 1) if vals else None

    try:
        app_label = str(app.relative_to(PROJECT_ROOT))
    except ValueError:
        app_label = str(app)

    summary = {
        "app": app_label,
        "runs": args.runs,
        "median": {
            "health_ready_s": med("health_ready_s"),
            "overlay_first_ms": med("overlay_first_ms"),
            "content_first_ms": med("content_first_ms"),
            "spinner_first_ms": med("spinner_first_ms"),
            "spinner_exposed_ms": med("spinner_exposed_ms"),
        },
        "per_run": runs,
    }

    print("\n=== median ===")
    for k, v in summary["median"].items():
        print(f"  {k:22s} {v}")
    exposed = summary["median"]["spinner_exposed_ms"]
    if exposed is None:
        print("\nverdict: spinner never appeared")
    elif exposed == 0:
        print("\nverdict: spinner exposure 0ms  PASS")
    elif exposed <= 600:
        # 实测下限: Streamlit 自己的 status widget 先于任何脚本渲染的元素上屏,
        # 遮罩无法早于它. 这段是结构性的, 不是 bug.
        print(f"\nverdict: spinner exposure {exposed}ms  PASS (within structural floor)")
    else:
        print(f"\nverdict: spinner exposure {exposed}ms  FAIL (overlay too late)")

    if args.json:
        args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
