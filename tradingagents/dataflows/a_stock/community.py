"""社区情绪层：东方财富股吧散户讨论 → LLM 可消费文本。

数据源: guba.eastmoney.com 个股吧帖子列表（服务端直出 HTML 表格，实测无需
JS 渲染）。默认排序为热门混排，不严格按时间，故抓取后统一按时间过滤排序。

引擎链:
1. requests 直连（走 _em_get 令牌桶限流）——主引擎，实测返回完整列表
2. crawl4ai 渲染兜底——直连 HTML 缺列表（反爬升级/JS 壳）时自动接管一次，
   未安装时给出可选依赖提示（pyproject extra `community`），不阻塞主流程

公开入口:
- get_community_sentiment(ticker, curr_date="", look_back_days=5, ...) -> str
"""

from __future__ import annotations

import asyncio
import re
import threading
from datetime import datetime, timedelta
from html import unescape

from . import _common
from ._common import logger, _em_get

_GUBA_LIST_URL = "https://guba.eastmoney.com/list,{code}_{page}.html"
_GUBA_HEADERS = {
    "User-Agent": _common._UA,
    "Referer": "https://guba.eastmoney.com/",
}
_SOURCE_LABEL = "东方财富股吧 (guba.eastmoney.com)"

_ROW_RE = re.compile(r'<tr class="listitem[^"]*">(.*?)</tr>', re.S)


def _parse_guba_rows(html: str) -> list[dict]:
    """解析股吧列表页 HTML → 行 dict 列表（字段缺失容忍，不抛异常）。

    兼容两种形态（实测 2026-10-06）：
    - 直连版: <tr class="listitem">，锚点带 data-postid，<div class="update">
    - 渲染版(crawl4ai): <tr class="listitem ">（尾随空格），锚点无 data-postid
      但 href 含唯一 id，<div class="update mod_time">
    """
    rows = []
    for chunk in _ROW_RE.findall(html):
        reads = re.search(r'<div class="read[^"]*">(\d+)</div>', chunk)
        replies = re.search(r'<div class="reply[^"]*">(\d+)</div>', chunk)
        title_a = re.search(r'<div class="title[^"]*"><a ([^>]+)>(.*?)</a>', chunk, re.S)
        author = re.search(r'<div class="author[^"]*">.*?<a[^>]*>([^<]*)</a>', chunk, re.S)
        updated = re.search(r'<div class="update[^"]*">([^<]*)</div>', chunk)
        if not title_a:
            continue
        attrs = title_a.group(1)
        href_m = re.search(r'href="([^"]+)"', attrs)
        postid_m = re.search(r'data-postid="(\d+)"', attrs)
        href = href_m.group(1) if href_m else ""
        title = unescape(re.sub(r"<[^>]+>", "", title_a.group(2))).strip()
        # post_id：data-postid 优先，缺失时用 href 末段（剥掉 query/fragment）作去重键
        post_id = postid_m.group(1) if postid_m else (
            href.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0]
        )
        rows.append(
            {
                "post_id": post_id,
                "title": title,
                "url": "https:" + href if href.startswith("//") else href,
                "author": unescape(author.group(1)).strip() if author else "",
                "reads": int(reads.group(1)) if reads else 0,
                "replies": int(replies.group(1)) if replies else 0,
                "time_str": updated.group(1).strip() if updated else "",
            }
        )
    return rows


def _parse_guba_time(s: str, now: datetime) -> datetime | None:
    """股吧时间字段："MM-DD HH:MM"（默认当年）或 "YYYY-MM-DD[ HH:MM]"。

    当年解释若落在 1 天以上的未来，回退为上一年（跨年残留）。
    """
    s = (s or "").strip()
    m = re.fullmatch(r"(\d{2})-(\d{2}) (\d{2}):(\d{2})", s)
    if m:
        try:
            dt = now.replace(
                year=now.year, month=int(m.group(1)), day=int(m.group(2)),
                hour=int(m.group(3)), minute=int(m.group(4)), second=0, microsecond=0,
            )
        except ValueError:
            return None
        if (dt - now).total_seconds() > 86400:
            try:
                dt = dt.replace(year=dt.year - 1)
            except ValueError:
                return None
        return dt
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2}))?", s)
    if m:
        try:
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4) or 0), int(m.group(5) or 0),
            )
        except ValueError:
            return None
    return None


