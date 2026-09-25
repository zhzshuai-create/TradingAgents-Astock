"""Round-2 recon: cold browser timeline of the boot mask vs shell vs script end.

Restart the streamlit process per run (module cache otherwise fakes warm numbers).
Poller runs in-page at 40ms so timestamps share one performance.now() clock.
"""
import subprocess
import sys
import time
import urllib.request
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(os.environ.get("ASTOCK_REPO") or Path(__file__).resolve().parents[2])
PORT = 8503

POLLER = """
window.__tl = {};
(function () {
  const mark = (k) => { if (!(k in window.__tl)) window.__tl[k] = Math.round(performance.now()); };
  let sawStatus = false;
  const iv = setInterval(() => {
    const h = document.documentElement;
    if (document.getElementById('boot-mask')) mark('mask_dom');
    if (h.getAttribute('data-boot') === 'play') mark('play');
    if (document.getElementById('boot-ready')) mark('ready');
    if (h.hasAttribute('data-boot-done')) mark('done');
    if (h.hasAttribute('data-boot-gone')) mark('gone');
    const sw = document.querySelector('[data-testid="stStatusWidget"]');
    if (sw) sawStatus = true;
    else if (sawStatus && ('ready' in window.__tl)) mark('script_end');
  }, 40);
  window.__tlStop = () => clearInterval(iv);
})();
"""


def cold_run(pw, idx):
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(REPO / "web" / "app.py"),
         "--server.port", str(PORT), "--server.headless", "true"],
        cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://localhost:{PORT}/_stcore/health", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script("try { sessionStorage.clear(); } catch (e) {}")
        page.add_init_script(POLLER)
        page.goto(f"http://localhost:{PORT}/", wait_until="commit")
        try:
            page.wait_for_function(
                "() => window.__tl && ('script_end' in window.__tl || 'gone' in window.__tl)",
                timeout=25000,
            )
            page.wait_for_timeout(1500)
        except Exception:
            pass
        tl = page.evaluate("() => window.__tl")
        browser.close()
        return tl
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def main():
    with sync_playwright() as pw:
        for i in range(3):
            tl = cold_run(pw, i)
            print(f"run{i}: " + "  ".join(f"{k}={v}" for k, v in sorted(tl.items(), key=lambda kv: kv[1])))
            time.sleep(1)


if __name__ == "__main__":
    main()
