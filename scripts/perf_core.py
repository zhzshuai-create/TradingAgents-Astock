"""P6-05 性能门禁：LCP / CLS / INP，三条指标各两条线。

用 ``vite preview`` 提供构建产物，Playwright ``context.route`` 桩住全部接口，
页面内 ``PerformanceObserver`` 采 LCP / CLS，交互后用 Event Timing 采 INP。
两档视口各 ``--samples`` 个样本（默认 20）取 p75；超回归线非零退出。

Playwright 只在浏览器采样路径里惰性导入，``.venv`` 的 pytest 可以导入本模块
测试纯函数，而不需要浏览器包。用法（系统 Python 3.13）::

    py -3.13 scripts/perf_core.py --samples 20
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
MANIFEST = FRONTEND / "dist" / ".vite" / "manifest.json"
REVIEWS = ROOT / "docs" / "upgrade" / "reviews"

TICKET = "P6-05"
TARGET = {"lcp_ms": 2000.0, "cls": 0.05, "inp_ms": 150.0}
REGRESSION = {"lcp_ms": 2500.0, "cls": 0.1, "inp_ms": 200.0}
VIEWPORTS = {
    "mobile": {"width": 390, "height": 844},
    "desktop": {"width": 1440, "height": 900},
}
INTERACTIONS = ("manual_refresh", "market_to_stock", "list_filter")
INTERACTION_DEFS = {
    "manual_refresh": (
        "在 /market 点击 [data-testid=market-refresh]，触发四个市场查询重取。"
    ),
    "market_to_stock": (
        "在 /market 点击强势股链接 a[href^=/stocks/]，客户端路由切到个股页。"
    ),
    "list_filter": (
        "在 /jobs 切换一个状态筛选复选框；移动档先点 "
        "[data-testid=job-filter-open] 打开筛选弹窗。"
    ),
}
MIN_SAMPLES = 20
LOAD_ROUTE = "/market"
SETTLE_MS = 700
INP_SETTLE_MS = 260
# Event Timing 的 durationThreshold 最小为 16ms；更快的交互按此下限记。
INP_FLOOR_MS = 16.0


# --------------------------------------------------------------------------
# 纯函数：分位、判分、证据。样本可注入，测试不依赖浏览器。
# --------------------------------------------------------------------------


def p75(values: Iterable[float]) -> float:
    """nearest-rank p75；空样本报错，由 judge 负责转成失败。"""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("p75 of an empty sample")
    rank = max(1, math.ceil(0.75 * len(ordered)))
    return ordered[rank - 1]


def _round(metric: str, value: float) -> float:
    return round(value, 2) if metric.endswith("_ms") else round(value, 4)


def judge(
    samples: dict[str, dict[str, list[float]]],
    *,
    min_samples: int = MIN_SAMPLES,
    require_interactions: bool = True,
) -> tuple[dict, bool]:
    """samples: {viewport: {metric: [...], "inp_by_interaction": {name: [...]}}}。

    超回归线或样本不足即失败；超目标线只标记 ``warn``，不改变退出码。
    """
    report: dict[str, dict] = {}
    failed = False
    for viewport in VIEWPORTS:
        metrics = samples.get(viewport) or {}
        viewport_report: dict[str, object] = {}
        for metric, regression in REGRESSION.items():
            target = TARGET[metric]
            values = [float(value) for value in (metrics.get(metric) or [])]
            if len(values) < min_samples:
                viewport_report[metric] = {
                    "p75": None,
                    "target": target,
                    "regression": regression,
                    "pass": False,
                    "warn": False,
                    "samples": len(values),
                    "reason": f"samples<{min_samples}",
                }
                failed = True
                continue
            value = p75(values)
            ok = value <= regression
            failed = failed or not ok
            viewport_report[metric] = {
                "p75": _round(metric, value),
                "target": target,
                "regression": regression,
                "pass": ok,
                "warn": value > target,
                "samples": len(values),
            }

        by_interaction = metrics.get("inp_by_interaction") or {}
        interaction_report: dict[str, dict] = {}
        for name in INTERACTIONS:
            values = [float(value) for value in (by_interaction.get(name) or [])]
            interaction_report[name] = {
                "samples": len(values),
                "p75": _round("inp_ms", p75(values)) if values else None,
            }
            if not values and require_interactions:
                failed = True
        viewport_report["inp_by_interaction"] = interaction_report
        report[viewport] = viewport_report
    return report, failed


def exit_code(failed: bool) -> int:
    return 1 if failed else 0


def classify_requests(urls: Iterable[str], base: str) -> list[str]:
    """返回不是本机预览源、也不是 data/blob 的请求；应为空。"""
    allowed_prefixes = (base, "data:", "blob:", "about:", "chrome:", "devtools:")
    external = []
    for url in urls:
        if url.startswith(allowed_prefixes):
            continue
        external.append(url)
    return external


def build_evidence(
    *,
    measured_at: str,
    command: str,
    build_info: dict,
    samples: dict[str, dict[str, list[float]]],
    samples_per_viewport: int,
    request_urls: Iterable[str],
    external_requests: Iterable[str],
) -> tuple[dict, bool]:
    report, failed = judge(samples)
    metrics: dict[str, dict] = {}
    inp_by_interaction: dict[str, dict] = {}
    warnings: list[str] = []
    for viewport in VIEWPORTS:
        metrics[viewport] = {
            metric: report[viewport][metric] for metric in REGRESSION
        }
        inp_by_interaction[viewport] = report[viewport]["inp_by_interaction"]
        for metric in REGRESSION:
            entry = report[viewport][metric]
            if entry.get("warn"):
                warnings.append(
                    f"{viewport}.{metric} p75={entry['p75']} "
                    f"> target {entry['target']}"
                )
    urls = list(request_urls)
    doc = {
        "ticket": TICKET,
        "measured_at": measured_at,
        "command": command,
        "build": build_info,
        "load_route": LOAD_ROUTE,
        "samples_per_viewport": samples_per_viewport,
        "viewports": {
            name: f"{spec['width']}x{spec['height']}"
            for name, spec in VIEWPORTS.items()
        },
        "interactions": list(INTERACTIONS),
        "interaction_definitions": INTERACTION_DEFS,
        "inp_floor_ms": INP_FLOOR_MS,
        "metrics": metrics,
        "inp_by_interaction": inp_by_interaction,
        "requests": {
            "total": len(urls),
            "external": sorted(set(external_requests)),
        },
        "target_warnings": warnings,
        "conclusion": "fail" if failed else "pass",
    }
    return doc, failed


def write_evidence(path: Path, doc: dict) -> None:
    """同一文件保留多次测量：``runs`` 依次追加，最新一跑在末尾。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    runs: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            runs = list(existing.get("runs", []))
        except (json.JSONDecodeError, OSError):
            runs = []
    runs.append(doc)
    document = {
        "ticket": TICKET,
        "updated_at": doc["measured_at"],
        "runs": runs,
    }
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------
# 构建与预览
# --------------------------------------------------------------------------


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node executable not found on PATH")
    return node


