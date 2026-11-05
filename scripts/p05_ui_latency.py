"""P05-c: from an SSE frame reaching the browser to the stage text changing.

P2-13. Runs the real dev entry (API + worker, fake graph) on a temporary root,
previews the built frontend with ``/api`` proxied to it, creates a job from
Python, and measures inside the browser:

* arrival: the app reads the event stream with ``response.body.getReader()``
  (not the ``EventSource`` API, so CDP's ``eventSourceMessageReceived`` never
  fires). An init script wraps ``fetch`` for the ``/events`` URL and the
  reader it hands back, so every resolved ``reader.read()`` is timed with
  ``performance.now()`` and its SSE block is parsed for ``stage_changed``;
* visible: ``MutationObserver`` timestamp (``performance.now()``) of the first
  ``stage-<id>`` text change after that frame.

Both timestamps come from the same page clock, so no clock alignment is
needed. A frame that changes nothing in the DOM (for example a stage already
shown as done after a snapshot replay) has no matching mutation and
contributes no sample.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        scripts/p05_ui_latency.py

Playwright lives in the system Python, not in .venv; the dev backend itself is
started with .venv/Scripts/python.exe. Writes
docs/upgrade/reviews/2026-11-05_P2性能结果.json and prints one JSON line.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from playwright.sync_api import Browser, BrowserContext, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
REVIEWS = ROOT / "docs" / "upgrade" / "reviews"
RESULT_PATH = REVIEWS / "2026-11-05_P2性能结果.json"
P1_RESULT_PATH = REVIEWS / "2026-11-05_P1-13性能结果.json"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

TICKER = "600519"
STAGE_DELAY_MS = 1500
TARGET_SAMPLES = 20
MAX_JOBS = 3
HARD_LINE_MS = 500
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
VIEWPORT = {"width": 1440, "height": 900}

PAGE_SCRIPT = """
window.__p05 = { frames: [], chunks: [], mutations: [] };
(() => {
  const isEventStream = (url) =>
    url.includes("/jobs/") && url.endsWith("/events");
  const readData = (block) => {
    const lines = block.split(/\\r\\n|\\n|\\r/);
    const data = [];
    for (const line of lines) {
      if (!line.startsWith("data:")) continue;
      const value = line.slice(5);
      data.push(value.startsWith(" ") ? value.slice(1) : value);
    }
    return data.length === 0 ? null : data.join("\\n");
  };
  const origFetch = window.fetch;
  window.fetch = function (...args) {
    const input = args[0];
    let url = "";
    try {
      url = typeof input === "string" ? input : (input && input.url) || "";
    } catch (error) {
      url = "";
    }
    const promise = origFetch.apply(this, args);
    if (!isEventStream(url)) return promise;
    return promise.then((response) => {
      const body = response.body;
      if (!body || typeof body.getReader !== "function") return response;
      const reader = body.getReader();
      let buffer = "";
      const decoder = new TextDecoder("utf-8");
      const flush = (text, t) => {
        buffer += text;
        for (;;) {
          const separator = /\\r\\n\\r\\n|\\n\\n|\\r\\r/.exec(buffer);
          if (separator === null) break;
          const block = buffer.slice(0, separator.index);
          buffer = buffer.slice(separator.index + separator[0].length);
          const data = readData(block);
          if (data === null) continue;
          let event;
          try {
            event = JSON.parse(data);
          } catch (error) {
            continue;
          }
          if (!event || event.type !== "stage_changed") continue;
          const payload = event.payload || {};
          window.__p05.frames.push({
            t,
            stage_id: String(payload.stage_id),
            stage_status: String(payload.stage_status),
          });
        }
      };
      try {
        Object.defineProperty(body, "getReader", {
          configurable: true,
          value: function () {
            return {
              read: async function () {
                const result = await reader.read();
                if (!result.done && result.value) {
                  const t = performance.now();
                  window.__p05.chunks.push(t);
                  flush(decoder.decode(result.value, { stream: true }), t);
                }
                return result;
              },
              cancel: (reason) => reader.cancel(reason),
              releaseLock: () => reader.releaseLock(),
              get closed() {
                return reader.closed;
              },
            };
          },
        });
      } catch (error) {
        // Leaving the stream untouched only costs samples, not correctness.
      }
      return response;
    });
  };

  const last = new Map();
  const record = (node) => {
    const element = node.nodeType === 1 ? node : node.parentElement;
    const button = element && element.closest
      ? element.closest('[data-testid^="stage-"]')
      : null;
    if (!button) return;
    const text = (button.innerText || "").replace(/\\s+/g, " ").trim();
    const id = button.getAttribute("data-testid");
    const before = last.get(id);
    last.set(id, text);
    if (before !== undefined && before !== text) {
      window.__p05.mutations.push({ id, before, after: text, t: performance.now() });
    }
  };
  const observer = new MutationObserver((records) => {
    for (const item of records) {
      if (item.type === "characterData") {
        record(item.target);
        continue;
      }
      for (const node of item.addedNodes) record(node);
    }
  });
  const start = () => observer.observe(document.body, {
    subtree: true, childList: true, characterData: true,
  });
  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start);
})();
"""


def run_node(script: str, *args: str) -> None:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node executable not found on PATH")
    subprocess.run([node, script, *args], cwd=FRONTEND, check=True)


def build() -> None:
    run_node("node_modules/typescript/bin/tsc", "--noEmit")
    run_node("node_modules/vite/bin/vite.js", "build")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until(predicate, timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise RuntimeError(f"timed out waiting for {label}")


def get_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def api_ready(base: str, proc: subprocess.Popen[str], timeout: float = 60.0) -> None:
    url = f"{base}/api/v1/jobs/not-ready-probe"

    def probe() -> bool:
        if proc.poll() is not None:
            raise RuntimeError("dev entry exited early")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return response.status == 404
        except urllib.error.HTTPError as error:
            return error.code == 404
        except (urllib.error.URLError, ConnectionError):
            return False

    wait_until(probe, timeout, "dev API")


def preview_ready(url: str, proc: subprocess.Popen[str], timeout: float = 60.0) -> None:
    def probe() -> bool:
        if proc.poll() is not None:
            raise RuntimeError("vite preview exited early")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return response.status == 200
        except (urllib.error.URLError, ConnectionError):
            return False

    wait_until(probe, timeout, "vite preview")


class DevBackend:
    def __init__(self, root: Path) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = os.environ.copy()
        env["TA_DEV_ROOT"] = str(root)
        self.proc = subprocess.Popen(
            [
                str(PYTHON),
                "scripts/dev_backend.py",
                "--port",
                str(self.port),
                "--stage-delay-ms",
                str(STAGE_DELAY_MS),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def __enter__(self) -> str:
        api_ready(self.base, self.proc)
        return self.base

    def __exit__(self, *_exc: object) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


class Preview:
    def __init__(self, api: str) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("node executable not found on PATH")
        env = os.environ.copy()
        env["VITE_API_PROXY_TARGET"] = api
        self.proc = subprocess.Popen(
            [
                node,
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

    def __enter__(self) -> str:
        preview_ready(f"{self.base}/workbench", self.proc)
        return self.base

    def __exit__(self, *_exc: object) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


def create_job(api: str) -> str:
    payload = json.dumps(
        {
            "ticker": TICKER,
            "analysis_date": datetime.now(timezone(timedelta(hours=8)))
            .date()
            .isoformat(),
            "config": {
                "llm_profile": "deepseek-default",
                "parallel_analysts": True,
                "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{api}/api/v1/jobs",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read().decode("utf-8"))
    return str(body["job_id"])


def job_status(api: str, job_id: str) -> str | None:
    try:
        return str(get_json(f"{api}/api/v1/jobs/{job_id}")["status"])
    except Exception:  # noqa: BLE001 - the poll is best effort
        return None


def measure_job(
    browser: Browser, base: str, api: str, job_id: str
) -> tuple[list[float], dict[str, Any]]:
    context: BrowserContext = browser.new_context(viewport=VIEWPORT)
    page = context.new_page()
    page.add_init_script(PAGE_SCRIPT)

    started = time.monotonic()
    page.goto(f"{base}/jobs/{job_id}")
    page.get_by_test_id("page-job-detail").wait_for(state="visible", timeout=30_000)

    wait_until(
        lambda: job_status(api, job_id) in TERMINAL, 120, f"job {job_id} terminal"
    )
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=10_000)
    time.sleep(0.5)

    marks = page.evaluate(
        """() => ({
            frames: window.__p05.frames,
            chunks: window.__p05.chunks.length,
            mutations: window.__p05.mutations,
        })"""
    )
    context.close()

    frames = marks["frames"]
    mutations = marks["mutations"]
    samples: list[float] = []
    dropped = 0
    used: set[int] = set()
    for frame in frames:
        for index, mutation in enumerate(mutations):
            if index in used or mutation["id"] != f"stage-{frame['stage_id']}":
                continue
            delta = float(mutation["t"]) - float(frame["t"])
            if delta < -1:
                continue
            used.add(index)
            if delta <= 5000:
                samples.append(round(delta, 3))
            else:
                dropped += 1
            break

    meta = {
        "job_id": job_id,
        "stage_frames": len(frames),
        "stream_chunks": marks["chunks"],
        "mutations": len(mutations),
        "samples": len(samples),
        "dropped_over_5000ms": dropped,
        "seconds": round(time.monotonic() - started, 1),
    }
    return samples, meta


def p1_metrics() -> dict[str, Any]:
    body = json.loads(P1_RESULT_PATH.read_text(encoding="utf-8-sig"))
    cases = {case["id"]: case for case in body["metrics"]["P05"]["cases"]}
    source = str(P1_RESULT_PATH.relative_to(ROOT)).replace("\\", "/")
    return {
        "a": cases["P05-a"],
        "b": cases["P05-b"],
        "a_median": int(cases["P05-a"]["median"]),
        "source": source,
    }


def write_result(
    samples: list[float], jobs: list[dict[str, Any]], browser_version: str
) -> dict[str, Any]:
    history = p1_metrics()
    ordered = sorted(samples)
    p05_c = round(median(ordered), 3) if ordered else None
    p95_index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
    p95 = round(ordered[p95_index], 3) if ordered else None
    total = None if p05_c is None else round(history["a_median"] + p05_c, 3)

    result = {
        "schema_version": "perf-result-v1",
        "run": {
            "run_id": f"perf-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "date": datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
            "commit": subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip(),
            "operator": "qoder-agent",
            "notes": (
                "P2-13 只补界面段 P05-c。P05-a 与 P05-b 不重测，引用 P1-13 的 JSON；"
                "P05 合计 = P05-a 中位 + P05-c 中位。P05-c 的到达时刻取页面内 "
                "reader.read() 解析出 stage_changed 的 performance.now()（详情页用 fetch 流读取，"
                "不使用 EventSource，CDP 的 eventSourceMessageReceived 不会触发），"
                "可见时刻取同一页面时钟下 MutationObserver 记录的首个 stage-<id> 文案变化；"
                "两时刻同钟，无需校准。配对规则：同一 stage_id 的帧到达后，该阶段按钮的第一次文案变化。"
            ),
        },
        "environment": {
            "python": sys.version.split()[0],
            "browser": browser_version,
            "os": f"{os.name}-{sys.getwindowsversion().major}.{sys.getwindowsversion().build}"
            if os.name == "nt"
            else os.name,
            "viewport": f"{VIEWPORT['width']}x{VIEWPORT['height']}",
            "stage_delay_ms": STAGE_DELAY_MS,
        },
        "method": {
            "script": "scripts/p05_ui_latency.py",
            "measurement": (
                "page reader.read() timestamp of a stage_changed SSE block -> "
                "first MutationObserver change of stage-<id>"
            ),
            "clock": "single page clock (performance.now)",
            "pairing": "first matching stage-id text change after the frame",
            "samples_per_metric": len(ordered),
            "statistic": "median",
            "jobs": jobs,
        },
        "metrics": {
            "P01": None,
            "P02": None,
            "P03": None,
            "P04": None,
            "P05": {
                "label": "任务事件延迟",
                "unit": "ms",
                "cases": [
                    {
                        "id": "P05-a",
                        "name": "事件产生到 SSE 帧可读（服务端，引用 P1-13）",
                        "baseline": None,
                        "budget": HARD_LINE_MS,
                        "budget_source": "硬线",
                        "samples": history["a"]["samples"],
                        "median": history["a"]["median"],
                        "source": history["source"],
                        "pass": bool(history["a"]["pass"]),
                    },
                    {
                        "id": "P05-b",
                        "name": "阶段间隔偏差（引用 P1-13）",
                        "unit": "percent",
                        "budget": 5,
                        "samples": history["b"]["samples"],
                        "median": history["b"]["median"],
                        "source": history["source"],
                        "pass": bool(history["b"]["pass"]),
                    },
                    {
                        "id": "P05-c",
                        "name": "SSE 帧到达浏览器到阶段文案可见",
                        "baseline": None,
                        "budget": HARD_LINE_MS,
                        "budget_source": "P2-13 新增",
                        "samples": ordered,
                        "median": p05_c,
                        "p95": p95,
                        "pass": p05_c is not None and p05_c <= HARD_LINE_MS,
                    },
                    {
                        "id": "P05",
                        "name": "合计（P05-a 中位 + P05-c 中位）",
                        "baseline": None,
                        "budget": HARD_LINE_MS,
                        "budget_source": "硬线",
                        "median": total,
                        "pass": total is not None and total <= HARD_LINE_MS,
                    },
                ],
            },
        },
    }
    REVIEWS.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P05-c 界面段时延")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.skip_build:
        print("skipping build")
    else:
        print("building frontend...")
        build()

    samples: list[float] = []
    jobs: list[dict[str, Any]] = []
    browser_version = ""
    with tempfile.TemporaryDirectory(prefix="astock-p05-") as temp:
        with DevBackend(Path(temp)) as api:
            print(f"dev api at {api}")
            with Preview(api) as base:
                print(f"preview at {base}")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    browser_version = f"Chromium {browser.version}"
                    try:
                        attempt = 0
                        while len(samples) < TARGET_SAMPLES and attempt < MAX_JOBS:
                            attempt += 1
                            job_id = create_job(api)
                            got, meta = measure_job(browser, base, api, job_id)
                            print(
                                f"job {job_id}: {len(got)} samples, "
                                f"{meta['stage_frames']} frames, "
                                f"{meta['mutations']} mutations"
                            )
                            samples.extend(got)
                            meta["samples"] = len(got)
                            jobs.append(meta)
                    finally:
                        browser.close()

    result = write_result(samples, jobs, browser_version)
    cases = {case["id"]: case for case in result["metrics"]["P05"]["cases"]}
    summary = {
        "script": "scripts/p05_ui_latency.py",
        "samples": len(samples),
        "P05-c_median_ms": cases["P05-c"]["median"],
        "P05-c_p95_ms": cases["P05-c"]["p95"],
        "P05_total_ms": cases["P05"]["median"],
        "verdict": "pass" if cases["P05"]["pass"] and len(samples) >= TARGET_SAMPLES else "fail",
        "result": str(RESULT_PATH.relative_to(ROOT)).replace("\\", "/"),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
