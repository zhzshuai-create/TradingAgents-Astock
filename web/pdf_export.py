"""Generate PDF reports from analysis results using fpdf2."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import fpdf as _fpdf_mod
from fpdf import FPDF
from fpdf.enums import WrapMode

from web.stock_display import normalize_stock_mentions, stock_display_label
from web.text_utils import strip_think_tags


# fpdf2 (maintained fork) and the abandoned pyfpdf 1.x BOTH import as `fpdf`, and
# installing both leaves whichever was installed last on disk. pyfpdf 1.x encodes
# every page as latin-1, so any Chinese character raises a cryptic
# `UnicodeEncodeError: 'latin-1' codec can't encode` deep inside the library
# (issue #54). Detect the wrong library up front and tell the user exactly how to
# fix it, instead of letting the PDF blow up mid-render.
_FPDF_VERSION = getattr(_fpdf_mod, "__version__", None) or getattr(_fpdf_mod, "FPDF_VERSION", "0")

_PDF_FONT_ENV = "TRADINGAGENTS_PDF_FONT"
_PDF_BOLD_FONT_ENV = "TRADINGAGENTS_PDF_BOLD_FONT"

_FONT_CANDIDATES = [
    (
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ),
    (
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ),
    (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ),
    (
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    ),
    (
        "/usr/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/noto-cjk/NotoSansCJKsc-Bold.otf",
    ),
    (
        "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansSC-Bold.ttf",
    ),
    (
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ),
    (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ),
    (
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
    ),
    (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
    ),
    (
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simhei.ttf",
    ),
]

_FONT_NAME_CANDIDATES = [
    ("WenQuanYi Micro Hei", "Regular"),
    ("WenQuanYi Zen Hei", "Regular"),
    ("Noto Sans CJK SC", "Regular"),
    ("Noto Sans CJK SC", "Bold"),
    ("Noto Sans SC", "Regular"),
    ("Noto Sans SC", "Bold"),
    ("Source Han Sans SC", "Regular"),
    ("Source Han Sans SC", "Bold"),
]

_FONT_FILE_PATTERNS = (
    "wqy-microhei.ttc",
    "wqy-zenhei.ttc",
    "NotoSansCJK-Regular.ttc",
    "NotoSansCJK-Bold.ttc",
    "NotoSansCJKsc-Regular.otf",
    "NotoSansCJKsc-Bold.otf",
    "NotoSansSC-Regular.ttf",
    "NotoSansSC-Bold.ttf",
    "SourceHanSansSC-Regular.otf",
    "SourceHanSansSC-Bold.otf",
    "DroidSansFallbackFull.ttf",
)

_CJK_FONT_MARKERS = (
    "NotoSansCJK",
    "NotoSansSC",
    "NotoSerifCJK",
    "SourceHanSans",
    "SourceHanSerif",
    "wqy-",
    "DroidSansFallback",
    "PingFang",
    "STHeiti",
    "msyh",
    "simhei",
)

_TTC_SC_FACE_INDEXES = {
    "NotoSansCJK-Regular.ttc": 2,
    "NotoSansCJK-Bold.ttc": 2,
    "NotoSerifCJK-Regular.ttc": 2,
    "NotoSerifCJK-Bold.ttc": 2,
}

_SINGLE_FACE_BOLD_FALLBACKS = {
    "wqy-microhei.ttc",
    "wqy-zenhei.ttc",
    "DroidSansFallbackFull.ttf",
}


class PDFExportError(RuntimeError):
    """Raised when the PDF report cannot be exported."""


def _ensure_fpdf2() -> None:
    try:
        major = int(str(_FPDF_VERSION).split(".")[0])
    except (ValueError, IndexError):
        major = 0
    if major < 2:
        raise RuntimeError(
            f"检测到旧版 fpdf (pyfpdf {_FPDF_VERSION})，它用 latin-1 编码、无法处理中文，"
            "会导致 PDF 导出崩溃（issue #54）。请执行：\n"
            '    pip uninstall -y fpdf && pip install "fpdf2>=2.8.0"\n'
            "（fpdf 与 fpdf2 都以 `fpdf` 名称导入、互相冲突，必须卸载旧的 fpdf），"
            "或改用「下载 Markdown」导出。"
        )


def _font_missing_message() -> str:
    candidates = ", ".join(regular for regular, _ in _FONT_CANDIDATES[:4])
    return (
        "PDF 导出需要可嵌入的 Unicode 中文字体。请优先安装 fonts-wqy-microhei，"
        f"或设置 {_PDF_FONT_ENV}=/path/to/wqy-microhei.ttc。"
        f"已检查的常见路径包括: {candidates}"
    )


def _env_font_path(env_name: str) -> Path | None:
    configured = os.getenv(env_name)
    if not configured:
        return None

    path = Path(configured).expanduser()
    if not path.exists():
        raise PDFExportError(f"{env_name} 指向的字体文件不存在: {path}")
    return path


def _is_likely_cjk_font(path: Path) -> bool:
    return any(marker in path.name for marker in _CJK_FONT_MARKERS)


def _font_search_roots() -> list[Path]:
    roots = [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path("~/.local/share/fonts").expanduser(),
        Path("~/.fonts").expanduser(),
    ]
    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        roots.append(Path(xdg_data_home).expanduser() / "fonts")
    return roots


def _find_font_file(pattern: str) -> Path | None:
    for root in _font_search_roots():
        if not root.exists():
            continue
        matches = sorted(root.rglob(pattern))
        if matches:
            return matches[0]
    return None


def _font_from_fontconfig(family: str, style: str) -> Path | None:
    try:
        output = subprocess.check_output(
            ["fc-match", "-f", "%{file}", f"{family}:style={style}"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None

    if not output:
        return None

    path = Path(output)
    if path.exists() and _is_likely_cjk_font(path):
        return path
    return None


def _discover_cjk_fonts() -> tuple[Path, Path] | None:
    discovered: dict[str, Path] = {}

    for pattern in _FONT_FILE_PATTERNS:
        path = _find_font_file(pattern)
        if path:
            discovered[pattern] = path

    regular = (
        discovered.get("wqy-microhei.ttc")
        or discovered.get("wqy-zenhei.ttc")
        or discovered.get("NotoSansCJK-Regular.ttc")
        or discovered.get("NotoSansCJKsc-Regular.otf")
        or discovered.get("NotoSansSC-Regular.ttf")
        or discovered.get("SourceHanSansSC-Regular.otf")
        or discovered.get("DroidSansFallbackFull.ttf")
    )
    if regular and regular.name in _SINGLE_FACE_BOLD_FALLBACKS:
        return regular, regular

    bold = (
        discovered.get("NotoSansCJK-Bold.ttc")
        or discovered.get("NotoSansCJKsc-Bold.otf")
        or discovered.get("NotoSansSC-Bold.ttf")
        or discovered.get("SourceHanSansSC-Bold.otf")
        or regular
    )
    if regular and bold:
        return regular, bold

    for family, style in _FONT_NAME_CANDIDATES:
        font_path = _font_from_fontconfig(family, style)
        if not font_path:
            continue
        if style == "Bold" and regular:
            return regular, font_path
        if style != "Bold":
            return font_path, font_path

    return None


def _find_cjk_fonts() -> tuple[Path, Path]:
    env_regular = _env_font_path(_PDF_FONT_ENV)
    if env_regular:
        return env_regular, _env_font_path(_PDF_BOLD_FONT_ENV) or env_regular

    for regular_path, bold_path in _FONT_CANDIDATES:
        regular = Path(regular_path)
        if regular.exists():
            bold = Path(bold_path)
            return regular, bold if bold.exists() else regular

    discovered = _discover_cjk_fonts()
    if discovered:
        return discovered

    raise PDFExportError(_font_missing_message())


def _collection_font_number(path: Path) -> int:
    """Select the Simplified Chinese face from known CJK font collections."""
    return _TTC_SC_FACE_INDEXES.get(path.name, 0)


def _strip_md_inline(text: str) -> str:
    """Remove inline markdown formatting: **bold**, *italic*, `code`, [link](url)."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    return text


