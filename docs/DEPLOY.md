# 部署指南（在线 Demo）

目标：让面试官/陌生访客无需 clone 仓库就能打开系统。两条路线，按可行性排序。

## 路线 A：轻量云服务器（推荐，全功能）

一台最低配 VPS（1C1G 即可，国内访问 github/pypi 需镜像）+ Caddy/Nginx 反代 8501：

```bash
git clone https://github.com/zhzshuai-create/TradingAgents-Astock.git
cd TradingAgents-Astock && pip install -e .
cp .env.example .env   # 填入 LLM key（DEEPSEEK_API_KEY 最省）
streamlit run web/app.py --server.headless true
```

要点：

- 行情数据全部免费直连（mootdx TCP 7709 / 腾讯 / 东财 / 新浪），**国内 VPS 无障碍**；TDX 不通时自动回落新浪 HTTP（v0.2.19+）
- LLM key 只在"AI 分析"模式消耗，看板浏览零成本；`.env` 权限 600，绝不入库
- `run_all.bat` 的双服务（平台 8501 + trade-journal 8502）在 Linux 下改用：
  `streamlit run web/app.py & streamlit run trade-journal/app.py --server.port 8502`

## 路线 B：Streamlit Community Cloud（免费，但受限）

1. 用 GitHub 账号登录 [share.streamlit.io](https://share.streamlit.io)，New app → 选本仓库 → main 分支 → `web/app.py`
2. Secrets（管理界面粘贴，等价 .env）：`DEEPSEEK_API_KEY = "sk-..."`
3. 已知限制（务必在 Demo 页注明"演示环境"）：
   - **mootdx TCP 7709 大概率被云沙箱拦截** → 依赖新浪 HTTP 兜底（可用但分时数据可能缺）
   - trade-journal 是同级独立应用，Cloud 单应用部署下"交易日志"页显示手动引导（预期行为，不白屏）
   - 免费实例 1C/0.8G，冷启动 1~2 分钟（启动遮罩会盖住大半）
4. 建议在 Cloud 版顶部加一条 `st.info("公共演示实例，数据延时仅供界面预览")`

## 通用红线

- 任何 LLM key 只进 Secrets/服务器 .env，不进仓库
- 公网实例建议加 basic auth（Caddy 两行）或仅演示时段开机，避免被扫
- 报告页保留"仅供学习研究，不构成投资建议"声明（已有 footer）
