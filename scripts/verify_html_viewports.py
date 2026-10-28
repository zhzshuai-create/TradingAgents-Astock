"""Check a local HTML file at three viewports and screenshot each.

    python scripts/verify_html_viewports.py <file.html> <shots_dir>

Prints one JSON line: per viewport, scrollWidth/clientWidth (must be equal,
otherwise the page overflows horizontally) and any page errors.
Run with a Python that has playwright + chromium (Python313, not .venv).
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

VIEWPORTS = [("desktop", 1440, 900), ("mobile", 390, 844), ("narrow", 360, 780)]


def main() -> None:
    target = Path(sys.argv[1]).resolve().as_uri()
    shots = Path(sys.argv[2])
    shots.mkdir(parents=True, exist_ok=True)
    stem = Path(sys.argv[1]).stem

    out = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, w, h in VIEWPORTS:
            ctx = browser.new_context(viewport={"width": w, "height": h})
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.goto(target)
            page.wait_for_timeout(600)
            out[name] = {
                "scrollWidth": page.evaluate("document.documentElement.scrollWidth"),
                "clientWidth": page.evaluate("document.documentElement.clientWidth"),
                "pageerrors": errs,
            }
            page.screenshot(path=str(shots / f"{stem}_{name}.png"))
            ctx.close()
        browser.close()

    print(json.dumps(out, ensure_ascii=True))
    bad = [k for k, v in out.items()
           if v["scrollWidth"] != v["clientWidth"] or v["pageerrors"]]
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
