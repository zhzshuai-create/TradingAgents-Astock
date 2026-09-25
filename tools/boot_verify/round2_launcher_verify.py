"""Round-2 A verification: parallel boot of journal+platform, first-frame journal probe, mask timeline no-regression."""
import subprocess
import sys
import time
import urllib.request
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

COPY = Path(os.environ.get("ASTOCK_REPO") or Path(__file__).resolve().parents[2])
JOURNAL = Path(os.environ.get("ASTOCK_JOURNAL") or COPY.parent / "trade-journal")
PORT = 8503

POLLER = """
window.__tl = {};
(function () {
  const mark = (k) => { if (!(k in window.__tl)) window.__tl[k] = Math.round(performance.now()); };
  const iv = setInterval(() => {
    const h = document.documentElement;
    if (h.getAttribute('data-boot') === 'play') mark('play');
    if (document.getElementById('boot-ready')) mark('ready');
    if (h.hasAttribute('data-boot-done')) mark('done');
    if (h.hasAttribute('data-boot-gone')) mark('gone');
  }, 40);
})();
"""


def health(port):
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/_stcore/health", timeout=0.5) as r:
            return r.status == 200
    except Exception:
        return False


def free(port):
    import socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def health_stable(port):
    # 单次 200 不可信 (本机 loopback 有单发假 200/::1 丢弃怪象): 连两次, 间隔 150ms
    if not health(port):
        return False
    time.sleep(0.15)
    return health(port)


def main():
    for port in (8502, PORT):
        assert free(port), f"port {port} occupied before spawn — abort (attribution would be garbage)"
    t0 = time.perf_counter()
    pj = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py",
                           "--server.port", "8502", "--server.headless", "true"],
                          cwd=str(JOURNAL), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pp = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(COPY / "web" / "app.py"),
                           "--server.port", str(PORT), "--server.headless", "true"],
                          cwd=str(COPY), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tj = tp = None
    try:
        for _ in range(400):
            dt = time.perf_counter() - t0
            if dt > 0.5:
                if tj is None and health_stable(8502):
                    tj = dt
                if tp is None and health_stable(PORT):
                    tp = dt
            if tj and tp:
                break
            time.sleep(0.05)
        print(f"journal_health={tj:.2f}s platform_health={tp:.2f}s (parallel, from spawn)")
        assert tj is not None and tp is not None, "boot timeout"
        if min(tj, tp) < 0.5:
            import os
            os.system(f'netstat -ano | findstr ":8502 :{PORT}" | findstr LISTEN')
            raise SystemExit("suspiciously fast health — listener attribution unclear, abort")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.add_init_script("try { sessionStorage.clear(); } catch (e) {}")
            page.add_init_script(POLLER)
            page.goto(f"http://localhost:{PORT}/", wait_until="commit")
            page.wait_for_function("() => window.__tl && ('ready' in window.__tl)", timeout=20000)
            # 首帧即切日志模式 = 真实最坏路径
            page.get_by_role("button", name="交易日志").first.click(timeout=5000)
            try:
                page.wait_for_selector("iframe[src*='8502']", timeout=8000)
                n_iframe = 1
                has_warn = False
            except Exception:
                body = page.inner_text("body")
                has_warn = "未检测到交易日志服务" in body
                n_iframe = page.evaluate(
                    "() => [...document.querySelectorAll('iframe')].filter(f => (f.src||'').includes('8502')).length")
            tl = page.evaluate("() => window.__tl")
            print(f"journal_mode: warning={has_warn} iframes_8502={n_iframe}")
            print("timeline: " + "  ".join(f"{k}={v}" for k, v in sorted(tl.items(), key=lambda kv: kv[1])))
            ok = (not has_warn) and n_iframe >= 1 and tj < tp + 2.0
            print("VERIFY", "PASS" if ok else "FAIL")
            browser.close()
    finally:
        for p in (pj, pp):
            p.terminate()
        for p in (pj, pp):
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()


if __name__ == "__main__":
    main()
