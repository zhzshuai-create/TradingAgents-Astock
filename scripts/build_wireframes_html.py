"""Build the P0 core wireframes as two self-contained HTML pages.

    python scripts/build_wireframes_html.py

Desktop page is drawn for 1440px; mobile page for 390px (must also fit 360px).
Content mirrors docs/upgrade/contracts/core-wireframes.md.
"""
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "upgrade" / "wireframes"

STAGES = [
    ("market", "技术分析", "done"),
    ("social", "情绪分析", "done"),
    ("news", "新闻舆情", "done"),
    ("fundamentals", "基本面", "done"),
    ("policy", "政策分析", "done"),
    ("hot_money", "游资追踪", "done"),
    ("lockup", "解禁监控", "done"),
    ("quality_gate", "质量门控", "done"),
    ("debate", "多空辩论", "active"),
    ("trader", "交易决策", "pending"),
    ("risk", "风控评估", "pending"),
    ("pm", "最终决策", "pending"),
]

STAGE_LABEL = {"done": "已完成", "active": "进行中", "pending": "等待", "failed": "失败", "skipped": "已跳过"}


def badge(kind: str, text: str) -> str:
    return f'<span class="badge {kind}">{text}</span>'


def btn(text: str, kind: str = "") -> str:
    cls = f"btn {kind}".strip()
    return f'<span class="{cls}">{text}</span>'


def topnav(active: str) -> str:
    items = ["工作台", "市场", "任务", "报告", "日志"]
    links = "".join(
        f'<span class="{"active" if name == active else ""}">{name}</span>' for name in items
    )
    return (
        '<div class="topnav"><div class="brand">AStock Pro</div>'
        f'<div class="navlinks">{links}</div>'
        '<div class="navsearch">搜索股票代码或名称</div>'
        '<div class="navgear">设置</div></div>'
    )


def jobbar(stage: str = "多空辩论 9/12", pct: int = 75) -> str:
    return (
        '<div class="jobbar">' + badge("run", "运行中")
        + '<b>宁德时代 300750</b>'
        + f'<span class="muted">{stage}</span>'
        + f'<span class="mini"><i style="width:{pct}%"></i></span>'
        + '<a>查看</a><span class="muted tiny">还有 1 个</span></div>'
    )


def m_top(title: str, right: str = "搜索") -> str:
    return f'<div class="m-top"><span>{title}</span><span class="m-top-r">{right}</span></div>'


def m_nav(active: str) -> str:
    items = ["工作台", "市场", "任务", "报告", "更多"]
    cells = "".join(
        f'<span class="{"active" if name == active else ""}">{name}</span>' for name in items
    )
    return f'<div class="m-nav">{cells}</div>'


def m_jobbar() -> str:
    return (
        '<div class="m-jobbar">' + badge("run", "运行中")
        + '<b>宁德时代</b><span>9/12 多空辩论</span><span class="m-job-more">查看</span></div>'
    )


def stage_grid(start: int, end: int) -> str:
    cells = []
    for i in range(start, end + 1):
        _, name, st = STAGES[i - 1]
        cells.append(f'<div class="stage {st}"><span class="no">{i:02d}</span>{name}</div>')
    return "".join(cells)


def stage_rows() -> str:
    rows = []
    for i, (_, name, st) in enumerate(STAGES, 1):
        rows.append(
            f'<div class="m-stage {st}"><span>{i:02d} {name}</span>'
            f'<span class="tiny">{STAGE_LABEL[st]}</span></div>'
        )
    return "".join(rows)


def md_lines(n: int = 8, heading: str = "一、投资结论") -> str:
    widths = ["w95", "w88", "w92", "w70", "w96", "w84", "w90", "w60"]
    lines = "".join(f'<div class="line {widths[i % len(widths)]}"></div>' for i in range(n))
    return f'<div class="md"><div class="md-h">{heading}</div>{lines}</div>'


def table(headers: list[str], rows: list[list[str]], cls: str = "tbl") -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def mrow(left: str, right: str = "") -> str:
    return f'<div class="m-list-row"><span>{left}</span><span class="muted tiny">{right}</span></div>'


def mcard(inner: str, cls: str = "") -> str:
    return f'<div class="m-card {cls}">{inner}</div>'


def chart(bars: list[int], mobile: bool = False) -> str:
    inner = "".join(f'<i style="height:{h}%"></i>' for h in bars)
    body = f'<div class="bars">{inner}</div>'
    if mobile:
        body = f'<div class="chart-scroll"><div class="chart-inner">{body}</div></div>'
    return f'<div class="chart"><div class="tiny muted">K 线占位 · 不复权</div>{body}</div>'


# ---------------------------------------------------------------- W01
def w01_d() -> str:
    return (
        topnav("工作台") + jobbar()
        + '<div class="content">'
        '<div class="grid2">'
        '<div class="card hero"><h3>分析一只股票</h3>'
        '<p class="muted tiny">输入代码或名称，12 个阶段，预计 5–15 分钟</p>'
        '<div class="searchrow"><div class="input">宁德时代 300750</div>' + btn("开始分析", "primary") + '</div>'
        '<div class="dropdown">'
        '<div class="drop-row"><b>宁德时代</b><span class="muted">300750 · 深市</span></div>'
        '</div></div>'
        '<div class="card"><h3>今日市场</h3>'
        '<div class="indices4">'
        '<div class="idx"><span class="muted tiny">上证指数</span><b>3,318.62</b><span class="up">+0.82%</span></div>'
        '<div class="idx"><span class="muted tiny">深证成指</span><b>10,562.14</b><span class="up">+1.10%</span></div>'
        '<div class="idx"><span class="muted tiny">创业板指</span><b>2,184.07</b><span class="down">-0.31%</span></div>'
        '<div class="idx"><span class="muted tiny">北向资金</span><b>+42.6 亿</b><span class="muted tiny">14:58</span></div>'
        '</div>'
        '<div class="market-state">' + badge("ok", "数据正常") + '<span class="tiny muted">更新于 14:59:32</span></div>'
        '</div></div>'
        '<div class="grid2">'
        '<div class="card"><h3>行业涨幅 Top5</h3>'
        + table(["#", "行业", "涨跌幅", "领涨股"], [
            ["1", "半导体", "+3.21%", "中芯国际"],
            ["2", "消费电子", "+2.74%", "立讯精密"],
            ["3", "汽车整车", "+2.15%", "比亚迪"],
            ["4", "电池", "+1.88%", "宁德时代"],
            ["5", "光伏设备", "+1.42%", "隆基绿能"],
        ]) + '</div>'
        '<div class="card"><h3>强势股 Top5</h3>'
        + table(["股票", "涨跌幅", "换手"], [
            ["中芯国际 688981", "+9.98%", "4.2%"],
            ["立讯精密 002475", "+7.31%", "3.1%"],
            ["比亚迪 002594", "+5.62%", "1.8%"],
            ["宁德时代 300750", "+4.10%", "1.2%"],
            ["隆基绿能 601012", "+3.55%", "2.0%"],
        ]) + '</div></div>'
        '<div class="grid2">'
        '<div class="card"><h3>最近任务</h3>'
        + table(["股票", "状态", "阶段", "时间"], [
            ["宁德时代 300750", badge("run", "运行中"), "9/12 多空辩论", "2 分钟前"],
            ["贵州茅台 600519", badge("ok", "已完成"), "报告已生成", "今天 11:20"],
            ["中国平安 601318", badge("bad", "失败"), "新闻舆情超时", "昨天 16:40"],
        ]) + '</div>'
        '<div class="card"><h3>最近报告</h3>'
        + table(["股票", "评级", "日期", ""], [
            ["贵州茅台 600519", badge("ok", "增持"), "2026-10-28", "阅读"],
            ["比亚迪 002594", badge("warn", "中性"), "2026-10-27", "阅读"],
            ["中芯国际 688981", badge("ok", "买入"), "2026-10-24", "阅读"],
        ]) + '</div></div>'
        '</div>'
    )


