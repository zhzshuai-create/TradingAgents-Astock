# -*- coding: utf-8 -*-
"""数据层白皮书 docx 构建（python-docx, 微软雅黑, 白色主题）.

用法: python docs/data_layer/build_doc.py
输出: 桌面/AStock_Pro_数据层工作原理.docx
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BASE = Path(__file__).resolve().parent
FIG = BASE / "figures"
OUT = Path(r"C:\Users\zhzsh\Desktop\AStock_Pro_数据层工作原理.docx")

INK = RGBColor(0x1B, 0x15, 0x10)
BRAND = RGBColor(0xA8, 0x40, 0x2F)
MUTED = RGBColor(0x6B, 0x62, 0x59)
FONT = "微软雅黑"


def set_font(run, size=10.5, bold=False, color=INK):
    run.font.name = FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def para(doc, text, size=10.5, bold=False, color=INK, align=None,
         space_after=6, indent=False):
    p = doc.add_paragraph()
    if align:
        p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.4
    if indent:
        p.paragraph_format.first_line_indent = Pt(21)
    set_font(p.add_run(text), size, bold, color)
    return p


def h1(doc, text):
    return para(doc, text, size=15, bold=True, color=BRAND, space_after=8)


def h2(doc, text):
    return para(doc, text, size=12, bold=True, color=INK, space_after=6)


def bullet(doc, text, bold_head=None):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.4
    if bold_head:
        set_font(p.add_run(bold_head), 10.5, True)
    set_font(p.add_run(text), 10.5)
    return p


def pic(doc, name, caption, width=16.2):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(FIG / name), width=Cm(width))
    para(doc, caption, size=9, color=MUTED,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=12)


def table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(cell.paragraphs[0].add_run(h), 9.5, True)
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), "F3EEE9")
        cell._tc.get_or_add_tcPr().append(shd)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            set_font(cells[i].paragraphs[0].add_run(str(v)), 9)
    if widths:
        for i, w in enumerate(widths):
            for r in t.rows:
                r.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


def main() -> None:
    doc = Document()
    for s in doc.sections:
        s.top_margin = s.bottom_margin = Cm(2.2)
        s.left_margin = s.right_margin = Cm(2.4)

    para(doc, "AStock Pro 数据层工作原理", size=22, bold=True, color=BRAND,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)
    para(doc, "从智能体工具调用到多源数据落盘 —— 架构、流程与可靠性机制",
         size=12, color=MUTED, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
    para(doc, "基于 TradingAgents-astock 仓库实际代码整理 · 2026-10",
         size=9, color=MUTED, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=16)

    # ── 一、总览 ──
    h1(doc, "一、数据层在系统中的位置")
    para(doc, "数据层位于智能体工具层与外部数据源之间，是整个系统输入侧的地基："
              "七位分析师（行情、新闻、基本面、舆情、政策、游资、解禁）的每一次数据获取，"
              "都经过统一路由进入 A 股数据包，再由数据包决定从哪个数据源、走什么通道、"
              "带哪些护栏去取数。它的设计目标只有一个：让上层的智能体永远拿到"
              "尽可能可靠、尽可能新鲜、且不含未来信息的数据，而把网络抖动、接口限流、"
              "反爬封锁、口径陷阱这些脏活全部挡在自己这一层。", indent=True)
    pic(doc, "fig1_architecture.png", "图 1  数据层总体架构：五层调用链 + 六大横切可靠性机制")

    h2(doc, "1.1 五层调用链")
    bullet(doc, "Streamlit 看板、分析报告页、命令行三种入口都会触发数据获取。", "交互层：")
    bullet(doc, "每位分析师持有若干 @tool 装饰的工具函数（如 get_stock_data、get_fundamentals），"
                "大模型通过函数调用发起取数请求，参数只有股票代码和日期。", "智能体工具层：")
    bullet(doc, "route_to_vendor(method) 按方法名查厂商配置，构造主厂商优先、"
                "其余厂商垫后的回退链依次尝试——系统配置为全 a_stock，直通不损失。", "统一路由层：")
    bullet(doc, "a_stock 包是全部 A 股数据能力的实现，其中 _common.py 是共享核心"
                "（代码解析、名称映射、缓存、限流、OHLCV 装配），其余六个模块按数据域拆分。", "A股数据包：")
    bullet(doc, "通达信走 TCP 7709 私有协议，其余走 HTTP；每家行为不同、脾气不同，"
                "数据层逐一适配。", "外部数据源：")

    h2(doc, "1.2 六大横切机制（本文主角）")
    para(doc, "右侧六项机制不属于任何单一数据域，而是像基础设施一样横切所有请求："
              "三级缓存管快，多源回退管活，统一限流管不被封，TLS 指纹兜底管被封之后，"
              "防前视管不穿越，容错契约管不炸。后文逐一展开。", indent=True)

    # ── 二、生命周期 ──
    h1(doc, "二、一次数据请求的完整旅程")
    para(doc, "以技术分析师取 601208 的日 K 线为例，一次请求从工具调用到返回共七步，"
              "其中③④两级缓存命中可跳过全部网络请求：", indent=True)
    pic(doc, "fig2_lifecycle.png", "图 2  一次数据请求的生命周期（含缓存命中与失败两条旁路）")
    table(doc,
          ["步骤", "发生什么", "设计意图"],
          [["① 工具调用", "大模型调用 get_stock_data(601208, 2026-10-24)", "入口统一：参数只有代码+日期"],
           ["② 统一路由", "route_to_vendor 查表分发", "厂商可配置、可替换、可回退"],
           ["③ 进程级缓存", "_TTLCache(512 条) 查同参数结果", "60 秒内重复请求零网络"],
           ["④ CSV 当日缓存", "~/.tradingagents/cache/ 下按股缓存日 K", "跨进程重启仍命中，只补增量"],
           ["⑤ 主源取数", "mootdx TCP 客户端（单例+线程锁）取 800 根", "通达信不限流、数据全"],
           ["⑥ 新浪兜底", "主源空/陈旧时 HTTP 补增量并合并去重", "单源故障不中断分析"],
           ["⑦ 防前视截断", "按分析日截断未来数据后返回", "回测与仿真不穿越"]],
          widths=[2.6, 7.2, 6.2])

    # ── 三、机制详解 ──
    h1(doc, "三、六大可靠性机制详解")

    h2(doc, "3.1 三级缓存：让重复请求零成本")
    para(doc, "分析一次标的期间，多位分析师常要同一份行情；看板刷新更是高频重复。"
              "缓存分三级、各管一段：UI 层 st.cache_data（TTL 10 秒~1 天，按数据新鲜度分级）→ "
              "核心层 _TTLCache（进程内 512 条 FIFO，跨分析师共享）→ 日 K CSV（当日有效，"
              "重启进程仍命中，只向数据源补当日增量）。层级越深、生命周期越长，"
              "命中收益从省一次 HTTP 提升到省全部网络。", indent=True)

    h2(doc, "3.2 多源回退：两层保险")
    para(doc, "第一层在厂商间：route_to_vendor 的回退链主厂商失败自动尝试备选厂商，"
              "系统可整体切换数据供应商而不改上层代码。第二层在厂商内：以日 K 为例，"
              "通达信 TCP 为主源、新浪 HTTP 为兜底——2026-09 通达信全网不可达的真实故障中，"
              "看板 K 线正是靠新浪兜底保持有数据。", indent=True)

    h2(doc, "3.3 统一限流：全部东财请求一条通道")
    para(doc, "东财是接口最多的一家（行业排名、资金流、解禁、板块、新闻、搜索），"
              "也是最容易被封的一家。所有东财请求收口到 _em_get 一条通道：令牌桶保证请求间隔"
              "不小于设定值并加随机抖动（并发安全），复用 Keep-Alive 会话，5xx 与连接错误"
              "退避 1 秒重试一次（防雪崩），4xx 不重试直接返回。单点收口的收益：任何反爬"
              "对策只需要改一条通道。", indent=True)
    pic(doc, "fig3_em_channel.png", "图 3  东财统一请求通道：限流 → 会话 → 重试 → 指纹兜底")

    h2(doc, "3.4 TLS 指纹兜底：被封之后怎么办")
    para(doc, "2026-10-07 实测发现：东财对 python-requests 客户端按 TLS/JA3 握手指纹直接断连——"
              "同一个接口，相同请求头用 curl 能通、用 python 必挂，属于机器级封锁。对策是"
              "两连败后切换 curl_cffi 以 impersonate=chrome 模拟浏览器指纹重发，UA 交给"
              "模拟器保持一致性；未安装 curl_cffi 则抛原始错误（历史行为不变）。这条通道上线后，"
              "行业排名、资金流、解禁、板块全部一次性恢复。", indent=True)

    h2(doc, "3.5 防前视偏差：回测可信的前提")
    para(doc, "两道闸门：行情类数据一律按分析日截断，分析日之后的行情在数据层就被丢弃；"
              "财报类数据按披露日过滤——年报报告期是 12 月 31 日，但次年 4 月才披露，"
              "按报告期过滤会把未来的财报漏给当时的分析师，按披露日过滤才正确。"
              "这是量化回测可信的底线，也是信号方向实验（T2/T3）成立的前提。", indent=True)

    h2(doc, "3.6 容错契约与冻结值检测")
    para(doc, "数据层函数承诺永不抛异常：失败返回错误字符串或空表，由上层决定降级方式"
              "（UI 显示空态、智能体收到数据缺失提示），保证任何单点数据故障不会炸掉整条分析。"
              "另外针对接口还活着但数据已死的场景设了冻结值检测——北向资金 2024-08 起停发，"
              "接口仍返回旧值，若不识别就会把同一份旧数据当成新数据写进历史；检测到返回值"
              "与历史快照完全一致且非当日，即标记疑似停发缓存回放且不落盘。", indent=True)

    # ── 四、数据域全景 ──
    h1(doc, "四、各数据域的数据源与专属护栏")
    para(doc, "八个数据域各有首选源、回退路径和针对该域数据特性的专属护栏，全景如下：", indent=True)
    pic(doc, "fig4_fallback_map.png",
        "图 4  多源回退与护栏全景（颜色区分护栏类型：蓝=常规回退，绿=口径护栏，橙=特殊降级）")

    # ── 五、代码索引 ──
    h1(doc, "五、关键代码位置索引")
    table(doc,
          ["模块", "位置", "职责"],
          [["统一路由", "dataflows/interface.py · route_to_vendor", "方法→厂商分发与回退链"],
           ["共享核心", "dataflows/a_stock/_common.py", "代码/名称解析、三级缓存、_em_get 限流通道、OHLCV 装配"],
           ["东财指纹兜底", "_common.py · _em_get_via_curl", "curl_cffi impersonate=chrome"],
           ["日K回退链", "_common.py · _load_ohlcv_astock", "CSV 当日缓存 → mootdx → 新浪补数"],
           ["防前视(财报)", "a_stock/fundamentals.py", "按披露日过滤报告期数据"],
           ["冻结值检测", "a_stock/signals.py · 北向资金", "停发缓存回放识别, 不落盘"],
           ["公告全文", "a_stock/announcements.py", "巨潮列表 + markitdown PDF(可选依赖降级)"],
           ["社区情绪", "a_stock/community.py", "股吧直连解析 + crawl4ai 渲染兜底"],
           ["UI 缓存", "web/data_functions.py", "st.cache_data 按 TTL 分级(10s~1d)"]],
          widths=[3.2, 6.6, 6.2])

    # ── 六、问答速查 ──
    h1(doc, "六、面试/答辩问答速查")
    h2(doc, "Q1 为什么不用付费数据源或现成库（akshare/tushare）？")
    para(doc, "三个原因：零成本目标；可控性——免费源的限流、口径、停发问题必须自己处理，"
              "而处理这些问题的过程恰好构成了数据层的可靠性能力；可替换性——统一路由层"
              "让未来接入付费源只是改一行配置。", indent=True)
    h2(doc, "Q2 怎么保证回测没有用到未来数据？")
    para(doc, "行情在数据层按分析日物理截断；财报按披露日过滤（报告期不等于披露日）；"
              "两道闸门都在数据层实现，智能体层无法绕过。", indent=True)
    h2(doc, "Q3 遇到反爬封锁怎么处理？")
    para(doc, "分层应对：先限流降低触发概率（令牌桶+抖动）；瞬时故障退避重试一次；"
              "持久封锁（TLS 指纹识别）切换 curl_cffi 模拟浏览器指纹；仍失败则走多源回退或"
              "降级空态，绝不重试风暴。", indent=True)
    h2(doc, "Q4 数据源返回了旧数据怎么发现？")
    para(doc, "冻结值检测：对当日数据类接口，若返回值与最近缓存快照完全一致且快照非当日，"
              "标记疑似停发回放，替换为不可用且不写入历史——防止假数据污染时间序列。", indent=True)

    doc.save(str(OUT))
    print("saved:", OUT)


if __name__ == "__main__":
    main()
