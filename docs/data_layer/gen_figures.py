# -*- coding: utf-8 -*-
"""数据层白皮书配图生成：四张工作原理图（matplotlib, 白底, 微软雅黑）.

图1 总体分层架构 | 图2 一次请求的生命周期 | 图3 东财统一请求通道 | 图4 多源回退全景
用法: python docs/data_layer/gen_figures.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = ["Microsoft YaHei", "SimHei"]
matplotlib.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parent / "figures"
OUT.mkdir(parents=True, exist_ok=True)

INK = "#1B1510"      # 暖黑
BRAND = "#A8402F"    # 朱砂
ORANGE = "#E8590C"   # 橙
MUTED = "#6B6259"
LINE = "#D8D2CB"
SURF = "#FAF8F6"
BLUE = "#2F6FED"
GREEN = "#2F9E44"


def box(ax, x, y, w, h, text, fc=SURF, ec=LINE, tc=INK, fs=10, bold=False,
        radius=0.02, lw=1.2):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle=f"round,pad=0.004,rounding_size={radius}",
                                fc=fc, ec=ec, lw=lw))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, color=tc, fontweight="bold" if bold else "normal",
            linespacing=1.5)


def arrow(ax, x1, y1, x2, y2, color=MUTED, lw=1.4, style="-|>", ls="-"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                                 mutation_scale=13, color=color, lw=lw,
                                 linestyle=ls, shrinkA=2, shrinkB=2))


def new_fig(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def save(fig, name):
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved:", OUT / name)


# ── 图1 总体分层架构 ─────────────────────────────────────
def fig1():
    fig, ax = new_fig(11, 7.6)
    ax.text(0.5, 0.975, "AStock Pro 数据层总体架构", ha="center", fontsize=15,
            fontweight="bold", color=INK)

    layers = [
        (0.845, "交互层", "Streamlit 看板 · 分析报告页 · 命令行 CLI", "#F3EEE9"),
        (0.695, "智能体工具层", "7 位分析师的 @tool 工具集\n行情 · 新闻 · 基本面 · 舆情 · 政策 · 游资 · 解禁", "#F3EEE9"),
        (0.545, "统一路由层", "route_to_vendor(method)\n方法名 → 厂商配置 → 回退链（主厂商优先, 其余厂商垫后）", "#FBEFEA"),
        (0.395, "A股数据包  a_stock", "_common 核心(解析/缓存/限流/OHLCV) · quote · fundamentals · news · signals · community · announcements", "#FBEFEA"),
        (0.245, "外部数据源", "通达信 TCP 7709 · 新浪 HTTP · 东方财富 HTTP · 同花顺 · 巨潮 · 东财股吧", "#F3EEE9"),
    ]
    for y, title, desc, fc in layers:
        box(ax, 0.06, y, 0.62, 0.11, f"{title}\n{desc}", fc=fc, fs=9.5)
    for y1 in (0.845, 0.695, 0.545, 0.395):
        arrow(ax, 0.37, y1, 0.37, y1 - 0.037, color=BRAND, lw=1.6)
    ax.text(0.37, 0.955, "调用", ha="center", fontsize=8, color=MUTED)
    ax.text(0.37, 0.205, "HTTP / TCP", ha="center", fontsize=8, color=MUTED)

    # 右侧横切机制
    ax.text(0.86, 0.905, "横切可靠性机制", ha="center", fontsize=11,
            fontweight="bold", color=BRAND)
    mech = [
        ("三级缓存", "UI 层 st.cache_data(TTL 10s~1d)\n核心层 _TTLCache(512条)\n日K CSV 当日缓存"),
        ("多源回退", "厂商间: route_to_vendor 回退链\n厂商内: mootdx→新浪 兜底"),
        ("统一限流", "_em_get 令牌桶\n最小间隔+随机抖动, 并发安全"),
        ("TLS 指纹兜底", "requests 两连败后\ncurl_cffi 模拟 Chrome 指纹"),
        ("防前视偏差", "行情按分析日截断\n财报按披露日过滤"),
        ("容错契约", "数据函数永不抛异常\n返回错误串/空表, UI 只降级"),
    ]
    y = 0.845
    for t, d in mech:
        box(ax, 0.72, y, 0.25, 0.093, f"{t}\n{d}", fc="white", ec=BRAND, fs=8.2)
        y -= 0.128
    save(fig, "fig1_architecture.png")


# ── 图2 一次请求的生命周期（分析师取日K） ────────────────
def fig2():
    fig, ax = new_fig(11, 7.2)
    ax.text(0.5, 0.975, "一次数据请求的生命周期 —— 以「技术分析师取日K」为例",
            ha="center", fontsize=15, fontweight="bold", color=INK)

    steps = [
        (0.88, "① 工具调用", "agent 调用 @tool\nget_stock_data(601208, 2026-10-24)", "#F3EEE9"),
        (0.755, "② 统一路由", "route_to_vendor(\"get_stock_data\")\n配置 a_stock → 无回退损失直达", "#FBEFEA"),
        (0.63, "③ 进程级缓存", "_TTLCache 命中?\n60s 内同参数直接返回(零网络)", "#FBEFEA"),
        (0.505, "④ 日K CSV 缓存", "~/.tradingagents/cache/601208-astock-daily.csv\n当日文件 → 直接读盘", "#FBEFEA"),
        (0.38, "⑤ 主源: 通达信 TCP", "mootdx 客户端单例(线程锁)\n服务器探测择优 → 取 800 根日K", "#F3EEE9"),
        (0.255, "⑥ 兜底: 新浪 HTTP", "主源空/陈旧 → 新浪接口补增量\n合并去重排序", "#F3EEE9"),
        (0.13, "⑦ 防前视 + 返回", "按分析日 2026-10-24 截断未来数据\n写回缓存 → 返回 DataFrame", "#FBEFEA"),
    ]
    for y, t, d, fc in steps:
        box(ax, 0.05, y, 0.56, 0.098, f"{t}\n{d}", fc=fc, fs=9)
    for i in range(len(steps) - 1):
        y1 = steps[i][0]
        arrow(ax, 0.33, y1, 0.33, y1 - 0.027, color=BRAND, lw=1.6)

    # 缓存命中旁路
    arrow(ax, 0.61, 0.679, 0.70, 0.679, color=GREEN, lw=1.4)
    box(ax, 0.70, 0.645, 0.26, 0.07,
        "命中 → 直接返回\n(最快路径: 0 次网络请求)", fc="white", ec=GREEN, fs=8.5)
    arrow(ax, 0.61, 0.554, 0.70, 0.554, color=GREEN, lw=1.4)
    ax.text(0.70, 0.515, "CSV 当日有效 → 跳过网络\n(仅新浪增量补今日)", fontsize=8.5,
            color=GREEN, ha="left")

    # 失败旁路
    arrow(ax, 0.61, 0.429, 0.70, 0.429, color=ORANGE, lw=1.4)
    ax.text(0.70, 0.39, "mootdx 全网不可达时静默返回空\n(2026-09 真实故障案例)", fontsize=8.5,
            color=ORANGE, ha="left")
    save(fig, "fig2_lifecycle.png")


# ── 图3 东财统一请求通道 _em_get ────────────────────────
def fig3():
    fig, ax = new_fig(11, 6.4)
    ax.text(0.5, 0.965, "东方财富统一请求通道 _em_get —— 全部东财接口的必经之路",
            ha="center", fontsize=15, fontweight="bold", color=INK)
    ax.text(0.5, 0.915,
            "行业排名 · 资金流 · 解禁 · 板块 · 新闻 · 搜索 —— 六类接口共用一条限流+重试+指纹兜底通道",
            ha="center", fontsize=9, color=MUTED)

    nodes = [
        (0.075, 0.72, 0.17, 0.13, "调用方\n行业/资金流/新闻\n等数据函数", "#F3EEE9"),
        (0.315, 0.72, 0.17, 0.13, "令牌桶限流\nEM_MIN_INTERVAL\n+随机抖动(并发安全)", "#FBEFEA"),
        (0.555, 0.72, 0.17, 0.13, "Keep-Alive\nSession GET\n默认 UA + Referer", "#FBEFEA"),
        (0.795, 0.72, 0.17, 0.13, "响应解析\n返回 requests\nResponse", "#FBEFEA"),
    ]
    for x, y, w, h, t, fc in nodes:
        box(ax, x, y, w, h, t, fc=fc, fs=9)
    for i in range(3):
        arrow(ax, nodes[i][0] + nodes[i][2], 0.785, nodes[i + 1][0], 0.785,
              color=BRAND, lw=1.6)

    # 重试与兜底
    box(ax, 0.315, 0.44, 0.17, 0.12, "失败判定\n连接错误/超时/5xx\n4xx 不重试", fc="white", ec=ORANGE, fs=8.5)
    arrow(ax, 0.642, 0.72, 0.485, 0.56, color=ORANGE, lw=1.4)
    box(ax, 0.555, 0.44, 0.17, 0.12, "退避 1s 重试 1 次\n(仅一次, 防雪崩)", fc="white", ec=ORANGE, fs=8.5)
    arrow(ax, 0.485, 0.50, 0.555, 0.50, color=ORANGE, lw=1.4)
    arrow(ax, 0.642, 0.50, 0.72, 0.72, color=ORANGE, lw=1.2, ls="--")
    ax.text(0.70, 0.60, "仍失败", fontsize=8, color=ORANGE)

    box(ax, 0.555, 0.16, 0.41, 0.17,
        "curl_cffi 指纹兜底  _em_get_via_curl\nimpersonate=\"chrome\" —— 东财按 TLS/JA3 指纹\n识别并断连 python 客户端(2026-10-07 实锤), \n模拟浏览器指纹重发, 未安装则抛原始错误",
        fc="white", ec=BRAND, fs=8.8)
    arrow(ax, 0.64, 0.44, 0.64, 0.33, color=BRAND, lw=1.6)

    ax.text(0.05, 0.10,
            "设计要点：单点收口 —— 所有东财请求共用一个限流器与会话，任何一处反爬对策只需改一条通道；\n"
            "两段式失败处理 —— 先退避重试(瞬时抖动), 再指纹切换(持久封锁)，两种故障模式分开对付。",
            fontsize=9, color=INK, linespacing=1.7)
    save(fig, "fig3_em_channel.png")


# ── 图4 多源回退与护栏全景 ──────────────────────────────
def fig4():
    fig, ax = new_fig(11, 7.0)
    ax.text(0.5, 0.97, "各数据域 · 首选源 → 回退源 · 专属护栏", ha="center",
            fontsize=15, fontweight="bold", color=INK)

    rows = [
        ("实时行情快照", "腾讯 HTTP (10s UI 缓存)", "失败返回 {} → 卡片降级 \"--\"", BLUE),
        ("日K OHLCV", "通达信 TCP (服务器探测+线程锁)", "新浪 HTTP 增量补数 · CSV 当日缓存", BLUE),
        ("行业/资金流/解禁/新闻", "东财 HTTP via _em_get", "curl_cffi 指纹兜底 → 空态降级", BLUE),
        ("财务三表", "新浪 getFinanceReport2022", "按披露日过滤防前视(年报4月才披露)", GREEN),
        ("估值/一致预期", "腾讯行情 + 同花顺 EPS", "PE 口径警示(中报年化≠静态)", GREEN),
        ("北向资金", "东财(2024-08 起停发)", "冻结值检测护栏, 不落盘假数据", ORANGE),
        ("公告全文", "巨潮列表 + markitdown PDF", "未安装降级为仅列表(可选依赖)", ORANGE),
        ("社区情绪", "股吧直连 HTML 解析", "反爬壳时 crawl4ai 浏览器渲染兜底", ORANGE),
    ]
    y = 0.865
    for name, primary, guard, c in rows:
        box(ax, 0.03, y, 0.20, 0.085, name, fc="white", ec=c, fs=9.5, bold=True)
        box(ax, 0.25, y, 0.36, 0.085, primary, fc=SURF, ec=LINE, fs=9)
        box(ax, 0.63, y, 0.35, 0.085, guard, fc=SURF, ec=LINE, fs=8.6)
        y -= 0.104
    ax.text(0.13, 0.905, "数据域", ha="center", fontsize=10, fontweight="bold", color=BRAND)
    ax.text(0.43, 0.905, "首选源(含通道机制)", ha="center", fontsize=10, fontweight="bold", color=BRAND)
    ax.text(0.805, 0.905, "回退 / 专属护栏", ha="center", fontsize=10, fontweight="bold", color=BRAND)
    save(fig, "fig4_fallback_map.png")


if __name__ == "__main__":
    fig1()
    fig2()
    fig3()
    fig4()
