# AStock Pro

AI 多智能体 A 股投资研究平台，集成实时数据看板。

> ⚠️ 仅供学习研究，不构成投资建议。

---

## 功能

- **AI 分析报告**：7 个 AI 分析师并行采集数据 → 多空辩论 → 风控评估 → 最终决策，全自动生成中文研报
- **实时数据看板**：K 线（分时/5日/30日/全部）· 北向资金 · 概念板块 · 强势股归因 · 行业对比
- **即时主题切换**：亮色/暗色一键切换，纯 JS 零延迟
- **可展开侧边栏**：顶部 ☰ 按钮控制，内含股票输入、模型配置、历史记录
- **PDF/Markdown 导出**：中文完整报告，适配 Windows/macOS/Linux 字体
- **暂停/继续/卡死检测**：分析过程可控，异常自动告警

## 快速开始

```bash
git clone https://github.com/zhzshuai-create/TradingAgents-Astock.git
cd TradingAgents-Astock
pip install -e .
```

在根目录创建 `.env`：

```bash
DEEPSEEK_API_KEY=sk-xxx
```

启动：

```bash
streamlit run web/app.py
# 或双击桌面 AStock-UI.bat
```

浏览器访问 `http://localhost:8501`。

## 数据源

mootdx · 腾讯财经 · 东方财富 · 新浪财经 · 同花顺 · 财联社 · 百度股市通（全部免费，无需 API Key）

## 技术栈

Python · Streamlit · LangGraph · Altair · 7 个 LLM Agent（市场/舆情/新闻/基本面/政策/游资/解禁）

## 致谢

- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — 多 Agent 金融交易框架
- [simonlin1212/TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock) — A 股数据层与特化分析师

## 许可证

Apache 2.0
