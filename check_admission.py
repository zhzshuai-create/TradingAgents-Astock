"""快速查看三位导师的招生信息"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

TARGETS = [
    ("唐小川", "http://faculty.cdut.edu.cn/xiaochuantang/zh_CN/index.htm"),
    ("王洪辉", "http://faculty.cdut.edu.cn/wanghonghui/zh_CN/index.htm"),
    ("李军",   "http://faculty.cdut.edu.cn/LJ1234567891011121314151617181920/zh_CN/index.htm"),
]

USER_DATA = Path.home() / ".playwright-cdut-check"


async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA),
            headless=False,
            args=["--disable-blink-features=AutomationControlled","--no-sandbox","--disable-infobars","--window-size=1366,768"],
            viewport={"width":1366,"height":768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # 建会话
        print("[*] 建立会话...")
        await page.goto("https://faculty.cdut.edu.cn/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        for name, url in TARGETS:
            print(f"\n{'='*60}")
            print(f"  访问: {name}")
            print(f"  {url}")
            print(f"{'='*60}")

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # 等 WAF 或内容
            for _ in range(12):
                await page.wait_for_timeout(3000)
                length = await page.evaluate("() => document.body.innerText.trim().length")
                if length > 80:
                    break

            # 获取全文
            full_text = await page.evaluate("() => document.body.innerText")

            # 找招生相关段落
            lines = full_text.split("\n")
            in_recruit = False
            recruit_lines = []
            for line in lines:
                line = line.strip()
                if not line:
                    if in_recruit:
                        recruit_lines.append("")
                    continue
                if any(kw in line for kw in ["招生信息","招生要求","报考条件","招生","研究生招生"]):
                    in_recruit = True
                if in_recruit:
                    recruit_lines.append(line)

            if recruit_lines:
                print("\n  [招生相关信息]")
                for l in recruit_lines[:30]:
                    print(f"  {l}")
            else:
                print("\n  [未找到招生相关内容]")

            # 也打印"个人简介"附近
            print("\n  [个人简介 / 研究方向 附近]")
            for kw in ["个人简介", "研究方向", "研究领域", "团队"]:
                idx = full_text.find(kw)
                if idx >= 0:
                    snippet = full_text[max(0,idx):idx+300]
                    print(f"  --- {kw} ---")
                    print(f"  {snippet[:300]}")
                    print()

            await page.wait_for_timeout(1000)

        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
