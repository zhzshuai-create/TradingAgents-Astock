# TradingAgents-Astock

[English](README.en.md) | [简体中文](README.md)

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python" alt="Python >=3.10">
  <img src="https://img.shields.io/badge/version-0.2.18-green" alt="Version 0.2.18">
  <img src="https://img.shields.io/badge/license-Apache%202.0-orange?logo=apache" alt="Apache 2.0">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey" alt="Platform">
  <a href="https://github.com/zhzshuai-create/TradingAgents-Astock/actions/workflows/ci.yml"><img src="https://github.com/zhzshuai-create/TradingAgents-Astock/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/tests-171%20passed-brightgreen" alt="Tests">
</p>

AI 多智能体 A 股投资研究平台，集成实时数据看板。基于 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)（65K+ Stars）的深度定制版。

> ⚠️ 仅供学习研究，不构成投资建议。

---

## 📸 界面预览

### 30 秒概览

<p align="center">
  <img src="assets/demo.gif" width="90%" alt="系统演示：启动动画 → AI 分析 → 实时看板 → 强势股归因 → 暗色主题"/>
</p>

### 启动过渡动画

冷启动期间全屏遮罩播放"7 个分析师节点逐个点亮 → 汇聚到投资决策节点"的过渡动画，盖住 3~5s 的空白等待；每个标签页播一次，URL 加 `?noboot=1` 可跳过。亮/暗主题自适应：

<p align="center">
  <img src="assets/boot-splash-light.png" width="49%" alt="启动过渡动画-亮色"/>
  <img src="assets/boot-splash-dark.png" width="49%" alt="启动过渡动画-暗色"/>
</p>

### 响应式顶栏

中等宽度（≤1680px）下指数条自动换行到第二行居中展示，模式导航、模型徽标、主题开关互不干扰；1920px 布局不变：

<p align="center">
  <img src="assets/topbar-responsive-fix.png" width="90%" alt="顶栏响应式修复：1440px 修复前后对比"/>
</p>

### AI 分析报告模式

7 个 AI 分析师（可开启并行加速）→ 多空辩论 → 风控评估 → 最终投资决策。

<p align="center">
  <img src="assets/screenshot-analysis.png" width="90%" alt="AI分析报告界面"/>
</p>

### 实时数据报告看板

K 线（分时/5日/30日/全部）· 实时估值指标 · 概念板块 · 强势股列表。

<p align="center">
  <img src="assets/dashboard-report.png" width="90%" alt="实时数据报告看板"/>
</p>

### AI分析报告界面

同一看板在亮色主题下的展示效果。

<p align="center">
  <img src="assets/analysis-interface.png" width="90%" alt="AI分析报告界面"/>
</p>

### 分析进度

12 阶段 pipeline 实时进度，7 分析师报告可展开查看，支持暂停/继续/停止。

<p align="center">
  <img src="assets/screenshot-progress.png" width="90%" alt="分析进度界面"/>
</p>

### 完整报告导出

信号卡片（Buy/Hold/Sell）+ 7 份分析师报告 + 多空辩论 + 风控评估，支持 PDF / Markdown 下载。

<p align="center">
  <img src="assets/screenshot-pdf.png" width="90%" alt="报告导出"/>
</p>

### K 线周期对比

同一股票不同时间周期（分时/5日/30日/全部）的 K 线切换对比。

<p align="center">
  <img src="assets/screenshot-kline-views.png" width="90%" alt="K线周期对比"/>
</p>

### 交易日志（嵌入式复盘看板）

顶部模式切到 **交易日志**，即以 iframe 嵌入独立的 trade-journal 复盘应用（需与本项目同级目录）：
零侵入集成——平台不读写日志代码与数据，仅通过 URL 回显。

**资金曲线点击联动**：指标卡 + 期望值判定 + 资金曲线，曲线上每个点 = 一笔已平仓交易（一一对应）。

<p align="center">
  <img src="assets/trade-journal-dashboard.png" width="90%" alt="交易日志-资金曲线"/>
</p>

**点击回显记录**：点任意点即展示该笔完整明细（股数/买卖价/收益率/账户影响/手续费/卖出原因）与分布图。

<p align="center">
  <img src="assets/trade-journal-click-record.png" width="90%" alt="交易日志-点击回显记录"/>
</p>

**行为诊断**：持仓周期与换手、仓位集中度（top5 标的）、单笔收益分布直方图（含均值线）。

<p align="center">
  <img src="assets/trade-journal-metrics.png" width="90%" alt="交易日志-行为诊断指标"/>
</p>

---

## 功能特性

