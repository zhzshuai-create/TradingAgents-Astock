"""巨潮公告层：公告列表检索 + 公告 PDF 全文转 Markdown。

数据源: 巨潮资讯网 cninfo.com.cn（直连 HTTP，POST 表单接口）
- orgId 不按代码前缀拼猜（实测 601208 用 "gssh0" 前缀规则查询返回 0 条），
  一律走 topSearch/query 实查后进程内缓存
- 公告 PDF 直链 = https://static.cninfo.com.cn/ + adjunctUrl
- PDF 全文依赖可选依赖 markitdown[pdf]（pyproject extra `announcements`）；
  未安装时自动降级为仅返回公告列表并附安装提示，不阻塞分析流程

公开入口:
- get_announcements(ticker, start_date, end_date, ...) -> str
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests as _requests

from . import _common
from ._common import logger

_CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
_CNINFO_TOPSEARCH_URL = "https://www.cninfo.com.cn/new/information/topSearch/query"
_CNINFO_STATIC_BASE = "https://static.cninfo.com.cn/"
_CNINFO_HEADERS = {
    "User-Agent": _common._UA,
    "Referer": "https://www.cninfo.com.cn/new/disclosure",
    "Origin": "https://www.cninfo.com.cn",
}
_SOURCE_LABEL = "巨潮资讯网 (cninfo.com.cn)"

# 单份公告 PDF 体积上限，防异常大文件拖垮转换
_MAX_PDF_BYTES = 10 * 1024 * 1024
# 提取文本低于该阈值视为扫描件/无文本层
_MIN_PDF_TEXT_CHARS = 50

_org_id_cache: dict[str, str] = {}
_markitdown_engine = None


def _cninfo_ts_to_date(ts) -> str:
    """巨潮 announcementTime 为 Unix 毫秒时间戳，公告日期按北京时间口径。

    显式固定 Asia/Shanghai：CI 的 UTC 容器里用本地时区会把日期差成前一天。
    """
    try:
        return datetime.fromtimestamp(int(ts) / 1000, tz=ZoneInfo("Asia/Shanghai")).strftime(
            "%Y-%m-%d"
        )
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _get_org_id(code: str) -> str | None:
    """通过巨潮 topSearch 实查公司 orgId（进程内缓存）。"""
    if code in _org_id_cache:
        return _org_id_cache[code]

    resp = _requests.post(
        _CNINFO_TOPSEARCH_URL,
        data={"keyWord": code, "maxNum": "10"},
        headers=_CNINFO_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    for item in resp.json():
        if isinstance(item, dict) and item.get("code") == code:
            org_id = item.get("orgId")
            if org_id:
                _org_id_cache[code] = org_id
                return org_id
    logger.warning("cninfo topSearch 未找到 %s 的 orgId", code)
    return None


def _list_announcements(code: str, page_size: int = 30) -> list[dict]:
    """检索巨潮公告列表，按公告日期倒序。失败时抛异常由上层捕获。

    返回行: {title, type, date, pdf_url, size_kb, anno_id, adjunct_type}
    """
    org_id = _get_org_id(code)
    if not org_id:
        return []

    payload = {
        "stock": f"{code},{org_id}",
        "tabName": "fulltext",
        "pageSize": str(page_size),
        "pageNum": "1",
        "column": "",
        "category": "",
        "plate": "",
        "seDate": "",
        "searchkey": "",
        "secid": "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    resp = _requests.post(
        _CNINFO_QUERY_URL,
        data=payload,
        headers={**_CNINFO_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("announcements") or []

    rows = []
    for item in items:
        adjunct_url = item.get("adjunctUrl") or ""
        rows.append(
            {
                "title": (item.get("announcementTitle") or "").strip(),
                "type": item.get("announcementTypeName") or "",
                "date": _cninfo_ts_to_date(item.get("announcementTime")),
                "pdf_url": _CNINFO_STATIC_BASE + adjunct_url if adjunct_url else "",
                "size_kb": item.get("adjunctSize"),
                "anno_id": str(item.get("announcementId") or ""),
                "adjunct_type": (item.get("adjunctType") or "").upper(),
            }
        )
    return rows


def _normalize_date(value: str) -> str:
    """宽容解析日期：提取 yyyy-mm-dd 前缀，无法解析返回空串（视为不过滤）。"""
    m = re.search(r"\d{4}-\d{2}-\d{2}", (value or "").strip())
    if not m:
        return ""
    try:
        return datetime.strptime(m.group(0), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _pdf_cache_path(anno_id: str) -> str:
    return os.path.join(_common._cache_dir(), "announcements", f"{anno_id}.pdf")


def _download_pdf(pdf_url: str, anno_id: str) -> str | None:
    """下载公告 PDF 到缓存目录（annoId 命名，原子写），返回本地路径或 None。"""
    path = _pdf_cache_path(anno_id)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    resp = _requests.get(pdf_url, headers=_CNINFO_HEADERS, timeout=30)
    resp.raise_for_status()
    if len(resp.content) > _MAX_PDF_BYTES:
        logger.warning("公告 PDF 超过体积上限 %d 字节，跳过: %s", _MAX_PDF_BYTES, pdf_url)
        return None

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(resp.content)
    os.replace(tmp, path)
    return path


def _get_markitdown():
    """懒加载 MarkItDown 单例；未安装返回 None（降级为仅列表）。"""
    global _markitdown_engine
    if _markitdown_engine is None:
        try:
            from markitdown import MarkItDown
        except ImportError:
            return None
        _markitdown_engine = MarkItDown()
    return _markitdown_engine


def _convert_pdf_to_markdown(path: str) -> str:
    """PDF 转 Markdown 文本。失败抛异常由上层按份捕获。"""
    engine = _get_markitdown()
    if engine is None:
        raise RuntimeError("markitdown 未安装")
    result = engine.convert(path)
    return result.text_content or ""


def get_announcements(
    ticker,
    start_date: str = "",
    end_date: str = "",
    max_items: int = 15,
    with_content: bool = True,
    max_fulltext: int = 5,
    max_chars_per_doc: int = 4000,
) -> str:
    """获取公司公告列表及最近公告 PDF 全文摘录（巨潮资讯网）。

    失败一律返回错误说明字符串，不抛异常（route_to_vendor 有 fallback 链，
    抛异常只会触发无意义的跨厂商重试后 RuntimeError）。
    """
    try:
        code = _common._normalize_ticker(str(ticker))
    except Exception as e:
        # safe_ticker_component 对模式外输入会抛 ValueError；中文股票名则由
        # resolve_ticker 自动解析成代码（属平台既定能力，不算垃圾输入）
        logger.warning("公告查询代码无法解析 %r: %s", ticker, e)
        return f"[公告查询需要 6 位数字股票代码，收到: {ticker}（解析失败: {e}）]"
    if not re.fullmatch(r"\d{6}", code or ""):
        return f"[公告查询需要 6 位数字股票代码，收到: {ticker}]"

    date_from = _normalize_date(start_date)
    date_to = _normalize_date(end_date)

    try:
        rows = _list_announcements(code)
    except Exception as e:
        logger.warning("cninfo 公告列表获取失败 %s: %s", code, e)
        return f"[公告数据获取失败: {e}]"

    if date_from:
        rows = [r for r in rows if r["date"] and r["date"] >= date_from]
    if date_to:
        rows = [r for r in rows if r["date"] and r["date"] <= date_to]

    if not rows:
        return (
            f"[{code} 在 {date_from or '…'}~{date_to or '…'} 区间内未查询到公告"
            f"（可能代码有误或区间过远）]"
        )

    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"## 公司公告（{code}）",
        f"来源: {_SOURCE_LABEL}，抓取于 {today}",
        f"区间: {date_from or '不限'} ~ {date_to or '不限'}，命中 {len(rows)} 条"
        f"（列表最多展示 {max_items} 条，按公告日期倒序）",
        "",
        "| # | 日期 | 类型 | 标题 |",
        "|---|------|------|------|",
    ]
    for i, r in enumerate(rows[:max_items], 1):
        lines.append(f"| {i} | {r['date']} | {r['type']} | {r['title']} |")

    if not with_content:
        return "\n".join(lines)

    if _get_markitdown() is None:
        return "\n".join(
            lines
            + [
                "",
                "> ⚠️ 未安装 markitdown，仅返回公告列表。",
                "全文提取需安装可选依赖: pip install 'markitdown[pdf]'",
            ]
        )

    lines.append("")
    lines.append(
        f"## 公告全文摘录（最近 {max_fulltext} 份，每份最多 {max_chars_per_doc} 字）"
    )
    converted = 0
    for r in rows:
        if converted >= max_fulltext:
            break
        converted += 1
        header = f"### {converted}. [{r['date']}] {r['title']}"
        if r["adjunct_type"] != "PDF" or not r["pdf_url"]:
            lines += [header, "", f"[非 PDF 附件({r['adjunct_type'] or '未知类型'})，暂不支持全文提取]", ""]
            continue

        size_note = f"，{r['size_kb']}KB" if r["size_kb"] else ""
        lines += [header, f"PDF: {r['pdf_url']}{size_note}", ""]
        try:
            path = _download_pdf(r["pdf_url"], r["anno_id"])
            if not path:
                lines += ["[公告 PDF 下载失败或超过体积上限]", ""]
                continue
            text = _convert_pdf_to_markdown(path).strip()
            if len(text) < _MIN_PDF_TEXT_CHARS:
                lines += [f"[PDF 全文提取失败：疑似扫描件或无文本层，仅提取到 {len(text)} 字]", ""]
                continue
            if len(text) > max_chars_per_doc:
                text = text[:max_chars_per_doc] + f"\n\n[已截断: 原文 {len(text)} 字]"
            lines += [text, ""]
        except Exception as e:
            logger.warning("公告全文提取失败 %s (%s): %s", code, r["anno_id"], e)
            lines += [f"[公告全文提取失败: {e}]", ""]

    return "\n".join(lines)