def w01_m() -> str:
    return (
        m_top("工作台") + m_jobbar()
        + '<div class="m-content">'
        + mcard('<div class="m-h">分析一只股票</div>'
                '<div class="m-input">宁德时代 300750</div>'
                '<div class="m-primary">开始分析</div>')
        + mcard('<div class="m-h">今日市场</div>'
                '<div class="m-indices">'
                '<div class="m-index"><span class="tiny muted">上证指数</span><b>3,318.62</b><span class="up tiny">+0.82%</span></div>'
                '<div class="m-index"><span class="tiny muted">深证成指</span><b>10,562.14</b><span class="up tiny">+1.10%</span></div>'
                '<div class="m-index"><span class="tiny muted">创业板指</span><b>2,184.07</b><span class="down tiny">-0.31%</span></div>'
                '</div>')
        + mcard('<div class="m-h">最近任务</div>'
                + mrow("宁德时代 · 运行中", "9/12")
                + mrow("贵州茅台 · 已完成", "11:20")
                + mrow("中国平安 · 失败", "昨天"))
        + mcard('<div class="m-h">最近报告</div>'
                + mrow("贵州茅台 · 增持", "10-28")
                + mrow("比亚迪 · 中性", "10-27")
                + mrow("查看全部报告", "›"))
        + '</div>' + m_nav("工作台")
    )


# ---------------------------------------------------------------- W02
def w02_d() -> str:
    return (
        topnav("工作台")
        + '<div class="content dim">'
        '<div class="grid2"><div class="card"><h3>分析一只股票</h3><div class="line w80"></div><div class="line w60"></div></div>'
        '<div class="card"><h3>今日市场</h3><div class="line w90"></div><div class="line w70"></div></div></div>'
        '<div class="grid2"><div class="card"><h3>最近任务</h3><div class="line w80"></div><div class="line w60"></div></div>'
        '<div class="card"><h3>最近报告</h3><div class="line w80"></div><div class="line w60"></div></div></div>'
        '</div>'
        '<div class="overlay"><div class="dialog">'
        '<div class="dialog-head"><b>新建分析</b><span class="muted">配置会在提交时固化</span></div>'
        '<div class="field"><label>标的</label><div class="input">宁德时代 300750 <span class="link">更换</span></div></div>'
        '<div class="field"><label>分析日期</label><div class="input">2026-10-29 <span class="tiny muted">服务器默认</span></div></div>'
        '<div class="field"><label>模型配置</label><div class="input">DeepSeek 默认 ▾</div></div>'
        '<div class="switchrow"><span>并行分析</span><span class="switch on"></span></div>'
        '<div class="accordion">阶段开关（7 个分析阶段）<span class="muted">展开</span></div>'
        '<div class="hintwarn">分析会调用付费模型，预计 5–15 分钟。</div>'
        '<div class="dialog-actions">' + btn("取消") + btn("开始分析（提交中…）", "primary disabled") + '</div>'
        '</div></div>'
    )


def w02_m() -> str:
    return (
        m_top("新建分析", "关闭")
        + '<div class="m-content">'
        + mcard('<div class="m-label">标的</div><div class="m-input">宁德时代 300750</div>')
        + mcard('<div class="m-label">分析日期</div><div class="m-input">2026-10-29</div>')
        + mcard('<div class="m-label">模型配置</div><div class="m-input">DeepSeek 默认 ▾</div>'
                '<div class="m-switch"><span>并行分析</span><span class="switch on"></span></div>')
        + mcard('<div class="m-label">阶段开关</div><div class="muted tiny">7 个分析阶段 · 点开二级页</div>')
        + '<div class="m-warn"><b>该股票今日已有进行中的分析</b>'
          '<div class="tiny">等待它结束，或先取消后再提交。</div>'
          '<div class="m-warn-actions">' + btn("查看进行中的任务") + btn("取消") + '</div></div>'
        + '</div>'
        + '<div class="m-sticky"><span class="muted tiny">预计 5–15 分钟</span>'
          '<span class="m-primary half disabled">暂不能提交</span></div>'
    )


# ---------------------------------------------------------------- W03
def w03_d() -> str:
    return (
        topnav("任务") + jobbar()
        + '<div class="content">'
        '<div class="card filters"><b>筛选</b>'
        '<span class="chip">状态：全部 ▾</span><span class="chip">股票代码</span>'
        '<span class="chip">分析日期 2026-09-01 → 2026-10-29</span>'
        '<span class="switch-s">只看活动任务</span><span class="link">重置</span></div>'
        '<div class="card">'
        + table(["股票", "分析日期", "状态", "当前阶段", "耗时", "创建时间", ""], [
            ["宁德时代 300750", "2026-10-29", badge("run", "运行中"), "9/12 多空辩论", "06:12", "14:52", "查看"],
            ["贵州茅台 600519", "2026-10-29", badge("ok", "已完成"), "12/12 完成", "11:41", "11:08", "查看"],
            ["中国平安 601318", "2026-10-28", badge("bad", "失败"), "新闻舆情超时", "03:05", "昨天 16:37", "查看"],
            ["比亚迪 002594", "2026-10-28", badge("warn", "中断"), "8/12 质量门控", "07:20", "昨天 10:02", "查看"],
            ["中芯国际 688981", "2026-10-27", badge("mut", "已取消"), "5/12 政策分析", "02:48", "10-27 09:31", "查看"],
        ])
        + '<div class="loadmore">加载更多</div></div>'
        '</div>'
    )


def w03_m() -> str:
    return (
        m_top("任务", "筛选")
        + m_jobbar()
        + '<div class="m-content">'
        + '<div class="m-chips"><span class="chip">全部状态</span><span class="chip">近 30 天</span><span class="chip">清空</span></div>'
        + mcard(
            '<div class="m-row-between"><b>宁德时代 300750</b>' + badge("run", "运行中") + '</div>'
            '<div class="tiny muted">2026-10-29 · 9/12 多空辩论 · 06:12</div>'
        )
        + mcard(
            '<div class="m-row-between"><b>贵州茅台 600519</b>' + badge("ok", "已完成") + '</div>'
            '<div class="tiny muted">2026-10-29 · 12/12 · 11:41</div>'
        )
        + mcard(
            '<div class="m-row-between"><b>中国平安 601318</b>' + badge("bad", "失败") + '</div>'
            '<div class="tiny muted">2026-10-28 · 新闻舆情超时 · 03:05</div>'
        )
        + mcard(
            '<div class="m-row-between"><b>比亚迪 002594</b>' + badge("warn", "中断") + '</div>'
            '<div class="tiny muted">2026-10-28 · 8/12 质量门控 · 07:20</div>'
        )
        + '<div class="loadmore">加载更多</div>'
        + '</div>' + m_nav("任务")
    )