def _compact_inline_text(text: str) -> str:
    """Collapse table/alignment whitespace that would create wide PDF gaps."""
    return re.sub(r"[ \t\u3000]{2,}", " ", text).strip()


# ── 导出文本清洗：框架解析标记 / 裸代码围栏 / 跨章节重复段落 ──
# 2026-10-06 首份 MiMo 报告评审实锤的三处工程瑕疵，在导出层统一收口
# （_collect_sections 是 PDF 与 Markdown 双格式共用源头，一次清洗两格式受益）

_FINAL_PROPOSAL_RE = re.compile(
    r"^\s*final\s+transaction\s+proposal\s*[:：].*$", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"^\s*```.*$")
# 短于此(归一化后)的行是标题/标签行，不参与去重，避免误杀。
# 中文信息密度高：30 字已是一行完整正文句，而标题/标签行通常 <10 字
_DEDUP_MIN_CHARS = 30


def strip_framework_markers(text: str) -> str:
    """剥离框架信号解析标记行（FINAL TRANSACTION PROPOSAL: X）。

    该标记是框架要求 agent 输出的信号解析锚点（信号值已在封面与章节
    标题展示），属管道内部约定，不应出现在面向用户的报告正文里。
    """
    return "\n".join(
        ln for ln in text.split("\n") if not _FINAL_PROPOSAL_RE.match(ln))


