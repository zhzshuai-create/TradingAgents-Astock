"""Screenshot the wireframe pages and check for page-level overflow.

    python scripts/shoot_wireframes.py

Needs playwright + chromium (Python313). Output goes to %TEMP%/astock-day5-wireframes.
"""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent / "docs" / "upgrade" / "wireframes"
SHOTS = Path(os.environ.get("TEMP", ".")) / "astock-day5-wireframes"

ALL_IDS = ["w01", "w02", "w03", "w04", "w05", "w06", "w07", "w08", "w09", "w10"]

PLAN = [
    ("desktop", 1440, 900, "core-wireframes-desktop.html", ALL_IDS),
    ("mobile", 390, 844, "core-wireframes-mobile.html", ALL_IDS),
    ("narrow", 360, 780, "core-wireframes-mobile.html", ["w01", "w06"]),
]

AUDIT = """() => {
  const doc = document.documentElement;
  const small = [];
  for (const el of document.querySelectorAll('.m-nav span, .m-primary, .m-btn, .m-btn-danger, .m-top-r')) {
    const r = el.getBoundingClientRect();
    if (r.height > 0 && r.height < 43.5) small.push([el.className, Math.round(r.height)]);
  }
  return {scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth, smallTargets: small};
}"""


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    out = {}
    failures = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, width, height, html, ids in PLAN:
            ctx = browser.new_context(viewport={"width": width, "height": height})
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto((ROOT / html).resolve().as_uri())
            page.evaluate("document.documentElement.style.scrollBehavior='auto'")
            page.wait_for_timeout(300)
            audit = page.evaluate(AUDIT)
            page.screenshot(path=str(SHOTS / f"{name}-full.png"), full_page=True, animations="disabled")
            for sid in ids:
                page.locator(f"#{sid}").screenshot(path=str(SHOTS / f"{name}-{sid}.png"), animations="disabled")
            out[name] = {**audit, "pageerrors": errors}
            if audit["scrollWidth"] != audit["clientWidth"] or errors:
                failures.append(name)
            if name != "desktop" and audit["smallTargets"]:
                failures.append(f"{name}:touch<44")
            ctx.close()
        browser.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("shots:", SHOTS)
    if failures:
        raise SystemExit("FAIL " + ", ".join(failures))


if __name__ == "__main__":
    main()