# ---------------------------------------------------------------- W04
def w04_d() -> str:
    accordion = (
        '<div class="acc-open"><div class="acc-head"><b>技术分析</b>' + badge("ok", "已完成") + '<span class="muted tiny">展开全文</span></div>'
        + md_lines(6, "技术面：均线多头排列") + '</div>'
        '<div class="acc"><b>情绪分析</b>' + badge("ok", "已完成") + '<span class="muted tiny">点击展开</span></div>'
        '<div class="acc"><b>新闻舆情</b>' + badge("ok", "已完成") + '<span class="muted tiny">点击展开</span></div>'
        '<div class="acc dim"><b>多空辩论</b>' + badge("run", "进行中") + '<span class="muted tiny">尚未产出</span></div>'
    )
    return (
        topnav("任务")
        + '<div class="content">'
        '<div class="task-head"><div>'
        '<div class="task-title">宁德时代 <span class="muted">300750</span> ' + badge("run", "运行中") + '</div>'
        '<div class="tiny muted">分析日期 2026-10-29 · 创建于 14:52 · 已运行 06:12</div></div>'
        '<div class="task-actions">' + btn("暂停") + btn("取消", "danger") + '</div></div>'
        '<div class="card"><div class="card-h"><b>阶段进度</b><span class="tiny muted">8/12 完成 · 当前 多空辩论</span></div>'
        '<div class="stage-label">ANALYSTS</div>'
        f'<div class="stages7">{stage_grid(1, 7)}</div>'
        '<div class="stage-label">PIPELINE</div>'
        f'<div class="stages5">{stage_grid(8, 12)}</div>'
        '</div>'
        '<div class="stats4">'
        '<div class="stat"><span class="tiny muted">模型调用</span><b>38</b></div>'
        '<div class="stat"><span class="tiny muted">输入 Tokens</span><b>128,420</b></div>'
        '<div class="stat"><span class="tiny muted">输出 Tokens</span><b>31,206</b></div>'
        '<div class="stat"><span class="tiny muted">耗时</span><b>06:12</b></div>'
        '</div>'
        '<div class="card"><div class="card-h"><b>阶段报告</b><span class="tiny muted">最近完成的自动展开</span></div>'
        + accordion + '</div>'
        '</div>'
    )


def w04_m() -> str:
    return (
        m_top("宁德时代 300750", "更多")
        + '<div class="m-content m-task">'
        + '<div class="m-row-between"><div><b>宁德时代</b> ' + badge("warn", "暂停中") + '</div><span class="tiny muted">8/12</span></div>'
        + '<div class="m-stats"><span>模型调用 38</span><span>耗时 06:12</span><span>Tokens 159.6k</span></div>'
        + '<div class="m-warn small">暂停请求已受理，将在当前阶段结束后生效。</div>'
        + '<div class="m-stage-list">' + stage_rows() + '</div>'
        + '</div>'
        + '<div class="m-drawer"><div class="m-drawer-head"><b>阶段报告 · 技术分析</b><span class="muted">关闭</span></div>'
        + md_lines(6, "技术面：均线多头排列") + '<div class="link tiny">展开全文</div></div>'
        + '<div class="m-sticky"><span class="m-btn-danger">取消</span><span class="m-btn quiet">打开报告</span></div>'
        + m_nav("任务")
    )


# ---------------------------------------------------------------- W05
def w05_d() -> str:
    return (
        topnav("报告") + jobbar()
        + '<div class="content">'
        '<div class="card filters"><b>筛选</b><span class="chip">股票代码</span>'
        '<span class="chip">分析日期 2026-09-01 → 2026-10-29</span><span class="chip">评级：全部 ▾</span>'
        '<span class="link">重置</span></div>'
        '<div class="card">'
        + table(["评级", "股票", "分析日期", "来源", "生成时间", "信号"], [
            [badge("ok", "增持"), "贵州茅台 600519", "2026-10-28", "AI 分析", "10-28 11:41", "Buy"],
            [badge("warn", "中性"), "比亚迪 002594", "2026-10-27", "AI 分析", "10-27 15:02", "Hold"],
            [badge("ok", "买入"), "中芯国际 688981", "2026-10-24", "AI 分析", "10-24 10:18", "Buy"],
            [badge("bad", "卖出"), "中国平安 601318", "2026-10-20", "历史导入", '<span class="muted">生成时间未知</span>', "Sell"],
            [badge("mut", "未知"), "隆基绿能 601012", "2026-10-18", "历史导入", '<span class="muted">生成时间未知</span>', "unknown"],
        ])
        + '<div class="loadmore">加载更多</div></div>'
        '</div>'
    )


def w05_m() -> str:
    return (
        m_top("报告", "筛选")
        + m_jobbar()
        + '<div class="m-content">'
        + '<div class="m-chips"><span class="chip">评级：全部</span><span class="chip">近 30 天</span><span class="chip">清空</span></div>'
        + mcard('<div class="m-row-between">' + badge("ok", "增持") + '<span class="tiny muted">10-28</span></div>'
                '<b>贵州茅台 600519</b><div class="tiny muted">AI 分析 · 生成于 11:41</div>')
        + mcard('<div class="m-row-between">' + badge("warn", "中性") + '<span class="tiny muted">10-27</span></div>'
                '<b>比亚迪 002594</b><div class="tiny muted">AI 分析 · 生成于 15:02</div>')
        + mcard('<div class="m-row-between">' + badge("bad", "卖出") + '<span class="tiny muted">10-20</span></div>'
                '<b>中国平安 601318</b><div class="tiny muted">历史导入 · 生成时间未知</div>')
        + '<div class="loadmore">加载更多</div>'
        + '</div>' + m_nav("报告")
    )


# ---------------------------------------------------------------- W06
def w06_d() -> str:
    toc = "".join(
        f'<div class="toc-item {"on" if i == 1 else ""}">sec-{name}</div>'
        for i, name in enumerate([
            "decision", "thesis", "market", "social", "news", "fundamentals",
            "policy", "hot_money", "lockup", "debate", "trader", "risk", "summary",
        ], 1)
    )
    return (
        topnav("报告")
        + '<div class="content">'
        '<div class="reader-head"><div><span class="link">← 返回报告库</span>'
        '<div class="task-title">贵州茅台 <span class="muted">600519</span> ' + badge("ok", "增持") + '</div>'
        '<div class="tiny muted">分析日期 2026-10-28 · 来源任务 5b1c… · 数据质量：完整</div></div>'
        '<div class="task-actions">' + btn("导出 PDF") + btn("重新分析", "primary") + '</div></div>'
        '<div class="reader">'
        f'<div class="toc"><div class="tiny muted">章节</div>{toc}</div>'
        '<div class="reading">'
        '<div class="md-h big">一、投资结论</div>'
        + md_lines(10, "评级：增持 · 目标价 1,980 元")
        + '<div class="md-h">二、核心逻辑</div>' + md_lines(6, "高端白酒动销改善")
        + '<div class="md-table">表格占位 · 容器内横向滚动</div>'
        + '</div>'
        '<div class="side">'
        '<div class="card tight"><div class="m-h">决策卡</div>'
        '<div class="kv"><span>评级</span><b>增持</b></div>'
        '<div class="kv"><span>信号</span><b>Buy</b></div>'
        '<div class="kv"><span>目标价</span><b>1,980 元</b></div>'
        '<div class="kv"><span>止损参考</span><b>1,720 元</b></div>'
        '<div class="kv"><span>时间跨度</span><b>3–6 个月</b></div></div>'
        '<div class="card tight"><div class="m-h">来源</div>'
        '<div class="kv"><span>任务</span><span class="link">5b1c…</span></div>'
        '<div class="kv"><span>图表快照</span><span>已生成</span></div></div>'
        '</div></div>'
        '<div class="toast">PDF 渲染中 · 2/3</div>'
        '</div>'
    )