def strip_code_fences(text: str) -> str:
    """剥离裸 markdown 代码围栏行（``` 与 ```lang），围栏内文本保留。"""
    return "\n".join(
        ln for ln in text.split("\n") if not _CODE_FENCE_RE.match(ln))


def _dedup_key(line: str) -> str:
    """去重键：剥离空白与标点后小写——容忍导出重排造成的格式差异。"""
    return re.sub(r"[\W_]+", "", line, flags=re.UNICODE).lower()


def dedup_paragraphs(text: str, seen: set[str] | None = None) -> str:
    """行级去重（文内 + 跨章节共用同一个 seen 集合）。

    实测问题：决策文本在「交易员决策 / 最终投资建议 / 最终决策」三节
    整段重复。归一化长度 >= _DEDUP_MIN_CHARS 的行第二次出现即丢弃；
    整节重复清空后由调用方跳过空节。
    """
    seen = seen if seen is not None else set()
    kept: list[str] = []
    for para in text.split("\n"):
        key = _dedup_key(para)
        if len(key) >= _DEDUP_MIN_CHARS:
            if key in seen:
                continue
            seen.add(key)
        kept.append(para)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def _format_table_cells(cells: list[str]) -> str:
    cleaned = [_compact_inline_text(_strip_md_inline(cell)) for cell in cells]
    cleaned = [cell for cell in cleaned if cell]
    return " | ".join(cleaned)


def _signal_color(signal: str) -> tuple[int, int, int]:
    s = signal.upper()
    if "BUY" in s:
        return (34, 197, 94)
    if "SELL" in s:
        return (239, 68, 68)
    return (251, 191, 36)


_REPORT_SECTIONS = [
    ("market_report", "技术分析报告"),
    ("sentiment_report", "市场情绪报告"),
    ("news_report", "新闻舆情报告"),
    ("fundamentals_report", "基本面报告"),
    ("policy_report", "政策分析报告"),
    ("hot_money_report", "游资追踪报告"),
    ("lockup_report", "解禁/减持报告"),
]

# 章节名 → 数据图表图注（与 report_charts._CHART_BUILDERS 的章节键对应）
_CHART_CAPTIONS = {
    "技术分析报告": "图1 近90个交易日日K蜡烛、均线与成交量（来源：通达信/新浪）",
    "市场情绪报告": "图4 融资余额日度变化与杠杆资金动向（来源：东方财富）",
    "新闻舆情报告": "图5 个股新闻关注度分布（近30个自然日，来源：东方财富）",
    "基本面报告": "图2 估值路径：TTM 与一致预期前向 PE（来源：腾讯/同花顺）",
    "游资追踪报告": "图3 近20个交易日主力/超大单净流入（来源：东方财富）",
    "解禁/减持报告": "图6 限售解禁批次时间轴与占比（来源：东方财富）",
    "最终决策": "图7 关键价位地图：现价/MA50/布林带/涨跌停（来源：通达信/腾讯）",
}