| 功能 | 说明 |
|------|------|
| 🧠 **AI 分析报告** | 7 个 AI 分析师 → Bull/Bear 辩论 → 三方风控 → 最终决策，全自动中文研报 |
| 📈 **实时数据看板** | 个股搜索（代码/中文名）· OHLC 蜡烛图（MA 均线 + 量价联动缩放）· 腾讯实时行情 · 北向资金 · 概念板块归因 · 行业对比 |
| 🌓 **即时主题切换** | 亮色 / 暗色一键切换，纯 JS + CSS 零延迟，localStorage 持久化记忆 |
| 📂 **可展开侧边栏** | 顶部 ☰ 按钮控制，内含股票代码输入、LLM 模型配置、历史记录 |
| 🔥 **强势股归因** | 同花顺当日强势股 + 题材标签（AI 算力 / 低空经济 / MLCC…） |
| ⏸️ **分析过程可控** | 随时暂停 / 继续 / 停止，卡死自动检测告警 |
| 📥 **双格式导出** | Markdown（零依赖）和 PDF 中文完整报告，跨平台字体适配 |
| 📝 **历史记录** | 自动保存所有分析，支持代码/日期搜索，一键回溯查看 |
| ⚡ **分析师并行（可选）** | 设 `TA_PARALLEL_ANALYSTS=1` 后 7 个分析师 fan-out 并发执行，墙钟时间约等于最慢的一个 |
| 💾 **断点续跑** | 开启 checkpoint 后分析中途崩溃可从最后完成的节点恢复，配合暂停/停止 |
| 🛡️ **数据层防封** | 东财全端点统一节流 + 失败自动重试；腾讯/新浪/同花顺单发请求也带一次重试 |
| 📖 **交易日志（嵌入）** | iframe 嵌入 trade-journal 复盘看板：资金曲线点击联动 · 持仓周期/仓位集中度/收益分布 |

---

## 性能与实验

以下均为 2026-09-13 基准实验的原始结果（模型：小米 MiMo `mimo-v2.5`，OpenAI 兼容协议直连；完整 7 分析师 pipeline）。复现脚本与原始数据见 [experiments/](experiments/)。

### T1 · 分析师并行加速

`TA_PARALLEL_ANALYSTS=1` 后 7 个分析师 fan-out 并发执行，墙钟时间约等于最慢的一个：

| 标的 | 串行 | 并行 | 降幅 |
|------|------|------|------|
| 000858 五粮液 | 694.4s | 559.3s | **-19.5%** |
| 601318 中国平安 | 684.3s | 508.2s | **-25.7%** |
| 300750 宁德时代 | 8001.7s* | 466.7s | **-94.2%** |

\* 300750 串行 8002s 为 LLM 服务商当日延迟方差异常（同配置其余串行约 690s）；并行 467s 恰好体现 fan-out 对单点延迟的天然免疫——最慢的分析师不再拖累整体。

### T2 · 信号方向回测

信号日 2026-08-13 产出 6 只标的的分析信号，以评估日 2026-09-11 收盘验证：

- 方向性信号 **2 / 2 全部命中**（000001、601899 的 Overweight，区间分别 +4.36% / +0.16%）
- 其余 4 条为 Hold（中性信号不参与方向命中，体现风控偏保守）
- ⚠️ 样本量小（6 只 / 1 个月），仅用于验证系统能产出可回溯、可评估的方向性输出，不构成投资建议

### 启动性能优化

冷启动顶部 spinner 的"裸暴露"时长（用户看到加载圈但无内容的时间）从 **2.80s 降至 0.15s**（各 3 次取中位数，证据数据在 [docs/boot-splash/evidence/](docs/boot-splash/evidence/)）：启动过渡动画遮罩首帧 0.69s 盖住空白期，主内容就绪从 3.32s 提前到 2.13s。

---

## 项目结构

```
TradingAgents-Astock/
├── tradingagents/          # 核心框架
│   ├── agents/             # 7 个 AI 分析师 + Bull/Bear 辩论
│   ├── dataflows/          # 数据层（所有行情/财务/新闻接口）
│   │   ├── a_stock/        # A 股数据 vendor（包）
│   │   │   ├── _common.py      # 共享基础设施：代码解析、mootdx 客户端、东财节流、
│   │   │   │                   #   腾讯/同花顺/新浪 helpers、OHLCV 缓存与补数链
│   │   │   ├── quote.py        # K 线行情 + 技术指标
│   │   │   ├── fundamentals.py # 估值快照 + 财报三表 + 盈利预测 + 股东研究
│   │   │   ├── news.py         # 个股新闻 + 全球财经资讯
│   │   │   └── signals.py      # 热股题材 / 北向资金 / 资金流 / 龙虎榜 / 解禁 / 行业对比
│   │   └── interface.py    # vendor 路由模式
│   └── graph/              # LangGraph 分析流程编排（串行链 / 并行 fan-out 可切换）
├── web/                    # Streamlit Web UI
│   ├── app.py              # Web 入口 + AI 分析模式
│   ├── launch.py           # 启动模块（tradingagents-web 命令）
│   ├── data_functions.py   # 看板数据适配层（核心数据层之上的缓存包装）
│   ├── text_utils.py       # 共享文本清洗（think 标签等）
│   ├── runner.py           # 分析运行器（后台线程，支持暂停/继续/停止/断点）
│   ├── components/         # UI 组件
│   │   └── data_dashboard.py   # 实时数据看板渲染
│   └── pdf_export.py       # PDF 导出
├── cli/                    # 命令行工具
│   ├── main.py             # CLI 入口 + 分析编排
│   └── display.py          # 终端显示层（MessageBuffer / 实时布局 / 报告展示）
├── examples/               # 示例脚本
│   └── run_cases.py        # 批量分析样例
├── scripts/                # 工具脚本
├── experiments/            # 性能/回测实验脚本 + 基准原始数据（见 experiments/README.md）
├── tests/                  # 测试（171，含数据解析离线单测与图拓扑测试）
├── .github/workflows/      # CI（ubuntu/windows × py3.10/3.13 测试矩阵）
├── assets/                 # 截图等静态资源
├── issues/                 # Issue 归档记录
├── pyproject.toml          # 项目配置与依赖
└── CHANGELOG.md            # 版本变更日志
```