def build_frontend() -> None:
    node = _node()
    subprocess.run(
        [node, "node_modules/typescript/bin/tsc", "--noEmit"],
        cwd=FRONTEND,
        check=True,
    )
    subprocess.run(
        [node, "node_modules/vite/bin/vite.js", "build"],
        cwd=FRONTEND,
        check=True,
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_preview(base: str, proc: subprocess.Popen, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("vite preview exited early")
        try:
            with urllib.request.urlopen(f"{base}/market", timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.1)
    raise RuntimeError("vite preview did not answer")


class Preview:
    """``vite preview`` 在随机端口、``--strictPort``，避免端口漂移。"""

    def __init__(self) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> str:
        env = os.environ.copy()
        # 代理目标不可达无妨：页面里的 /api 全部被 route 桩拦截。
        env["VITE_API_PROXY_TARGET"] = "http://127.0.0.1:9"
        self.proc = subprocess.Popen(
            [
                _node(),
                "node_modules/vite/bin/vite.js",
                "preview",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--strictPort",
            ],
            cwd=FRONTEND,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        _wait_preview(self.base, self.proc)
        return self.base

    def __exit__(self, *_exc: object) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


# --------------------------------------------------------------------------
# 桩接口与夹具（全本地，不联网）
# --------------------------------------------------------------------------

SERVER_TIME = "2026-11-05T09:30:00+08:00"


def _envelope(data: object, status: str = "ok") -> dict:
    return {
        "schema_version": "market-envelope-v1",
        "status": status,
        "source": "static",
        "as_of": SERVER_TIME,
        "fetched_at": SERVER_TIME,
        "is_stale": False,
        "stale_reason": None,
        "error_code": None,
        "error_message": None,
        "partial": False,
        "failed_blocks": [],
        "data": data,
    }


META_OPTIONS = {
    "app_version": "0.9.0",
    "server_time": SERVER_TIME,
    "default_analysis_date": "2026-11-05",
    "llm_profiles": [{"id": "deepseek-default", "label": "DeepSeek 默认"}],
    "stage_toggles": [{"id": "policy", "label": "政策分析", "default": True}],
    "limits": {"max_active_jobs": 1, "max_date_ahead_days": 0},
    "journal": {
        "available": False,
        "entry_url": "http://127.0.0.1:8502",
        "reason": "not_running",
    },
    "contract_version": "api-v1",
}

EMPTY_PAGE = {"items": [], "next_cursor": None}
EMPTY_ENVELOPE = _envelope(None, status="empty")
SEARCH_EMPTY = _envelope({"items": [], "truncated": False})

OVERVIEW = _envelope(
    {
        "market_session": "trading",
        "indices": [
            {
                "code": "000001",
                "name": "上证指数",
                "price": 3234.52,
                "change_pct": 0.42,
                "change_amt": 13.52,
            },
            {
                "code": "399001",
                "name": "深证成指",
                "price": 10123.44,
                "change_pct": -0.18,
                "change_amt": -18.21,
            },
            {
                "code": "399006",
                "name": "创业板指",
                "price": 2034.11,
                "change_pct": 0.91,
                "change_amt": 18.33,
            },
        ],
        "northbound": None,
    }
)

INDUSTRIES = _envelope(
    {
        "top": [
            {
                "rank": 1,
                "name": "半导体",
                "code": "BK0123",
                "change_pct": 2.34,
                "up_count": 42,
                "down_count": 5,
                "leader": "中芯国际",
                "leader_change": 5.12,
            },
            {
                "rank": 2,
                "name": "白酒",
                "code": "BK0456",
                "change_pct": 1.87,
                "up_count": 18,
                "down_count": 3,
                "leader": "贵州茅台",
                "leader_change": 3.21,
            },
        ],
        "bottom": [
            {
                "rank": 31,
                "name": "银行",
                "code": "BK0789",
                "change_pct": -0.94,
                "up_count": 2,
                "down_count": 30,
                "leader": "招商银行",
                "leader_change": -1.12,
            }
        ],
        "total": 32,
    }
)

STRONG = _envelope(
    {
        "items": [
            {
                "ticker_code": "600519",
                "name": "贵州茅台",
                "reason": "白酒",
                "market": "sh",
                "change_pct": 3.21,
                "change_amt": 55.1,
                "close": 1770.0,
                "turnover_pct": 0.62,
            },
            {
                "ticker_code": "300750",
                "name": "宁德时代",
                "reason": "储能",
                "market": "sz",
                "change_pct": 1.37,
                "change_amt": 2.52,
                "close": 186.42,
                "turnover_pct": 0.94,
            },
        ]
    }
)

NEWSFLASH = _envelope(
    {
        "items": [
            {
                "title": "示例快讯",
                "content": "夹具内容，不代表真实行情。",
                "published_at": "2026-11-05T09:20:00+08:00",
            }
        ],
        "untrusted": True,
    }
)

STOCK_SNAPSHOT = _envelope(
    {
        "ticker_code": "600519",
        "quote": {
            "name": "贵州茅台",
            "price": 1770.0,
            "last_close": 1714.9,
            "open": 1720.0,
            "high": 1780.0,
            "low": 1710.0,
            "change_pct": 3.21,
            "change_amt": 55.1,
            "amount_wan": 512300.0,
            "turnover_pct": 0.62,
            "pe_ttm": 31.2,
            "pb": 9.1,
            "amplitude_pct": 4.1,
            "float_mcap_yi": 22200.0,
            "mcap_yi": 22200.0,
            "limit_up": 1886.4,
        },
        "valuation": {
            "eps_forecast": 68.2,
            "pe_forward": 25.9,
            "peg": 1.3,
            "pe_digestion_years": 0.0,
        },
        "sector_blocks": {
            "industry": [{"name": "白酒", "change_pct": 2.1, "desc": "白酒制造"}],
            "concept": [],
            "region": [],
        },
        "units": {"price": "元", "amount": "万元", "mcap": "亿元"},
    }
)


def install_stubs(context: object) -> None:
    """宽匹配先注册、窄匹配后注册（后者优先），覆盖 ``/api/v1/**``。"""

    def fulfill(payload: object, status: int = 200):
        def handler(route: object) -> None:
            route.fulfill(  # type: ignore[attr-defined]
                status=status,
                content_type="application/json",
                body=json.dumps(payload, ensure_ascii=False),
            )

        return handler

    def jobs(route: object) -> None:
        if route.request.method == "POST":  # type: ignore[attr-defined]
            fulfill({"job_id": "job-1", "status": "queued"}, status=201)(route)
        else:
            fulfill(EMPTY_PAGE)(route)

    def stocks(route: object) -> None:
        url = route.request.url  # type: ignore[attr-defined]
        fulfill(STOCK_SNAPSHOT if url.endswith("/snapshot") else EMPTY_ENVELOPE)(
            route
        )

    context.route("**/api/v1/**", fulfill(EMPTY_ENVELOPE))  # type: ignore[attr-defined]
    context.route("**/api/v1/jobs**", jobs)  # type: ignore[attr-defined]
    context.route("**/api/v1/meta/options**", fulfill(META_OPTIONS))  # type: ignore[attr-defined]
    context.route("**/api/v1/market/search**", fulfill(SEARCH_EMPTY))  # type: ignore[attr-defined]
    context.route("**/api/v1/market/overview**", fulfill(OVERVIEW))  # type: ignore[attr-defined]
    context.route("**/api/v1/market/industries**", fulfill(INDUSTRIES))  # type: ignore[attr-defined]
    context.route("**/api/v1/market/strong-stocks**", fulfill(STRONG))  # type: ignore[attr-defined]
    context.route("**/api/v1/market/newsflash**", fulfill(NEWSFLASH))  # type: ignore[attr-defined]
    context.route("**/api/v1/stocks/**", stocks)  # type: ignore[attr-defined]
    context.route("**/api/v1/reports**", fulfill(EMPTY_PAGE))  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# 页面内观测
# --------------------------------------------------------------------------

OBSERVER_SCRIPT = r"""
(() => {
  const perf = { lcp: 0, cls: 0, events: [], mark: 0 };
  window.__perf = perf;
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        perf.lcp = entry.startTime;
      }
    }).observe({ type: "largest-contentful-paint", buffered: true });
  } catch (error) {}
  try {
    let cls = 0, session = 0, sessionStart = 0, last = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.hadRecentInput) continue;
        const gap = entry.startTime - last;
        if (session > 0 &&
            (entry.startTime - sessionStart > 5000 || gap > 1000)) {
          session = 0;
        }
        if (session === 0) sessionStart = entry.startTime;
        session += entry.value;
        last = entry.startTime;
        if (session > cls) cls = session;
      }
      perf.cls = cls;
    }).observe({ type: "layout-shift", buffered: true });
  } catch (error) {}
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        perf.events.push({
          startTime: entry.startTime,
          duration: entry.duration,
          interactionId: entry.interactionId || 0,
        });
        if (perf.events.length > 1000) perf.events.shift();
      }
    }).observe({ type: "event", durationThreshold: 16, buffered: true });
  } catch (error) {}
})();
"""

READ_LCP = "() => window.__perf.lcp"
READ_CLS = "() => window.__perf.cls"
MARK_INP = "() => { window.__perf.mark = performance.now(); }"
READ_INP = """
() => {
  const mark = window.__perf.mark;
  return window.__perf.events
    .filter((entry) => entry.interactionId && entry.startTime >= mark)
    .map((entry) => entry.duration);
}
"""
NEXT_FRAME = """
() => new Promise((resolve) => {
  requestAnimationFrame(() => requestAnimationFrame(resolve));
})
"""


def _interact(page: object, viewport: str, name: str, base: str) -> float:
    if name == "manual_refresh":
        page.evaluate(MARK_INP)  # type: ignore[attr-defined]
        page.locator('[data-testid="market-refresh"]').click()  # type: ignore
    elif name == "market_to_stock":
        page.evaluate(MARK_INP)  # type: ignore[attr-defined]
        page.locator('a[href^="/stocks/"]').first.click()  # type: ignore
        page.wait_for_url("**/stocks/**", timeout=10000)  # type: ignore
    elif name == "list_filter":
        page.goto(f"{base}/jobs", wait_until="domcontentloaded")  # type: ignore
        page.wait_for_selector(  # type: ignore[attr-defined]
            '[data-testid="page-jobs"]', timeout=15000
        )
        if viewport == "mobile":
            page.locator('[data-testid="job-filter-open"]').click()  # type: ignore
            page.wait_for_selector(  # type: ignore[attr-defined]
                '[data-testid="job-filters-mobile"]',
                state="visible",
                timeout=10000,
            )
            target = (
                '[data-testid="job-filters-mobile"] '
                '[data-testid="filter-status-succeeded"] input'
            )
        else:
            target = (
                '[data-testid="job-filters"] '
                '[data-testid="filter-status-succeeded"] input'
            )
        page.wait_for_selector(target, timeout=10000)  # type: ignore
        page.evaluate(MARK_INP)  # type: ignore[attr-defined]
        page.locator(target).click()  # type: ignore[attr-defined]
    else:
        raise ValueError(f"unknown interaction: {name}")

    page.evaluate(NEXT_FRAME)  # type: ignore[attr-defined]
    page.wait_for_timeout(INP_SETTLE_MS)  # type: ignore[attr-defined]
    durations = page.evaluate(READ_INP)  # type: ignore[attr-defined]
    return float(max(durations)) if durations else INP_FLOOR_MS


def measure(
    base: str, samples: int, *, headless: bool = True
) -> tuple[dict[str, dict], list[str], list[str]]:
    from playwright.sync_api import sync_playwright

    results: dict[str, dict] = {
        viewport: {
            "lcp_ms": [],
            "cls": [],
            "inp_ms": [],
            "inp_by_interaction": {name: [] for name in INTERACTIONS},
        }
        for viewport in VIEWPORTS
    }
    request_urls: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            for viewport, spec in VIEWPORTS.items():
                context = browser.new_context(
                    viewport={"width": spec["width"], "height": spec["height"]},
                    device_scale_factor=1,
                )
                context.add_init_script(OBSERVER_SCRIPT)
                install_stubs(context)
                try:
                    for index in range(samples):
                        name = INTERACTIONS[index % len(INTERACTIONS)]
                        page = context.new_page()
                        page.on("request", lambda req: request_urls.append(req.url))
                        try:
                            page.goto(f"{base}{LOAD_ROUTE}")
                            page.wait_for_selector(
                                '[data-testid="page-market"]', timeout=15000
                            )
                            page.wait_for_selector(
                                '[data-testid="strong-row"], '
                                '[data-testid="strong-card"]',
                                timeout=15000,
                            )
                            page.wait_for_timeout(SETTLE_MS)
                            bucket = results[viewport]
                            bucket["lcp_ms"].append(
                                float(page.evaluate(READ_LCP))
                            )
                            bucket["cls"].append(float(page.evaluate(READ_CLS)))
                            value = _interact(page, viewport, name, base)
                            bucket["inp_ms"].append(value)
                            bucket["inp_by_interaction"][name].append(value)
                        finally:
                            page.close()
                finally:
                    context.close()
        finally:
            browser.close()

    external = classify_requests(request_urls, base)
    return results, request_urls, external


# --------------------------------------------------------------------------
# 命令行
# --------------------------------------------------------------------------


def _build_info() -> dict:
    stat = MANIFEST.stat()
    mtime = dt.datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(
        timespec="seconds"
    )
    return {
        "manifest": MANIFEST.relative_to(ROOT).as_posix(),
        "mtime": mtime,
    }


def _print_summary(doc: dict) -> None:
    print(f"{TICKET} 性能门禁  {doc['measured_at']}")
    for viewport, metrics in doc["metrics"].items():
        print(f"[{viewport} {doc['viewports'][viewport]}]")
        for metric, entry in metrics.items():
            if entry["p75"] is None:
                print(f"  {metric:<7} FAIL  {entry.get('reason')}")
                continue
            flag = "PASS" if entry["pass"] else "FAIL"
            warn = "  (超目标线)" if entry["warn"] else ""
            print(
                f"  {metric:<7} p75={entry['p75']}  "
                f"target={entry['target']}  "
                f"regression={entry['regression']}  {flag}{warn}"
            )
        by_interaction = doc["inp_by_interaction"][viewport]
        for name, entry in by_interaction.items():
            print(f"    inp:{name:<15} n={entry['samples']}")
    external = doc["requests"]["external"]
    print(f"外部请求: {len(external)}")
    if external:
        for url in external[:10]:
            print(f"  {url}")
    print(f"结论: {doc['conclusion']}")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="P6-05 性能门禁")
    parser.add_argument("--samples", type=int, default=MIN_SAMPLES)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--headful", action="store_true")
    args = parser.parse_args(argv)

    if args.samples < MIN_SAMPLES:
        parser.error(f"--samples 至少为 {MIN_SAMPLES}")
    if not args.no_build:
        build_frontend()
    if not MANIFEST.exists():
        raise SystemExit(f"缺少构建产物: {MANIFEST}")

    out = args.out or (
        REVIEWS / f"{dt.date.today().isoformat()}_P6-05性能证据.json"
    )
    command = f"perf_core.py --samples {args.samples}"
    with Preview() as base:
        samples, request_urls, external = measure(
            base, args.samples, headless=not args.headful
        )

    doc, failed = build_evidence(
        measured_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        command=command,
        build_info=_build_info(),
        samples=samples,
        samples_per_viewport=args.samples,
        request_urls=request_urls,
        external_requests=external,
    )
    write_evidence(out, doc)
    _print_summary(doc)
    print(f"证据: {out}")
    return exit_code(failed)


if __name__ == "__main__":
    raise SystemExit(main())