def _run_async(coro):
    """同步上下文执行协程；已处于事件循环内时起独立线程跑（Streamlit/agent 均为同步线程，此为防御）。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict = {}

    def _target():
        loop = asyncio.new_event_loop()
        try:
            result["value"] = loop.run_until_complete(coro)
        finally:
            loop.close()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=90)
    return result.get("value")


def _crawl_render_html(url: str) -> str | None:
    """crawl4ai 渲染兜底：直连拿不到列表时用无头浏览器取一次 HTML。

    未安装 crawl4ai 返回 None（调用方据此给出降级说明）。
    """
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    except ImportError:
        return None

    async def _run() -> str | None:
        browser_cfg = BrowserConfig(headless=True)
        run_cfg = CrawlerRunConfig(page_timeout=30000, cache_mode=CacheMode.BYPASS)
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url, config=run_cfg)
            return result.html if result.success else None

    try:
        return _run_async(_run())
    except Exception as e:
        logger.warning("crawl4ai 渲染失败 %s: %s", url, e)
        return None


def _fetch_guba_pages(code: str, max_pages: int) -> tuple[list[dict], bool]:
    """抓取股吧列表前 max_pages 页，按 post_id 跨页去重（默认排序为热门混排，
    置顶/热帖跨页重复出现是常态）。返回 (行列表, 是否动用了渲染兜底)。"""
    all_rows: list[dict] = []
    seen_ids: set[str] = set()
    used_render = False
    for page in range(1, max_pages + 1):
        url = _GUBA_LIST_URL.format(code=code, page=page)
        try:
            resp = _em_get(url, headers=_GUBA_HEADERS, timeout=15)
            resp.raise_for_status()
            rows = _parse_guba_rows(resp.text)
        except Exception as e:
            logger.warning("股吧列表抓取失败 %s page%d: %s", code, page, e)
            continue

        if not rows and page == 1 and not used_render:
            # 反爬/JS 壳场景：直连 HTML 无列表 → 渲染兜底接管一次
            rendered = _crawl_render_html(url)
            used_render = True
            if rendered:
                rows = _parse_guba_rows(rendered)
        for r in rows:
            if r["post_id"] and r["post_id"] in seen_ids:
                continue
            if r["post_id"]:
                seen_ids.add(r["post_id"])
            all_rows.append(r)
    return all_rows, used_render


def get_community_sentiment(
    ticker,
    curr_date: str = "",
    look_back_days: int = 5,
    max_pages: int = 2,
    max_posts: int = 60,
) -> str:
    """获取东方财富股吧散户讨论样本（帖子标题/阅读/评论数，按时间倒序）。

    情绪判断由调用方 LLM 基于样本完成；本工具不做情绪打分（量化=伪精确）。
    失败一律返回错误说明字符串，不抛异常（与公告层同约定）。
    """
    try:
        code = _common._normalize_ticker(str(ticker))
    except Exception as e:
        logger.warning("股吧查询代码无法解析 %r: %s", ticker, e)
        return f"[股吧查询需要 6 位数字股票代码，收到: {ticker}（解析失败: {e}）]"
    if not re.fullmatch(r"\d{6}", code or ""):
        return f"[股吧查询需要 6 位数字股票代码，收到: {ticker}]"

    look_back_days = max(1, min(int(look_back_days or 5), 30))
    max_pages = max(1, min(int(max_pages or 2), 5))
    now = datetime.now()

    rows, used_render = _fetch_guba_pages(code, max_pages)
    if not rows:
        hint = (
            "；crawl4ai 渲染兜底"
            + ("已尝试仍未取得" if used_render else "未启用（未安装，安装: pip install crawl4ai 后执行 crawl4ai-setup）")
        )
        return f"[股吧数据获取失败: 未取得帖子列表{hint}]"

    window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start -= timedelta(days=look_back_days - 1)

    dated = []
    unparsed = 0
    for r in rows:
        dt = _parse_guba_time(r["time_str"], now)
        if dt is None:
            unparsed += 1
            continue
        r["dt"] = dt
        dated.append(r)

    in_window = [r for r in dated if r["dt"] >= window_start]
    in_window.sort(key=lambda r: r["dt"], reverse=True)
    sample = in_window[:max_posts]

    total_reads = sum(r["reads"] for r in sample)
    total_replies = sum(r["replies"] for r in sample)

    disclaimer = _common._realtime_disclaimer(curr_date, "股吧讨论")
    today = now.strftime("%Y-%m-%d %H:%M")
    span = (
        f"{sample[-1]['dt']:%Y-%m-%d %H:%M} ~ {sample[0]['dt']:%Y-%m-%d %H:%M}"
        if sample
        else "无"
    )

    lines = [
        f"## 股吧社区讨论（{code}）",
        f"来源: {_SOURCE_LABEL}，抓取于 {today}",
        f"窗口: 最近 {look_back_days} 天（{window_start:%Y-%m-%d} 起），"
        f"样本 {len(sample)} 帖，累计阅读 {total_reads} 次 / 评论 {total_replies} 条，"
        f"时间跨度 {span}",
        "（样本为股吧默认排序前 "
        f"{max_pages} 页，热门混排非全量，仅供情绪判断参考）",
    ]
    if disclaimer:
        lines.append(disclaimer.strip())
    if not sample:
        lines.append(
            f"[窗口内样本 0 帖：共解析 {len(dated)} 帖"
            f"（{unparsed} 帖时间不可解析），均落在窗口外——"
            "该股近期可能讨论极冷清，而非数据故障]"
        )
        return "\n".join(lines)

    lines += [
        "",
        "| # | 时间 | 阅读 | 评论 | 标题 |",
        "|---|------|------|------|------|",
    ]
    for i, r in enumerate(sample, 1):
        title = r["title"] if len(r["title"]) <= 60 else r["title"][:57] + "..."
        lines.append(
            f"| {i} | {r['dt']:%m-%d %H:%M} | {r['reads']} | {r['replies']} | {title} |"
        )

    lines += [
        "",
        "> 数据说明: 以上为股吧真实帖子样本，情绪方向/强度/转折请基于样本判断；"
        "样本不足以支撑结论时明确标注 [数据缺失: 社区讨论样本不足]，勿凭空推断。",
    ]
    return "\n".join(lines)