---

## 快速开始

### 环境要求

- Python >= 3.10
- 无需 Docker（可选）

### 安装

```bash
git clone https://github.com/zhzshuai-create/TradingAgents-Astock.git
cd TradingAgents-Astock
pip install -e .
```

如需使用 Google Gemini 模型（可选）：

```bash
pip install -e ".[google]"
```

### 配置 LLM

创建 `.env` 文件（可参考 `.env.example`）：

```bash
DEEPSEEK_API_KEY=sk-xxx
# 或其他兼容 OpenAI 协议的模型
```

### 启动

**Web 界面（推荐）：**

```bash
streamlit run web/app.py
```

**命令行模式：**

```bash
tradingagents           # 交互式 CLI
tradingagents --help    # 查看所有命令
```

浏览器访问 `http://localhost:8501`。

**同时启动嵌入式交易日志（可选）：**

顶部模式切到"交易日志"需要独立的 trade-journal 应用跑在 8502。一键同时拉起两者：

```bash
run_all.bat                       # Windows 双击
# 或
python web/launch.py --with-journal
```

要求 trade-journal 与本项目同级目录。未启动时，"交易日志"页会给出手动启动引导而非白屏。

### 可选：分析师并行加速

默认 7 个分析师按顺序执行。设置环境变量后改为 fan-out 并发（墙钟时间约等于最慢的分析师）：

```bash
# Windows PowerShell
$env:TA_PARALLEL_ANALYSTS = "1"; streamlit run web/app.py

# macOS / Linux
TA_PARALLEL_ANALYSTS=1 streamlit run web/app.py
```

---

## 数据源

mootdx · 腾讯财经 · 东方财富 · 新浪财经 · 同花顺 · 财联社 · 百度股市通

全部免费直连，无需 API Key。

| 来源 | 协议 | 数据类型 |
|------|------|----------|
| mootdx | TCP 7709 | OHLCV K线、财务快照、F10 |
| 腾讯财经 | HTTP | PE/PB/市值/换手率 |
| 东方财富 | HTTP | 龙虎榜、解禁、板块行情、资金流 |
| 新浪财经 | HTTP | K线历史、财报三表 |
| 同花顺 | HTTP | EPS一致预期、热股题材 |
| 财联社 | HTTP | 全球财经快讯 |
| 百度股市通 | HTTP | 概念板块归属 |

---

## 常见问题

### pip install 报 httpx 依赖冲突？

`pip install -e .`（默认安装）不会触发冲突。仅当你额外安装 `[google]` 可选依赖时，mootdx（要求 `httpx<0.26`）与 `langchain-google-genai`（要求 `httpx>=0.28`）互斥。

**解决方案**：
- **推荐**：不用 Google 模型时不装 `[google]`，用 DeepSeek 等国内直连模型即可
- **备选**：手动升级 httpx — mootdx 实际走 TCP 协议，运行时并不调用 httpx（0.11.7 在 httpx 0.28.1 下实测正常）：
  ```bash
  pip install --no-deps httpx>=0.28.1
  ```
- **最稳妥**：用 Google 模型时单独建一个 venv

### 不用 Web 界面怎么批量跑？

使用 `examples/run_cases.py`，支持批量分析多只股票并输出完整报告：

```bash
python examples/run_cases.py
```

每只标的会生成与 CLI 完全一致的 `complete_report.md`（含分析师/研究/交易/风险/组合五个分区 + 合并报告）和 `summary.json`。

### 中文股票名输入支持吗？

支持。输入「贵州茅台」「宁德时代」等中文名称，系统自动解析为 6 位代码。解析失败时请直接输入 6 位数字代码。

### 东财接口被封了怎么办？

v0.2.11 起内置限流机制（请求间隔 ≥ 1s + 随机抖动），且所有东财端点（含看板刷新）都走统一节流入口并带失败自动重试，一般不会触发封禁。如果频繁使用仍被封，可在 `.env` 中增加间隔：

```bash
EM_MIN_INTERVAL=2.0
```

等待几分钟后 IP 会自动解封。

### macOS/Linux 下 PDF 中文不显示？

确保系统安装了中文字体（如 WenQuanYi、Noto Sans CJK）。程序会自动检测可用字体，也可通过环境变量指定：

```bash
FPDF_FONT_PATH=/usr/share/fonts/your-font.ttf
```

---

## 致谢

- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — 多 Agent 金融交易框架
- [simonlin1212/TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock) — A 股数据层与特化分析师角色

## 许可证

Apache 2.0 — 详见 [LICENSE](LICENSE)