def w06_m() -> str:
    toc = "".join(
        f'<div class="m-toc-row {"on" if i == 1 else ""}">sec-{name}</div>'
        for i, name in enumerate([
            "decision", "thesis", "market", "social", "news", "fundamentals",
            "policy", "hot_money", "lockup", "debate", "trader", "risk", "summary",
        ], 1)
    )
    return (
        m_top("贵州茅台 600519", "目录")
        + '<div class="m-content">'
        + mcard('<div class="m-row-between"><b>增持</b><span class="tiny muted">2026-10-28</span></div>'
                '<div class="tiny muted">目标价 1,980 元 · 止损 1,720 元 · 3–6 个月</div>')
        + '<div class="md-h">一、投资结论</div>' + md_lines(8, "评级：增持")
        + '<div class="md-h">二、核心逻辑</div>' + md_lines(6, "高端白酒动销改善")
        + '</div>'
        + '<div class="m-drawer"><div class="m-drawer-head"><b>报告目录</b><span class="muted">关闭</span></div>'
        + toc + '</div>'
        + '<div class="m-sticky"><span class="m-btn">导出 PDF</span><span class="m-primary half">重新分析</span></div>'
        + m_nav("报告")
    )


# ---------------------------------------------------------------- W07
def w07_d() -> str:
    return (
        topnav("市场") + jobbar()
        + '<div class="content">'
        '<div class="stock-head"><div><span class="task-title">宁德时代 <span class="muted">300750 · 深市</span></span>'
        '<div><b class="price">268.40</b> <span class="up">+4.10%</span> <span class="tiny muted">行情 14:59:32</span></div></div>'
        + btn("分析这只股票", "primary") + '</div>'
        '<div class="tabs"><span class="on">估值</span><span>K 线</span><span>分时</span><span>新闻</span><span>报告</span><span>任务</span></div>'
        '<div class="grid2">'
        '<div class="card"><div class="m-h">一致预期</div>'
        '<div class="metrics4">'
        '<div class="metric"><span class="tiny muted">EPS 预期</span><b>12.86</b></div>'
        '<div class="metric"><span class="tiny muted">动态 PE</span><b>20.9</b></div>'
        '<div class="metric"><span class="tiny muted">PEG</span><b>0.87</b></div>'
        '<div class="metric"><span class="tiny muted">消化估值</span><b>2.1 年</b></div>'
        '</div></div>'
        '<div class="card"><div class="m-h">板块</div>'
        '<div class="tiny muted">行业 · 电池</div><div class="line w80"></div>'
        '<div class="tiny muted">概念 · 固态电池 / 储能</div><div class="line w70"></div></div>'
        '</div>'
        '<div class="grid2">'
        f'<div class="card"><div class="m-h">日 K（容器内缩放）</div>{chart([40, 52, 45, 60, 58, 66, 62, 70, 68, 76, 72, 84, 80, 88])}</div>'
        '<div class="card"><div class="m-h">资金流</div>' + md_lines(4, "主力净流入 +2.4 亿") + '</div>'
        '</div></div>'
    )


def w07_m() -> str:
    return (
        m_top("宁德时代 300750", "⋯")
        + '<div class="m-content">'
        + mcard('<b class="price">268.40</b> <span class="up">+4.10%</span>'
                '<div class="tiny muted">行情 14:59:32 · 数据正常</div>')
        + '<div class="m-tabs"><span class="on">估值</span><span>K 线</span><span>分时</span><span>新闻</span><span>报告</span></div>'
        + mcard('<div class="m-metrics"><div><span class="tiny muted">EPS</span><b>12.86</b></div>'
                '<div><span class="tiny muted">动态 PE</span><b>20.9</b></div>'
                '<div><span class="tiny muted">PEG</span><b>0.87</b></div>'
                '<div><span class="tiny muted">消化</span><b>2.1 年</b></div></div>')
        + mcard('<div class="m-h">日 K</div>' + chart([40, 52, 45, 60, 58, 66, 62, 70, 68, 76, 72, 84, 80, 88, 74, 90], mobile=True))
        + '</div>'
        + '<div class="m-sticky"><span class="muted tiny">268.40 · +4.10%</span><span class="m-primary half">分析这只股票</span></div>'
        + m_nav("市场")
    )


# ---------------------------------------------------------------- W08
def w08_d() -> str:
    return (
        topnav("市场") + jobbar()
        + '<div class="content">'
        '<div class="session">' + badge("ok", "交易中") + '<span class="tiny muted">数据更新 14:59:32 · 指数块 10 秒 / 行业块 5 分钟</span></div>'
        '<div class="indices3">'
        '<div class="card"><span class="tiny muted">上证指数</span><b>3,318.62</b><span class="up">+0.82%</span></div>'
        '<div class="card"><span class="tiny muted">深证成指</span><b>10,562.14</b><span class="up">+1.10%</span></div>'
        '<div class="card"><span class="tiny muted">创业板指</span><b>2,184.07</b><span class="down">-0.31%</span></div>'
        '</div>'
        '<div class="grid2">'
        '<div class="card"><div class="m-h">行业涨幅 Top</div>'
        + table(["#", "行业", "涨跌幅", "涨/跌", "领涨股"], [
            ["1", "半导体", "+3.21%", "82/11", "中芯国际 +9.98%"],
            ["2", "消费电子", "+2.74%", "61/18", "立讯精密 +7.31%"],
            ["3", "汽车整车", "+2.15%", "24/9", "比亚迪 +5.62%"],
            ["4", "电池", "+1.88%", "38/12", "宁德时代 +4.10%"],
            ["5", "光伏设备", "+1.42%", "45/20", "隆基绿能 +3.55%"],
        ]) + '</div>'
        '<div class="card"><div class="m-h">强势股</div>'
        + table(["股票", "涨跌幅", "换手", "原因"], [
            ["中芯国际", "+9.98%", "4.2%", "先进制程"],
            ["立讯精密", "+7.31%", "3.1%", "苹果链"],
            ["比亚迪", "+5.62%", "1.8%", "销量"],
            ["宁德时代", "+4.10%", "1.2%", "储能"],
        ]) + '</div></div>'
        '<div class="grid2">'
        '<div class="card"><div class="m-h">快讯</div>' + mrow("盘中快讯：半导体板块持续走强", "14:56") + mrow("北向资金净流入扩大至 42 亿", "14:51") + mrow("工信部：加快固态电池标准制定", "14:32") + '</div>'
        '<div class="card"><div class="m-h">数据状态</div><div class="tiny muted">指数块 ok · 行业块 ok · 北向块 stale（30 秒阈值）</div></div>'
        '</div></div>'
        '<div class="drawer"><div class="drawer-head"><b>行业成分股 · 半导体</b><span class="muted">关闭</span></div>'
        + table(["股票", "现价", "涨跌幅"], [
            ["中芯国际 688981", "92.40", "+9.98%"],
            ["韦尔股份 603501", "118.20", "+6.31%"],
            ["北方华创 002371", "412.60", "+5.02%"],
            ["兆易创新 603986", "108.14", "+4.44%"],
            ["长电科技 600584", "36.92", "+3.10%"],
        ]) + '<div class="tiny muted">点击成分股进入股票工作区</div></div>'
        '<div class="scrim"></div>'
    )