class _ReportPDF(FPDF):
    def __init__(
        self,
        ticker: str,
        trade_date: str,
        signal: str,
        final_state: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.ticker = ticker
        self.ticker_label = stock_display_label(ticker, final_state)
        self.trade_date = trade_date
        self.signal = signal
        regular_font, bold_font = _find_cjk_fonts()

        try:
            self.add_font(
                "CJK",
                "",
                str(regular_font),
                collection_font_number=_collection_font_number(regular_font),
            )
            self.add_font(
                "CJK",
                "B",
                str(bold_font),
                collection_font_number=_collection_font_number(bold_font),
            )
        except Exception as exc:
            raise PDFExportError(
                f"无法加载 PDF 中文字体: {regular_font}。"
                f"请换一个 TTF/OTF/TTC 字体并通过 {_PDF_FONT_ENV} 指定。"
            ) from exc

    def _use_font(self, style: str = "", size: int = 10) -> None:
        self.set_font("CJK", style, size)

    def _text_block_width(self) -> float:
        return self.w - self.l_margin - self.r_margin

    def _write_multicell(self, height: float, text: str, **kwargs: Any) -> None:
        self.set_x(self.l_margin)
        kwargs.setdefault("align", "L")
        kwargs.setdefault("wrapmode", WrapMode.CHAR)
        self.multi_cell(self._text_block_width(), height, text, **kwargs)

    def header(self) -> None:
        self._use_font("", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 6, f"A股多Agent投研分析  |  {self.ticker_label}  |  {self.trade_date}", align="C")
        self.ln(8)
        self.set_draw_color(60, 60, 60)
        self.line(10, self.get_y(), self.w - 10, self.get_y())
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-15)
        self._use_font("", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="C")
        self.ln(4)
        self._use_font("", 6)
        self.set_text_color(160, 160, 160)
        self.cell(0, 4, "仅供学习研究，不构成投资建议", align="C")

    def add_cover(self) -> None:
        self.add_page()
        self.ln(60)

        self._use_font("B", 24)
        self.set_text_color(255, 90, 31)
        self.cell(0, 12, "A股多Agent投研分析报告", align="C")
        self.ln(20)

        self._use_font("B", 36)
        self.set_text_color(30, 30, 30)
        self.cell(0, 18, self.ticker_label, align="C")
        self.ln(16)

        self._use_font("", 14)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, f"分析日期: {self.trade_date}", align="C")
        self.ln(8)
        self.cell(0, 10, f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="C")
        self.ln(20)

        r, g, b = _signal_color(self.signal)
        self._use_font("B", 40)
        self.set_text_color(r, g, b)
        self.cell(0, 20, self.signal.upper(), align="C")
        self.ln(20)

        self._use_font("", 9)
        self.set_text_color(120, 120, 120)
        self._write_multicell(
            5,
            "免责声明: 本报告由 AI 多 Agent 系统自动生成, 仅供学习研究与技术演示, "
            "不构成任何投资建议。投资决策请咨询持牌专业机构。"
            "使用本报告所产生的任何损失由使用者自行承担。",
            align="C",
        )

    def add_section(self, title: str, content: str) -> None:
        self.add_page()
        self._use_font("B", 16)
        self.set_text_color(255, 90, 31)
        self.cell(0, 10, title)
        self.ln(12)

        cleaned = strip_think_tags(content)
        self._render_markdown(cleaned)

    def add_chart(self, image_path: Path, caption: str) -> None:
        """在章节文字后插入数据图表（等比缩放，需要时自动换页）。"""
        try:
            from PIL import Image  # fpdf2 依赖链自带 pillow

            with Image.open(image_path) as im:
                w_px, h_px = im.size
        except Exception as exc:  # noqa: BLE001 — 图插入失败只跳过不阻塞
            import logging

            logging.getLogger(__name__).warning("图表插入失败，跳过: %s", exc)
            return

        max_w = self._text_block_width()
        max_h = self.h - self.t_margin - self.b_margin - 20  # 预留标题行
        w = max_w
        h = w * h_px / w_px
        if h > max_h:
            h = max_h
            w = h * w_px / h_px
        if self.will_page_break(h + 14):
            self.add_page()
        self._use_font("", 8)
        self.set_text_color(110, 110, 110)
        self.cell(0, 6, caption, align="C")
        self.ln(8)
        self.image(str(image_path), x=(self.w - w) / 2, w=w, h=h)
        self.ln(2)

    def _render_markdown(self, text: str) -> None:
        """Render markdown-formatted text with basic styling."""
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Empty line → small vertical gap
            if not stripped:
                self.ln(3)
                i += 1
                continue

            # Headings: ### → 11pt, ## → 13pt, # → 14pt
            if stripped.startswith("###"):
                self._use_font("B", 11)
                self.set_text_color(50, 50, 50)
                self.cell(0, 7, _compact_inline_text(stripped.lstrip("#")))
                self.ln(8)
                i += 1
                continue
            if stripped.startswith("##"):
                self._use_font("B", 13)
                self.set_text_color(40, 40, 40)
                self.cell(0, 8, _compact_inline_text(stripped.lstrip("#")))
                self.ln(9)
                i += 1
                continue
            if stripped.startswith("#"):
                self._use_font("B", 14)
                self.set_text_color(255, 90, 31)
                self.cell(0, 9, _compact_inline_text(stripped.lstrip("#")))
                self.ln(10)
                i += 1
                continue

            # Horizontal rule
            if stripped in ("---", "***", "___"):
                self.set_draw_color(180, 180, 180)
                y = self.get_y() + 2
                self.line(10, y, self.w - 10, y)
                self.ln(6)
                i += 1
                continue

            # Bullet points (-, *, numbered)
            if re.match(r"^[-*]\s", stripped) or re.match(r"^\d+[.)]\s", stripped):
                self._use_font("", 10)
                self.set_text_color(40, 40, 40)
                if re.match(r"^[-*]\s", stripped):
                    bullet = "  •  "
                    body = stripped[2:].strip()
                else:
                    m = re.match(r"^(\d+[.)])\s*(.*)", stripped)
                    bullet = f"  {m.group(1)} "
                    body = m.group(2)
                body = _compact_inline_text(_strip_md_inline(body))
                self._write_multicell(5.5, bullet + body)
                i += 1
                continue

            # Table rows (|col|col|) → render compactly; fixed-width spacing
            # creates large visual gaps in proportional PDF fonts.
            if stripped.startswith("|") and stripped.endswith("|"):
                # Skip separator rows like |---|---|
                if re.match(r"^\|[-:\s|]+\|$", stripped):
                    i += 1
                    continue
                self._use_font("", 9)
                self.set_text_color(60, 60, 60)
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                row_text = _format_table_cells(cells)
                self._write_multicell(5, row_text)
                i += 1
                continue

            # Regular paragraph — collect consecutive non-special lines
            para_lines = []
            while i < len(lines):
                ln = lines[i].strip()
                if not ln or ln.startswith("#") or ln.startswith("|") or re.match(r"^[-*]\s", ln) or re.match(r"^\d+[.)]\s", ln) or ln in ("---", "***", "___"):
                    break
                para_lines.append(ln)
                i += 1

            if para_lines:
                self._use_font("", 10)
                self.set_text_color(40, 40, 40)
                para = " ".join(para_lines)
                para = _compact_inline_text(_strip_md_inline(para))
                self._write_multicell(5.5, para)
                self.ln(2)
                continue

            i += 1


