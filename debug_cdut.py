"""快速调试：查看详情页结构 + 翻页逻辑"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

USER_DATA = Path.home() / ".playwright-cdut-profile"


async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA),
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-infobars", "--window-size=1366,768"],
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # --- 任务1：看详情页结构 ---
        print("=" * 60)
        print("任务1: 访问多滨的详情页，看 HTML 结构")
        print("=" * 60)
        await page.goto("http://faculty.cdut.edu.cn/duobin/zh_CN/index.htm", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        detail_html = await page.content()
        Path(r"C:\Users\zhzsh\TradingAgents-astock\detail_sample.html").write_text(detail_html, encoding="utf-8")
        body_text = await page.evaluate("() => document.body.innerText.substring(0, 3000)")
        print(body_text)

        # --- 任务2：测试翻页 ---
        print("\n" + "=" * 60)
        print("任务2: 测试翻页逻辑")
        print("=" * 60)
        list_url = "https://faculty.cdut.edu.cn/xysy-lb.jsp?urltype=tsites.CollegeTeacherList&wbtreeid=1011&st=0&id=1068&lang=zh_CN"
        await page.goto(list_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # 打印分页区域的所有链接
        page_links = await page.evaluate("""
        () => {
            const links = document.querySelectorAll('.page a, .headStyle33o9svc32y a, td a, table a');
            const result = [];
            links.forEach(a => {
                result.push({text: a.textContent.trim(), href: a.href, className: a.className});
            });
            return result;
        }
        """)
        print("分页区域链接:")
        for l in page_links:
            print(f"  [{l['className']}] {l['text']} → {l['href']}")

        # 尝试点击"下页"
        try:
            next_link = page.locator("a:has-text('下页')")
            count = await next_link.count()
            print(f"\n找到 {count} 个'下页'链接")
            if count > 0:
                await next_link.first.click()
                await page.wait_for_timeout(2000)
                names = await page.evaluate("""
                () => {
                    const lis = document.querySelectorAll('ul.xz1 li h4.txt1');
                    return Array.from(lis).map(h => h.textContent.trim());
                }
                """)
                print(f"第2页教师: {names}")
        except Exception as e:
            print(f"点击失败: {e}")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