def w08_m() -> str:
    return (
        m_top("市场", "筛选")
        + m_jobbar()
        + '<div class="m-content">'
        + mcard('<div class="m-row-between">' + badge("ok", "交易中") + '<span class="tiny muted">14:59:32</span></div>'
                '<div class="m-indices">'
                '<div class="m-index"><span class="tiny muted">上证</span><b>3,318.62</b><span class="up tiny">+0.82%</span></div>'
                '<div class="m-index"><span class="tiny muted">深证</span><b>10,562.14</b><span class="up tiny">+1.10%</span></div>'
                '<div class="m-index"><span class="tiny muted">创业板</span><b>2,184.07</b><span class="down tiny">-0.31%</span></div>'
                '</div>')
        + mcard('<div class="m-h">行业涨幅</div>'
                + mrow("半导体 · 领涨中芯国际", "+3.21%")
                + mrow("消费电子 · 立讯精密", "+2.74%")
                + mrow("汽车整车 · 比亚迪", "+2.15%")
                + mrow("电池 · 宁德时代", "+1.88%")
                + '<div class="tiny muted">点击行业查看成分股</div>')
        + mcard('<div class="m-h">强势股</div>'
                + mrow("中芯国际 688981", "+9.98%")
                + mrow("立讯精密 002475", "+7.31%")
                + mrow("比亚迪 002594", "+5.62%"))
        + mcard('<div class="m-h">快讯</div>'
                + mrow("半导体板块持续走强", "14:56")
                + mrow("北向净流入扩大至 42 亿", "14:51"))
        + '</div>' + m_nav("市场")
    )


# ---------------------------------------------------------------- W09
def w09_d() -> str:
    return (
        topnav("日志") + jobbar()
        + '<div class="content">'
        '<div class="iframe-placeholder">'
        '<div class="journal-card">'
        '<div class="journal-icon">J</div>'
        '<h3>交易日志服务当前没有运行</h3>'
        '<p class="muted">交易日志是独立应用，本系统不读取也不修改它的数据。</p>'
        '<div class="code">trade-journal/run.bat</div>'
        '<div class="tiny muted">在交易日志目录运行上面的脚本，端口固定 8502。</div>'
        '<div class="journal-actions">' + btn("重试") + btn("查看启动说明") + '</div>'
        '<div class="hintwarn tiny">检测结果：端口未监听（not_running）</div>'
        '</div></div></div>'
    )


def w09_m() -> str:
    return (
        m_top("交易日志", "⋯")
        + '<div class="m-content">'
        + mcard('<div class="m-h">交易日志服务当前没有运行</div>'
                '<div class="tiny muted">交易日志是独立应用，本系统不读取也不修改它的数据。</div>'
                '<div class="m-code">trade-journal/run.bat</div>'
                '<div class="m-primary">重试</div>'
                '<div class="m-btn quiet">查看启动说明</div>'
                '<div class="tiny muted">端口未监听（not_running）</div>')
        + '</div>' + m_nav("更多")
    )


# ---------------------------------------------------------------- W10
def w10_d() -> str:
    return (
        topnav("") + jobbar()
        + '<div class="content">'
        '<div class="settings">'
        '<div class="settings-nav">'
        '<div class="set-item on">基本信息</div>'
        '<div class="set-item">模型</div>'
        '<div class="set-item">数据源</div>'
        '<div class="set-item">关于</div>'
        '</div>'
        '<div class="card settings-body"><div class="m-h">基本信息</div>'
        '<div class="kv"><span>服务状态</span><b>' + badge("ok", "接口可达") + ' ' + badge("ok", "SSE 可达") + '</b></div>'
        '<div class="kv"><span>版本</span><b>0.9.0</b></div>'
        '<div class="kv"><span>接口契约</span><b>api-v1</b></div>'
        '<div class="kv"><span>服务器时间</span><b>2026-10-29 15:04:05 +08:00</b></div>'
        '<div class="kv"><span>交易日志</span><b>' + badge("warn", "不可用") + '</b></div>'
        '<div class="kv"><span>数据源</span><b>腾讯行情 · 最近成功 14:59:31</b></div>'
        '</div></div>'
        '<div class="card settings-body"><div class="m-h">关于</div>'
        '<div class="tiny muted">AStock Pro · 构建 2026-10-29 · 免责声明与许可</div></div>'
        '</div>'
    )


def w10_m() -> str:
    return (
        m_top("设置", "⋯")
        + '<div class="m-content">'
        + mcard('<b>基本信息</b>'
                + mrow("服务状态", "接口可达 · SSE 可达")
                + mrow("版本", "0.9.0")
                + mrow("接口契约", "api-v1")
                + mrow("服务器时间", "15:04:05 +08:00")
                + mrow("交易日志", "不可用 ›")
                + mrow("数据源", "腾讯行情 · 14:59:31"))
        + mcard(mrow("模型", "P1 开放 ›") + mrow("数据源", "P1 开放 ›") + mrow("关于", "构建 2026-10-29 ›"))
        + '</div>' + m_nav("更多")
    )


SCREENS = [
    dict(id="w01", code="W01", title="工作台首页", route="/workbench", d=w01_d(), m=w01_m(),
         goal="打开就有事可做：活动任务优先，其次是发起分析，最后才是市场与历史。",
         states=["无活动任务", "市场 stale / error", "搜索无结果", "无最近任务与报告"],
         deps=["GET /market/overview", "GET /jobs?active=true", "GET /reports", "GET /market/search"]),
    dict(id="w02", code="W02", title="统一分析启动器", route="/workbench?launch=1", d=w02_d(), m=w02_m(), app_cls="tall",
         goal="把票、日期、配置填对，并在付费前说清代价；提交中防重复。",
         states=["标的解析失败/多候选", "日期非法", "active_conflict", "提交中", "429 退避", "已有相同任务"],
         deps=["GET /meta/options", "POST /jobs（Idempotency-Key）"]),
    dict(id="w03", code="W03", title="任务列表", route="/jobs", d=w03_d(), m=w03_m(),
         goal="按状态、股票、日期范围找到任务；移动端表格换成摘要卡。",
         states=["空列表", "筛选为空", "接口错误", "加载更多失败", "九种状态徽标"],
         deps=["GET /jobs?status=&ticker=&date_from=&date_to=&active="]),
    dict(id="w04", code="W04", title="任务详情", route="/jobs/:jobId", d=w04_d(), m=w04_m(),
         goal="看清 12 个阶段与控制效果；展开单个阶段读报告；异常时给出下一步。",
         states=["queued/running/paused/failed/interrupted/succeeded", "SSE 重连中", "410 过期", "任务不存在"],
         deps=["GET /jobs/{id}", "GET /jobs/{id}/stages/{stageId}", "POST /jobs/{id}/actions",
               "POST /jobs/{id}/retry", "GET /jobs/{id}/events"]),
    dict(id="w05", code="W05", title="报告库", route="/reports", d=w05_d(), m=w05_m(),
         goal="按票、日期、评级找报告；旧报告缺时间时如实说明。",
         states=["空库", "筛选为空", "接口错误", "旧报告生成时间未知", "legacy_import 角标"],
         deps=["GET /reports?ticker=&date_from=&date_to=&rating="]),
    dict(id="w06", code="W06", title="报告阅读器", route="/reports/:reportId", d=w06_d(), m=w06_m(),
         goal="读完报告、跳到任意章节、显式导出 PDF、按原配置重新分析。",
         states=["正文加载中", "报告不存在", "章节缺失", "导出四态", "历史报告无图表", "重新分析确认"],
         deps=["GET /reports/{id}", "GET /reports/{id}/markdown", "POST /reports/{id}/exports/pdf",
               "GET /exports/{id}", "POST /jobs/{id}/retry"]),
    dict(id="w07", code="W07", title="股票工作区", route="/stocks/:ticker", d=w07_d(), m=w07_m(),
         goal="看盘并就地发起分析；数据三态与区块失败要说清楚。",
         states=["ticker 解析失败", "部分区块失败", "stale 横幅", "空数据", "数据源错误"],
         deps=["GET /stocks/{ticker}/snapshot|kline|intraday|news|reports"]),
    dict(id="w08", code="W08", title="市场与钻取", route="/market", d=w08_d(), m=w08_m(),
         goal="从行业看成分股，再进个股；非交易日与区块延迟不伪装成错误。",
         states=["非交易日 empty", "北向 stale", "行业成分股加载中", "快讯为空"],
         deps=["GET /market/overview", "GET /market/industries", "GET /market/industries/{boardCode}/stocks",
               "GET /market/strong-stocks", "GET /market/newsflash"]),
    dict(id="w09", code="W09", title="交易日志不可用", route="/journal", d=w09_d(), m=w09_m(),
         goal="解释日志是独立应用、当前起不来，并给出可执行的下一步。",
         states=["not_running", "not_installed", "probe_failed", "可用（iframe）"],
         deps=["GET /meta/options → journal"]),
    dict(id="w10", code="W10", title="设置页", route="/settings", d=w10_d(), m=w10_m(),
         goal="看清版本、服务器时间、日志与数据源状态；P0 只做基本信息分组。",
         states=["接口可达/不可达", "日志可用/不可用", "P1 分组占位"],
         deps=["GET /meta/options"]),
]