def _collect_sections(
    final_state: dict[str, Any],
    ticker: str | None = None,
) -> list[tuple[str, str]]:
    """Assemble the (title, content) report sections shared by PDF & Markdown.

    Keeps both export formats in sync from a single source of truth.
    """
    sections: list[tuple[str, str]] = []
    # 跨章节去重只在「决策族」章节间生效（交易员决策/最终投资建议/风控评估/
    # 最终决策）——实测的整段重复发生在这四节之间。分析师报告/辩论内容被
    # 决策章节复述是合法综合（10-24 v2.6 报告实测：合法复述被误删只剩孤壳），
    # 不喂 seen；章节内去重对所有章节生效（同文内逐字重复恒为噪音）。
    decision_seen: set[str] = set()

    def _clean(text: str, cross: bool) -> str:
        """导出统一清洗：框架标记 → 代码围栏 → 去重（cross=参与跨章节）。"""
        cleaned = strip_code_fences(strip_framework_markers(text))
        if cross:
            return dedup_paragraphs(cleaned, decision_seen)
        return dedup_paragraphs(cleaned)

    for key, title in _REPORT_SECTIONS:
        content = final_state.get(key, "")
        if content:
            text = strip_think_tags(str(content))
            if ticker:
                text = normalize_stock_mentions(text, ticker, final_state)
            text = _clean(text, cross=False)
            if text:
                sections.append((title, text))

    debate = final_state.get("investment_debate_state")
    if debate and isinstance(debate, dict):
        parts = []
        if debate.get("bull_history"):
            parts.append(f"=== 多方论点 ===\n{debate['bull_history']}")
        if debate.get("bear_history"):
            parts.append(f"\n=== 空方论点 ===\n{debate['bear_history']}")
        if debate.get("judge_decision"):
            parts.append(f"\n=== 研究经理决策 ===\n{debate['judge_decision']}")
        if parts:
            text = strip_think_tags("\n".join(parts))
            if ticker:
                text = normalize_stock_mentions(text, ticker, final_state)
            text = _clean(text, cross=False)
            if text:
                sections.append(("多空辩论", text))

    trader_decision = final_state.get("trader_investment_decision", "")
    if trader_decision:
        text = strip_think_tags(str(trader_decision))
        if ticker:
            text = normalize_stock_mentions(text, ticker, final_state)
        text = _clean(text, cross=True)
        if text:
            sections.append(("交易员决策", text))

    inv_plan = final_state.get("investment_plan", "")
    if inv_plan:
        text = strip_think_tags(str(inv_plan))
        if ticker:
            text = normalize_stock_mentions(text, ticker, final_state)
        text = _clean(text, cross=True)
        if text:
            sections.append(("最终投资建议", text))

    risk = final_state.get("risk_debate_state")
    if risk and isinstance(risk, dict):
        parts = []
        for key_name, label in [("aggressive_history", "激进观点"),
                                 ("conservative_history", "保守观点"),
                                 ("neutral_history", "中性观点")]:
            if risk.get(key_name):
                parts.append(f"=== {label} ===\n{risk[key_name]}")
        if risk.get("judge_decision"):
            # 框架把同一文本同时存进 risk.judge_decision 与 final_trade_decision
            # （2026-10-06/10-24 两份真实报告实测逐字相同）——决策正文只在
            # 「最终决策」节渲染一次，风控评估不重复带出
            final_txt = str(final_state.get("final_trade_decision") or "")
            judge_txt = str(risk.get("judge_decision") or "")
            if not final_txt or _dedup_key(judge_txt) != _dedup_key(final_txt):
                parts.append(f"\n=== 风控决策 ===\n{judge_txt}")
        if parts:
            text = strip_think_tags("\n".join(parts))
            if ticker:
                text = normalize_stock_mentions(text, ticker, final_state)
            text = _clean(text, cross=True)
            if text:
                sections.append(("风控评估", text))

    final_decision = final_state.get("final_trade_decision", "")
    if final_decision:
        text = strip_think_tags(str(final_decision))
        if ticker:
            text = normalize_stock_mentions(text, ticker, final_state)
        text = _clean(text, cross=True)
        if text:
            sections.append(("最终决策", text))

    return sections


