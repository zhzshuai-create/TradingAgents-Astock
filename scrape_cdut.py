"""
成都理工大学 教师详情补抓 v10 · 自恢复版
WAF 超时 → 自动关闭浏览器 → 等待冷却 → 新会话继续
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import asyncio, csv, shutil
from pathlib import Path
from playwright.async_api import async_playwright

USER_DATA_BASE = Path.home() / ".playwright-cdut-auto"
CSV_PATH = Path(r"C:\Users\zhzsh\TradingAgents-astock\cdut_teachers.csv")
FIELDS = ["name","url","photo","title","research","email","phone","office","education","college","_summary"]

WAF_TIMEOUT = 35   # WAF 挑战最多等 35 秒
COOLDOWN = 10      # 被封后冷却 10 秒再重开
MAX_ROUNDS = 10    # 最多重试 10 轮


def load_all():
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save(teachers):
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for t in teachers: w.writerow(t)


def has_detail(t):
    return any(t.get(k, "").strip() for k in ["title", "research", "email", "_summary"])


async def safe_goto(page, url):
    """带硬超时的导航。WAF 超时抛异常让外层重启"""
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    start = asyncio.get_event_loop().time()
    while True:
        await page.wait_for_timeout(2000)
        try:
            length = await page.evaluate(
                "() => document.body.innerText.trim().length")
            if length > 80:
                return True
        except:
            pass

        elapsed = asyncio.get_event_loop().time() - start
        if elapsed > WAF_TIMEOUT:
            return False  # WAF 挑战超时，触发外部重启


async def run_one_round(round_num):
    """一轮抓取：打开浏览器，逐个处理，直到 WAF 超时或全部完成"""
    teachers = load_all()
    need = [(i, t) for i, t in enumerate(teachers) if not has_detail(t)]

    if not need:
        return True  # 全部完成

    # 用轮次号区分用户目录，避免上一轮残留
    user_dir = Path(str(USER_DATA_BASE) + f"-r{round_num}")
    shutil.rmtree(str(user_dir), ignore_errors=True)

    print(f"\n{'='*50}")
    print(f"第 {round_num} 轮: 剩余 {len(need)} 位")
    print(f"{'='*50}")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled","--no-sandbox","--disable-infobars","--window-size=1366,768"],
            viewport={"width":1366,"height":768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # 建会话
        print("[*] 建会话...")
        ok = await safe_goto(page, "https://faculty.cdut.edu.cn/")
        if not ok:
            print("[!] 首页都无法加载，WAF 直接封了")
            await context.close()
            return False

        done_this_round = 0
        for idx, t in need:
            name = t["name"]
            print(f"  [{idx+1:02d}] {name}", end=" ", flush=True)

            await page.wait_for_timeout(1000)
            ok = await safe_goto(page, t["url"])

            if not ok:
                print("⏰ WAF 超时 → 结束本轮")
                break  # 本轮到此为止，让外层重启

            try:
                info = await page.evaluate("""
                () => {
                    const text = document.body.innerText;
                    if (!text || text.length < 20) return {};
                    const r = {};
                    const ex = (kws, key) => {
                        for (const kw of kws) {
                            const i = text.indexOf(kw);
                            if (i >= 0) {
                                const s = text.substring(i+kw.length).replace(/^[\\s：:：]+/,'');
                                const e = s.search(/[\\n\\r]/);
                                r[key] = (e>0?s.substring(0,e).trim():s.substring(0,60).trim());
                                return;
                            }
                        }
                    };
                    ex(['导师情况','职称','职务','职位'],'title');
                    ex(['研究方向','研究领域','研究兴趣','学术方向'],'research');
                    ex(['所在学院','学院'],'college');
                    ex(['学历'],'education');
                    ex(['通讯/办公地址','办公室','办公地点','办公地址'],'office');
                    ex(['办公电话','电话','手机','联系电话','Tel'],'phone');
                    const em = text.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/);
                    if (em) r.email = em[0];
                    r._summary = text.substring(0,500).replace(/\\s+/g,' ').trim();
                    return r;
                }""")
                t.update(info)
                title = info.get('title','')
                research = info.get('research','')
                email = info.get('email','')
                print(f"✓ 职称:{title or '-'} | 方向:{(research or '-')[:20]} | {email or '-'}")
            except Exception as e:
                print(f"✗ {e}")

            save(teachers)
            done_this_round += 1

        await context.close()

    # 本轮结束，看是否全部完成
    teachers = load_all()
    remaining = sum(1 for t in teachers if not has_detail(t))
    print(f"\n  本轮完成 {done_this_round} 位，剩余 {remaining} 位")
    return remaining == 0


async def main():
    for r in range(1, MAX_ROUNDS + 1):
        all_done = await run_one_round(r)
        if all_done:
            print(f"\n🎉 全部 28 位教师详情抓取完成！")
            break
        # 被 WAF 封了，冷却
        print(f"  [冷却 {COOLDOWN}s]...")
        await asyncio.sleep(COOLDOWN)
    else:
        print(f"\n⚠ {MAX_ROUNDS} 轮后仍未完成，请手动检查 CSV")

    # 最终统计
    teachers = load_all()
    done = sum(1 for t in teachers if has_detail(t))
    print(f"\n=== 最终: {done}/{len(teachers)} ===")
    print(f"CSV: {CSV_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
