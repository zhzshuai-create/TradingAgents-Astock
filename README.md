<h1 align="center">TradingAgents-Astock</h1>

<p align="center">
  A股多智能体投研系统 + 实时数据看板 · 统一投资研究平台
</p>

<p align="center">
  <b>⚠️ 免责声明：本项目仅供学习研究与技术演示，不构成任何投资建议。</b>
</p>

<p align="center">
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/License-Apache_2.0-blue"/></a>
</p>

---

## 项目来源

本项目基于 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 的 A 股特化版本 [simonlin1212/tradingagents-astock](https://github.com/simonlin1212/tradingagents-astock) 进行二次开发。

感谢原作者的开源贡献。

---

## 我的改动

在原项目基础上做了以下改进：

### UI 重设计
- **抛弃传统侧边栏**，改为顶部导航栏布局，界面更简洁
- **水平模式切换**：AI 分析报告 与 实时数据看板 一键切换，无需多开页面
- **统一搜索框**：顶部输入股票代码，回车或点击箭头即可搜索

### 功能合并
- **实时数据看板** 嵌入统一平台，包含 4 个 Tab：
  - 📈 个股估值（PE/PB/PEG/机构预期/K线/概念板块）
  - 🔥 强势股归因（当日强势股 + 题材热度排行）
  - 💰 资金流向（北向资金 + 行业排名）
  - 📰 资讯（财联社快讯 + 个股新闻）
- **数据函数模块化** — 从 `stock_ui.py` 提取全部数据接口到 `web/data_functions.py`
- **七层数据架构** — 覆盖行情、研报、信号、资金面、新闻、基础数据、公告

---

## 快速开始

```bash
git clone https://github.com/zhzshuai-create/TradingAgents-Astock.git
cd TradingAgents-Astock
pip install -r requirements.txt
```

配置 `.env`（参考 `.env.example`）：

```bash
DEEPSEEK_API_KEY=sk-xxx
LLM_PROVIDER=deepseek
DEEP_THINK_LLM=deepseek-chat
QUICK_THINK_LLM=deepseek-chat
```

启动 Web UI：

```bash
streamlit run web/app.py
```

打开 http://localhost:8501

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 前端 | Streamlit |
| 数据 | mootdx + 腾讯财经 + 东财 + 同花顺 |
| AI 框架 | LangChain + LangGraph |
| LLM | DeepSeek / OpenAI / Anthropic |

---

## 致谢

- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — 多智能体投研框架
- [simonlin1212/tradingagents-astock](https://github.com/simonlin1212/tradingagents-astock) — A 股特化版本
- [simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data) — A 股数据工具包

---

## 许可证

[Apache License 2.0](./LICENSE)

本项目继承自上游开源项目，详见 [NOTICE](./NOTICE)。
