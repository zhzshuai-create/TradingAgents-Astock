<h1 align="center">AStock Pro</h1>

<p align="center">
  AI 多智能体投资研究平台 · 实时数据看板<br>
  基于 TradingAgents 框架的 A 股深度特化定制版
</p>

<p align="center">
  <b>⚠️ 免责声明：本项目仅供学习研究与技术演示，不构成任何投资建议。</b>
</p>

<p align="center">
  <a href="https://github.com/zhzshuai-create/TradingAgents-Astock"><img alt="GitHub Repo" src="https://img.shields.io/badge/GitHub-zhzshuai--create%2FTradingAgents--Astock-orange?logo=github"/></a>
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/License-Apache_2.0-blue"/></a>
  <a href="https://arxiv.org/abs/2412.20138"><img alt="论文" src="https://img.shields.io/badge/论文-arXiv_2412.20138-B31B1B?logo=arxiv"/></a>
</p>

---

## 这是什么？

**AStock Pro** 是一个 A 股全栈 AI 投资研究平台，在 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 和 [simonlin1212/TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock) 的基础上进行了深度定制。

核心能力：**7 个 AI 分析师** 并行收集数据 → **多空辩论** → **三方风险辩论** → **最终投资决策**，全自动生成完整中文研报。

---

## 🎯 本版特色功能

| 功能 | 说明 |
|------|------|
| 🌓 **即时主题切换** | 亮色 / 暖暗色一键切换，**纯 JS/CSS 零延迟**，localStorage 持久化 |
| 📈 **实时数据看板** | K 线周期选择器 + 腾讯行情 + 北向资金 + 概念板块 + 行业对比 |
| 📂 **可展开侧边栏** | 顶部 ☰ 按钮切换，股票输入 / LLM 配置 / 历史记录随时访问 |
| 🔥 **强势股归因** | 同花顺当日强势股列表 + 题材标签（AI 算力 / 低空经济 / MLCC...） |
| ⏸️ **分析暂停/继续** | 多 Agent 分析过程随时暂停、继续或停止 |
| 📥 **双格式报告导出** | Markdown（零依赖）和 PDF 中文完整报告一键下载 |
| 🛡️ **超时保护** | 全局 15s 请求超时防止挂死 + 卡死检测告警 |
| 🎨 **顶部导航栏** | 品牌化自定义导航 · 股票搜索 · 模式切换 · 主题切换 |

### 主题系统

- ☀️ **亮色模式**：白底黑字 + 橙色强调，高对比度，白天清晰阅读
- 🌙 **暗色模式**：暖黑底 + 暖白字，GitHub 风格，长时间盯盘不刺眼
- ⚡ **切换机制**：纯 JavaScript/CSS 类切换，**不触发页面重载**，0 秒延迟

### 数据看板

输入 6 位代码即可查看：实时行情 · PE/PB 估值 · 交互式 K 线图 · 北向资金流向 · 概念板块归属 · 同花顺热点归因 · 行业对比 · 财联社实时快讯

---

## 🧠 7 个 AI 分析师

| 角色 | 职责 | 特化 |
|------|------|------|
| 🏪 市场分析师 | K 线形态、技术指标、量价分析 | A 股适配 |
| 💬 舆情分析师 | 社交媒体情绪、散户讨论热度 | A 股适配 |
| 📰 新闻分析师 | 行业新闻、公告、宏观事件 | A 股适配 |
| 📊 基本面分析师 | 财报三表、盈利能力、估值分析 | A 股适配 |
| 🏛️ 政策分析师 | 监管政策、产业政策、窗口指导 | **A 股特化** |
| 🔥 游资追踪师 | 龙虎榜、大单流向、主力资金动态 | **A 股特化** |
| 🔓 解禁监控师 | 限售股解禁、大股东减持、股权质押 | **A 股特化** |

所有分析师报告 → Bull/Bear 辩论 → Aggressive/Conservative/Neutral 三方风险辩论 → Portfolio Manager 最终决策

---

## 📡 数据源

全部免费，无需 API Key：

| 来源 | 提供内容 |
|------|---------|
| **mootdx** | OHLCV K 线、财务快照、F10 文本（TCP 7709） |
| **腾讯财经** | PE / PB / 市值 / 换手率 |
| **东方财富** | 龙虎榜、限售解禁、板块行情、个股新闻、资金流 |
| **新浪财经** | K 线历史、财报三表 |
| **同花顺** | EPS 一致预期、强势股列表、题材热点 |
| **财联社** | 全球财经快讯 |
| **百度股市通** | 概念板块分类 |

---

## 🚀 快速开始

### 环境要求

- Python >= 3.10
- Windows / macOS / Linux

### 安装

```bash
git clone https://github.com/zhzshuai-create/TradingAgents-Astock.git
cd TradingAgents-Astock
pip install -e .
```

### LLM 配置

在项目根目录创建 `.env`：

```bash
# 推荐：DeepSeek（国内直连，性价比高）
DEEPSEEK_API_KEY=sk-xxx

# 或 MiniMax / 通义千问 / 智谱 / OpenAI / Anthropic 等
```

### 启动 Web UI

```bash
streamlit run web/app.py
```

或双击桌面 `AStock-UI.bat` 一键启动。

打开浏览器访问 `http://localhost:8501`。

---

## 📂 项目结构

```
TradingAgents-Astock/
├── tradingagents/
│   ├── agents/              # 7 个 AI 分析师 + 辩论逻辑
│   │   ├── analysts/        # 市场/舆情/新闻/基本面/政策/游资/解禁
│   │   ├── researchers/     # Bull / Bear 研究员
│   │   ├── risk_mgmt/       # 激进 / 保守 / 中立 辩手
│   │   ├── managers/        # Research Manager + Portfolio Manager
│   │   └── trader/          # 交易执行（A 股约束）
│   ├── dataflows/           # 数据层（mootdx/东财/新浪/同花顺）
│   │   └── a_stock.py       # A 股数据 vendor（零第三方数据库依赖）
│   └── graph/               # LangGraph 工作流编排
├── web/                     # Streamlit Web UI
│   ├── app.py               # 主入口
│   ├── components/          # 侧边栏/进度/报告展示组件
│   ├── chart_utils.py       # Altair 交互式 K 线图
│   ├── data_functions.py    # 实时行情/北向/概念/行业数据
│   └── ...
├── cli/                     # 命令行工具
├── examples/                # 批量分析示例
└── tests/                   # 测试套件
```

---

## 致谢

本项目基于以下开源项目：

- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — 多 Agent LLM 金融交易框架，[论文](https://arxiv.org/abs/2412.20138)
- [simonlin1212/TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock) — A 股数据层 + 特化分析师角色

本仓库是 simonlin1212 版本的独立定制 fork，增加了实时数据看板、即时主题切换、可展开侧边栏、卡死检测、全局超时保护等功能。

---

## 许可证

[Apache License 2.0](./LICENSE)

---

## 免责声明

> **本项目仅供学习研究与技术演示，不构成任何投资建议。**
>
> - 本系统产出的所有分析报告和交易信号均由 AI 自动生成，可能存在错误或偏差
> - 投资决策请咨询持有中国证监会颁发资质的专业机构
> - 作者不对使用本工具产生的任何投资损失承担责任
> - 股市有风险，投资需谨慎