def generate_pdf(final_state: dict[str, Any], ticker: str, trade_date: str, signal: str) -> bytes:
    """Generate a PDF report and return it as bytes.

    Raises RuntimeError if the wrong fpdf library is installed (issue #54) or no
    CJK font is available on the system — callers should catch this and fall back
    to Markdown export.
    """
    _ensure_fpdf2()

    # 数据图表是增强项：生成/插入的任何失败都不阻塞导出（report_charts
    # 内部已按单图降级，这里再兜底导入/调度层的意外）。
    charts: dict[str, Path] = {}
    chart_dir: Path | None = None
    try:
        from web.report_charts import cleanup_chart_dir, generate_report_charts

        charts, chart_dir = generate_report_charts(ticker, trade_date)
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning("报告图表生成整体跳过: %s", exc)

    try:
        pdf = _ReportPDF(ticker, trade_date, signal, final_state)
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=20)

        pdf.add_cover()
        for title, content in _collect_sections(final_state, ticker):
            pdf.add_section(title, content)
            chart_path = charts.get(title)
            if chart_path:
                pdf.add_chart(chart_path, _CHART_CAPTIONS.get(title, "数据可视化"))

        return bytes(pdf.output())
    finally:
        if chart_dir is not None:
            from web.report_charts import cleanup_chart_dir

            cleanup_chart_dir(chart_dir)


def generate_markdown(final_state: dict[str, Any], ticker: str, trade_date: str, signal: str) -> str:
    """Generate a Markdown report. Font-free and always works — the safe export.

    This is the bulletproof alternative to PDF when the system lacks a CJK
    font (common on minimal Linux/Windows installs).
    """
    ticker_label = stock_display_label(ticker, final_state)
    out = [
        "# A股多Agent投研分析报告",
        "",
        f"- **股票代码**：{ticker_label}",
        f"- **分析日期**：{trade_date}",
        f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- **交易信号**：**{signal.upper()}**",
        "",
        "> 本报告由 AI 多 Agent 系统自动生成，仅供学习研究与技术演示，"
        "不构成任何投资建议。投资决策请咨询持牌专业机构，使用本报告所产生的"
        "任何损失由使用者自行承担。",
        "",
        "---",
        "",
    ]
    for title, content in _collect_sections(final_state, ticker):
        out.append(f"## {title}")
        out.append("")
        out.append(content)
        out.append("")

    return "\n".join(out)
