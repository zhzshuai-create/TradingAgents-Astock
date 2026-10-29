"""Build docs/upgrade/contracts/AStock_Pro_P0契约集_阅读版.html.

Run with the Python that has `markdown` installed (Python313, not .venv):
    python scripts/build_contracts_html.py

Reuses the master plan's CSS head so the reading version matches the plan's
typography, and strips each contract's leading `# ` line so the combined page
has exactly one h1 per document.
"""
import pathlib
import re

import markdown

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "docs" / "upgrade" / "contracts"
SRC_HTML = ROOT / "docs" / "AStock_Pro_专业投研工作台全面升级计划_2026-10-28.html"
OUT = CONTRACTS / "AStock_Pro_P0契约集_阅读版.html"

# Append new contracts here in reading order.
DOCS = [
    ("semantic-dictionary.md", "核心语义词典"),
    ("job-state-machine.md", "任务状态机"),
    ("idempotency-conflicts.md", "幂等与冲突决策表"),
    ("crash-boundaries.md", "崩溃边界预期表"),
    ("p1-state-machine-tests.md", "P1 状态机测试用例清单"),
    ("report-schema-v1.md", "报告结构契约 v1"),
    ("report-consistency-tests.md", "报告一致性测试清单"),
    ("api-v1.md", "接口契约 v1：任务、报告与市场数据"),
    ("sse-events-v1.md", "SSE 事件流契约 v1"),
    ("error-codes-v1.md", "错误响应字典 v1"),
]


def main() -> None:
    head = SRC_HTML.read_text(encoding="utf-8").split("<body><article>")[0]
    head = re.sub(r"<title>.*?</title>", "<title>AStock Pro P0 契约集</title>",
                  head, count=1, flags=re.S)

    md = markdown.Markdown(extensions=["extra", "toc", "sane_lists"])
    parts = []
    toc = ['<details class="toc"><summary><strong>展开目录</strong></summary>'
           '<div class="toc"><ul>']
    for fname, title in DOCS:
        text = (CONTRACTS / fname).read_text(encoding="utf-8-sig")
        text = re.sub(r"\A#\s.*\n", "", text, count=1)
        body = md.convert(text)
        anchor = fname.replace(".md", "")
        toc.append(f'<li><a href="#{anchor}">{title}</a></li>')
        parts.append(f'<section id="{anchor}"><h1>{title}</h1>\n{body}\n</section>')
    toc.append("</ul></div></details>")

    html = (head + "<body><article>\n" + "\n".join(toc) + "\n"
            + "\n".join(parts) + "\n</article></body></html>")
    OUT.write_text(html, encoding="utf-8")

    b = OUT.read_bytes()
    print("out", OUT)
    print("bytes", len(b))
    print("h1", len(re.findall(rb"<h1[ >]", b)), "(expect", len(DOCS), ")")
    print("h2", len(re.findall(rb"<h2[ >]", b)))
    print("tables", len(re.findall(rb"<table[ >]", b)))
    print("em", len(re.findall(rb"<em[ >]", b)), "(expect 0)")
    print("0x0C", b.count(b"\x0c"), "(expect 0)")
    print("leftover", b.count(b"{content}") + b.count(b"{toc}"), "(expect 0)")


if __name__ == "__main__":
    main()