CSS = """
:root{--ink:#1f2328;--muted:#6b7280;--line:#d0d7de;--soft:#f6f8fa;--accent:#2563eb;--ok:#15803d;--warn:#b45309;--bad:#b91c1c;--bg:#eef1f4}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 "Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;-webkit-font-smoothing:antialiased}
.doc{max-width:1240px;margin:0 auto;padding:28px 20px 60px}
.doc-head h1{font-size:24px;margin:0 0 6px}
.doc-head p{margin:4px 0;color:#4b5563}
.meta{font-size:12px;color:var(--muted)}
.toc{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:18px 0 26px}
.toc a{display:block;background:#fff;border:1px solid var(--line);border-radius:7px;padding:8px 10px;color:var(--ink);text-decoration:none;font-size:12px}
.toc a b{color:var(--accent);margin-right:5px}
.toc a span{display:block;color:var(--muted);font-size:11px}
.screen{margin:0 0 42px;scroll-margin-top:16px}
.screen-head{display:flex;align-items:baseline;gap:10px;margin-bottom:4px;flex-wrap:wrap}
.screen-head .wid{background:var(--ink);color:#fff;border-radius:5px;padding:2px 7px;font:600 12px/1.5 monospace}
.screen-head h2{font-size:19px;margin:0}
.screen-head code{background:#fff;border:1px solid var(--line);border-radius:5px;padding:2px 7px;font-size:12px;color:#57606a;overflow-wrap:anywhere}
.goal{margin:2px 0 12px;color:#4b5563}
.browser{background:#fff;border:1px solid #b9c1ca;border-radius:10px;overflow:hidden;box-shadow:0 6px 22px rgba(15,23,42,.08)}
.browser-bar{display:flex;align-items:center;gap:7px;background:#e6e9ee;padding:8px 12px;border-bottom:1px solid #cfd5dd}
.browser-bar .dot{width:9px;height:9px;border-radius:50%;background:#c3c9d2}
.browser-bar .url{margin-left:10px;background:#fff;border:1px solid #cfd5dd;border-radius:5px;padding:2px 12px;font-size:11px;color:#57606a;max-width:60%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.app{position:relative;font-size:13px;background:#fff;min-height:420px}
.app.tall{min-height:700px}
.topnav{display:flex;align-items:center;gap:18px;padding:10px 16px;border-bottom:1px solid var(--line)}
.brand{font-weight:700;letter-spacing:.02em}
.navlinks{display:flex;gap:14px;color:#57606a;font-size:12px}
.navlinks .active{color:var(--accent);font-weight:600;box-shadow:inset 0 -2px 0 var(--accent)}
.navsearch{margin-left:auto;border:1px solid var(--line);border-radius:6px;padding:4px 10px;color:#9aa2ad;min-width:170px;font-size:12px}
.navgear{color:#57606a;font-size:12px}
.jobbar{display:flex;align-items:center;gap:9px;padding:7px 16px;background:#eff6ff;border-bottom:1px solid #dbeafe;font-size:12px}
.jobbar b{font-size:12px}
.jobbar .mini{width:110px;height:5px;background:#dbeafe;border-radius:3px;overflow:hidden}
.jobbar .mini i{display:block;height:100%;background:var(--accent)}
.jobbar a{margin-left:auto;color:var(--accent);cursor:pointer}
.content{padding:16px}
.dim{opacity:.55}
.grid2{display:grid;grid-template-columns:1.06fr .94fr;gap:12px;margin-bottom:12px}
.grid2:last-child{margin-bottom:0}
.card{border:1px solid var(--line);border-radius:8px;padding:12px;background:#fff;min-width:0}
.card.tight{padding:10px}
.card h3,.m-h{font-size:13px;font-weight:600;margin:0 0 8px}
.card-h{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:8px}
.hero h3{font-size:16px}
.hero p{margin:0 0 10px}
.searchrow{display:flex;gap:8px}
.input{flex:1;border:1px solid var(--line);border-radius:6px;padding:6px 9px;font-size:12px;display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0}
.dropdown{margin-top:8px;border:1px solid var(--line);border-radius:6px;overflow:hidden}
.drop-row{display:flex;justify-content:space-between;padding:6px 9px;border-bottom:1px solid #eef1f4;font-size:12px}
.drop-row:last-child{border-bottom:0}
.indices4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.idx{display:flex;flex-direction:column;gap:2px;border:1px solid #eef1f4;border-radius:6px;padding:7px}
.idx b{font-size:15px}
.indices3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px}
.indices3 .card{display:flex;flex-direction:column;gap:3px}
.indices3 b{font-size:18px}
.market-state{display:flex;gap:8px;align-items:center;margin-top:8px}
.up{color:#b91c1c}.down{color:#15803d}
.badge{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;line-height:1.6;border:1px solid var(--line);white-space:nowrap}
.badge.ok{color:var(--ok);background:#f0fdf4;border-color:#bbf7d0}
.badge.run{color:#1d4ed8;background:#eff6ff;border-color:#bfdbfe}
.badge.warn{color:var(--warn);background:#fffbeb;border-color:#fde68a}
.badge.bad{color:var(--bad);background:#fef2f2;border-color:#fecaca}
.badge.mut{color:#4b5563;background:#f3f4f6;border-color:#e5e7eb}
.btn{display:inline-block;border:1px solid var(--line);background:#fff;border-radius:6px;padding:5px 11px;font-size:12px;white-space:nowrap}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.btn.danger{color:var(--bad);border-color:#fecaca}
.btn.disabled{opacity:.6}
.tbl{width:100%;border-collapse:collapse;font-size:12px}
.tbl th{text-align:left;color:var(--muted);font-weight:600;border-bottom:1px solid var(--line);padding:5px 6px;white-space:nowrap}
.tbl td{border-bottom:1px solid #eef1f4;padding:6px;vertical-align:middle}
.tbl tr:last-child td{border-bottom:0}
.filters{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px;font-size:12px}
.chip{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:11px;color:#374151;background:#fafbfc;white-space:nowrap}
.switch-s{font-size:11px;color:#374151;border:1px solid var(--line);border-radius:999px;padding:3px 10px;background:#fff}
.link{color:var(--accent);cursor:pointer}
.loadmore{text-align:center;color:var(--accent);font-size:12px;padding-top:10px}
.stage-label{font-size:10px;letter-spacing:.08em;color:var(--muted);margin:9px 0 5px}
.stages7{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}
.stages5{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}
.stage{border:1px solid var(--line);border-radius:6px;padding:6px;font-size:11px;min-height:50px;display:flex;flex-direction:column;gap:3px}
.stage .no{color:var(--muted);font-size:10px;font-family:monospace}
.stage.done{background:#f0fdf4;border-color:#bbf7d0}
.stage.active{background:#eff6ff;border-color:#93c5fd;box-shadow:0 0 0 2px #dbeafe}
.stage.pending{background:#fafafa;color:#9ca3af}
.stage.failed{background:#fef2f2;border-color:#fecaca}
.pause-note{margin-top:8px;background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:6px 9px;font-size:11px;color:#92400e}
.stats4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0}
.stat{border:1px solid var(--line);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column;gap:2px;background:#fff}
.stat b{font-size:17px}
.task-head,.reader-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:12px}
.task-title{font-size:18px;font-weight:700;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.task-actions{display:flex;gap:8px;align-items:center}
.acc,.acc-open{border-top:1px solid #eef1f4;padding:8px 0}
.acc{display:flex;align-items:center;gap:8px;color:#6b7280}
.acc-open .acc-head{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.acc-head .muted{margin-left:auto}
.md{border:1px dashed #dbe1e8;border-radius:6px;padding:8px 10px;background:#fcfcfd}
.md-h{font-weight:700;font-size:13px;margin:2px 0 6px}
.md-h.big{font-size:16px}
.md .line{margin:5px 0}
.line{height:7px;background:#e9edf2;border-radius:4px}
.line.w95{width:95%}.line.w92{width:92%}.line.w90{width:90%}.line.w88{width:88%}.line.w84{width:84%}.line.w80{width:80%}.line.w70{width:70%}.line.w60{width:60%}
.overlay{position:absolute;inset:0;background:rgba(15,23,42,.30);display:flex;justify-content:center;align-items:flex-start;padding:56px 20px}
.dialog{background:#fff;border-radius:10px;width:520px;max-width:100%;padding:16px;box-shadow:0 18px 50px rgba(15,23,42,.28)}
.dialog-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px}
.field{margin-bottom:10px}
.field label{display:block;font-size:11px;color:var(--muted);margin-bottom:3px}
.switchrow{display:flex;justify-content:space-between;align-items:center;font-size:12px;margin:8px 0}
.switch{width:30px;height:16px;border-radius:999px;background:#cbd5e1;display:inline-block;position:relative}
.switch.on{background:var(--accent)}
.switch.on:after{content:"";position:absolute;right:2px;top:2px;width:12px;height:12px;border-radius:50%;background:#fff}
.accordion{display:flex;justify-content:space-between;border:1px solid var(--line);border-radius:6px;padding:7px 9px;font-size:12px;margin:8px 0}
.hintwarn{background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:6px 9px;font-size:11px;color:#92400e;margin:10px 0}
.dialog-actions{display:flex;justify-content:flex-end;gap:8px}
.reader{display:grid;grid-template-columns:130px minmax(0,1fr) 220px;gap:12px;align-items:start}
.reader .toc{display:block;margin:0;background:#fff;border:1px solid var(--line);border-radius:8px;padding:8px;position:static}
.toc-item{font-size:10px;color:#6b7280;padding:3px 5px;border-radius:4px;font-family:monospace}
.toc-item.on{background:#eff6ff;color:var(--accent);font-weight:700}
.reading{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px;min-width:0}
.md-table{margin-top:10px;border:1px dashed #dbe1e8;border-radius:6px;padding:14px;text-align:center;font-size:11px;color:var(--muted)}
.side{display:flex;flex-direction:column;gap:10px}
.kv{display:flex;justify-content:space-between;gap:10px;font-size:12px;padding:4px 0;border-bottom:1px solid #f1f4f7}
.kv:last-child{border-bottom:0}
.toast{position:absolute;right:16px;bottom:16px;background:#111827;color:#fff;border-radius:7px;padding:8px 12px;font-size:12px;box-shadow:0 8px 24px rgba(15,23,42,.28)}
.stock-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px}
.price{font-size:26px}
.tabs{display:flex;gap:16px;border-bottom:1px solid var(--line);margin-bottom:12px;font-size:12px;color:#57606a}
.tabs .on{color:var(--accent);font-weight:700;box-shadow:inset 0 -2px 0 var(--accent);padding-bottom:6px}
.tabs span{padding-bottom:6px}
.metrics4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.metric{border:1px solid #eef1f4;border-radius:6px;padding:8px;display:flex;flex-direction:column;gap:2px}
.metric b{font-size:16px}
.chart{border:1px dashed #dbe1e8;border-radius:6px;padding:8px}
.bars{display:flex;align-items:flex-end;gap:3px;height:110px;margin-top:6px}
.bars i{flex:1;background:#c7d2fe;border-radius:2px 2px 0 0;min-height:4px}
.session{display:flex;gap:10px;align-items:center;margin-bottom:10px}
.drawer{position:absolute;top:0;right:0;bottom:0;width:340px;background:#fff;border-left:1px solid var(--line);box-shadow:-12px 0 30px rgba(15,23,42,.12);padding:14px;z-index:3}
.drawer-head{display:flex;justify-content:space-between;margin-bottom:10px}
.scrim{position:absolute;inset:0;background:rgba(15,23,42,.18);z-index:2}
.iframe-placeholder{min-height:480px;border:1px dashed #b9c1ca;border-radius:8px;background:#f8fafc;display:flex;align-items:center;justify-content:center;padding:20px}
.journal-card{max-width:420px;text-align:center;background:#fff;border:1px solid var(--line);border-radius:10px;padding:22px}
.journal-icon{width:44px;height:44px;border-radius:12px;background:#e5e7eb;color:#6b7280;font:700 20px/44px monospace;margin:0 auto 10px}
.journal-card h3{margin:0 0 6px;font-size:16px}
.code,.m-code{font-family:Consolas,monospace;background:#f3f4f6;border:1px solid var(--line);border-radius:6px;padding:7px 10px;margin:10px 0 6px;font-size:12px;overflow-wrap:anywhere}
.journal-actions{display:flex;gap:8px;justify-content:center;margin-top:10px}
.settings{display:grid;grid-template-columns:180px minmax(0,1fr);gap:12px;align-items:start}
.settings-nav{background:#fff;border:1px solid var(--line);border-radius:8px;padding:6px}
.set-item{font-size:12px;padding:7px 9px;border-radius:6px;color:#57606a}
.set-item.on{background:#eff6ff;color:var(--accent);font-weight:700}
.settings-body{margin-bottom:12px}
.notes{display:grid;grid-template-columns:1.15fr .85fr;gap:14px;margin-top:12px;font-size:12px}
.notes h3{font-size:12px;margin:0 0 4px;color:#374151}
.notes ul{margin:0;padding-left:18px;color:#4b5563}
.notes li{margin:2px 0}
.doc-foot{margin-top:30px;font-size:12px;color:var(--muted);border-top:1px solid #d6dbe1;padding-top:12px}
/* mobile page */
.mobile-page{max-width:460px;margin:0 auto;padding:18px 12px 50px}
.mobile-page .doc-head h1{font-size:20px}
.phone{background:#fff;border:1px solid #b9c1ca;border-radius:20px;overflow:hidden;box-shadow:0 10px 30px rgba(15,23,42,.12);margin-bottom:8px;display:flex;flex-direction:column;position:relative}
.m-top{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--line);font-weight:700;font-size:14px}
.m-top-r{font-size:11px;color:var(--accent);font-weight:500;display:flex;align-items:center;min-height:44px;padding-left:12px}
.m-jobbar{display:flex;align-items:center;gap:6px;padding:6px 12px;background:#eff6ff;border-bottom:1px solid #dbeafe;font-size:11px;flex-wrap:wrap}
.m-job-more{margin-left:auto;color:var(--accent)}
.m-content{padding:10px;display:flex;flex-direction:column;gap:9px;flex:1}
.m-card{border:1px solid var(--line);border-radius:9px;padding:10px;min-width:0;overflow-wrap:anywhere}
.m-h{font-size:12px;font-weight:700;margin-bottom:6px}
.m-label{font-size:11px;color:var(--muted);margin-bottom:4px}
.m-input{border:1px solid var(--line);border-radius:6px;padding:7px 9px;font-size:12px;margin-bottom:6px}
.m-primary{display:flex;align-items:center;justify-content:center;min-height:44px;text-align:center;background:var(--accent);color:#fff;border-radius:7px;padding:9px;font-size:13px;font-weight:700;margin-top:6px}
.m-primary.half{flex:1;margin:0}
.m-primary.disabled{background:#94a3b8}
.m-btn{display:flex;align-items:center;justify-content:center;min-height:44px;border:1px solid var(--line);border-radius:7px;padding:8px 10px;font-size:12px;text-align:center}
.m-btn.quiet{color:#57606a}
.m-btn-danger{display:flex;align-items:center;justify-content:center;min-height:44px;border:1px solid #fecaca;color:var(--bad);border-radius:7px;padding:8px 10px;font-size:12px;text-align:center}
.m-indices{display:flex;gap:8px;overflow-x:auto;padding-bottom:2px}
.m-index{min-width:110px;flex:1;border:1px solid #eef1f4;border-radius:7px;padding:7px;display:flex;flex-direction:column;gap:1px}
.m-index b{font-size:14px}
.m-list-row{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid #eef1f4;font-size:12px;min-width:0}
.m-list-row:last-child{border-bottom:0}
.m-list-row>span:first-child{overflow-wrap:anywhere}
.m-chips{display:flex;gap:6px;flex-wrap:wrap}
.m-row-between{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.m-tabs{display:flex;gap:14px;overflow-x:auto;font-size:12px;color:#57606a;border-bottom:1px solid var(--line);padding-bottom:2px}
.m-tabs .on{color:var(--accent);font-weight:700;box-shadow:inset 0 -2px 0 var(--accent);padding-bottom:4px}
.m-metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
.m-metrics>div{display:flex;flex-direction:column;gap:1px}
.chart-scroll{overflow-x:auto;margin-top:4px}
.chart-inner{width:520px}
.m-sticky{display:flex;align-items:center;gap:8px;padding:8px 10px;border-top:1px solid var(--line);background:#fff;position:sticky;bottom:0;z-index:2}
.m-sticky>*:first-child{margin-right:auto}
.m-nav{display:grid;grid-template-columns:repeat(5,1fr);border-top:1px solid var(--line);background:#fff;font-size:10px;text-align:center;color:#57606a;position:sticky;bottom:0}
.m-nav span{min-height:44px;display:flex;align-items:center;justify-content:center}
.m-nav .active{color:var(--accent);font-weight:700}
.m-warn{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:9px;font-size:12px;color:#92400e}
.m-warn.small{font-size:11px;padding:6px 8px}
.m-warn-actions{display:flex;gap:6px;margin-top:7px;flex-wrap:wrap}
.m-warn-actions .btn{font-size:11px}
.m-stage-list{border:1px solid var(--line);border-radius:9px;overflow:hidden}
.m-stage{display:flex;justify-content:space-between;gap:8px;padding:7px 10px;border-bottom:1px solid #eef1f4;font-size:12px}
.m-stage:last-child{border-bottom:0}
.m-stage.done{background:#f7fdf9}
.m-stage.active{background:#eff6ff;font-weight:700;color:#1d4ed8}
.m-stage.pending{color:#9ca3af}
.m-stats{display:flex;gap:10px;flex-wrap:wrap;font-size:11px;color:#4b5563}
.m-drawer{position:absolute;left:0;right:0;bottom:0;background:#fff;border-top:1px solid var(--line);border-radius:14px 14px 0 0;box-shadow:0 -12px 30px rgba(15,23,42,.18);padding:12px;z-index:4;max-height:62%;overflow:auto}
.m-drawer-head{display:flex;justify-content:space-between;margin-bottom:6px;font-size:12px}
.m-toc{border:1px solid var(--line);border-radius:8px;padding:8px;max-height:180px;overflow:auto}
.m-toc-row{font-size:10px;color:#6b7280;padding:2px 4px;font-family:monospace}
.m-toc-row.on{background:#eff6ff;color:var(--accent);font-weight:700}
.m-switch{display:flex;justify-content:space-between;align-items:center;font-size:12px;margin-top:4px}
.mobile-page .toc{grid-template-columns:1fr 1fr;margin:14px 0 22px}
.mobile-page .notes{grid-template-columns:1fr}
@media (max-width:420px){.mobile-page{padding:12px 8px 40px}.m-content{padding:8px}.m-card{padding:9px}.m-top{padding:10px 12px}.mobile-page .doc-head h1{font-size:18px}}
"""


def screen_block(s: dict, mode: str) -> str:
    body = s["d"] if mode == "desktop" else s["m"]
    if mode == "desktop":
        frame = (
            '<div class="browser"><div class="browser-bar">'
            '<span class="dot"></span><span class="dot"></span><span class="dot"></span>'
            f'<span class="url">http://127.0.0.1:8000{s["route"]}</span></div>'
            f'<div class="app {s.get("app_cls", "")}">{body}</div></div>'
        )
    else:
        frame = f'<div class="phone">{body}</div>'
    states = "".join(f"<li>{x}</li>" for x in s["states"])
    deps = "".join(f"<li><code>{x}</code></li>" for x in s["deps"])
    return (
        f'<section class="screen" id="{s["id"]}">'
        '<div class="screen-head">'
        f'<span class="wid">{s["code"]}</span><h2>{s["title"]}</h2><code>{s["route"]}</code></div>'
        f'<p class="goal">{s["goal"]}</p>'
        f'{frame}'
        '<div class="notes"><div><h3>要确认的状态</h3><ul>' + states + '</ul></div>'
        '<div><h3>依赖接口</h3><ul>' + deps + '</ul></div></div>'
        '</section>'
    )


def page(mode: str) -> str:
    label = "桌面" if mode == "desktop" else "移动"
    cls = "doc" if mode == "desktop" else "doc mobile-page"
    toc = "".join(
        f'<a href="#{s["id"]}"><b>{s["code"]}</b>{s["title"]}<span>{s["route"]}</span></a>'
        for s in SCREENS
    )
    blocks = "".join(screen_block(s, mode) for s in SCREENS)
    note = (
        "按 1440px 宽绘制，浏览器框仅示意。"
        if mode == "desktop"
        else "按 390px 宽绘制，同时必须在 360px 下不出现页面级横向滚动；表格已换成摘要卡。"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AStock Pro P0 核心页面线框（{label}）</title>
<style>{CSS}</style>
</head>
<body>
<div class="{cls}">
<header class="doc-head">
<h1>AStock Pro P0 核心页面线框（{label}）</h1>
<p>十张线框覆盖 Day 5 主线；只表达结构与状态，不代表最终视觉。</p>
<p class="meta">2026-10-29 · 与 docs/upgrade/contracts/core-wireframes.md 同步 · {note}</p>
</header>
<nav class="toc">{toc}</nav>
{blocks}
<footer class="doc-foot">线框版本 2026-10-29。任何与 core-wireframes.md 不一致之处，以 md 为准并回写本文件。</footer>
</div>
</body>
</html>
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for mode, name in (("desktop", "core-wireframes-desktop.html"), ("mobile", "core-wireframes-mobile.html")):
        path = OUT_DIR / name
        path.write_text(page(mode), encoding="utf-8")
        print(path, path.stat().st_size)


if __name__ == "__main__":
    main()
