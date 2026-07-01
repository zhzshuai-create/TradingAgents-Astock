# TradingAgents-Astock 变更日志

> 基于 `backup-before-upstream-merge-20260702` → `HEAD`  
> 生成时间：2026-07-02

---

## 一、合并上游 v0.2.7 ~ v0.2.16

| 版本 | 日期 | 功能 |
|------|------|------|
| v0.2.7 | 05-19 | 替换3个失效数据源接口（百度PAE→东财push2） |
| v0.2.8 | 05-30 | 侧边栏收起后无法展开修复 |
| v0.2.9 | 05-30 | PDF跨平台字体 + Markdown导出 |
| v0.2.10 | 05-30 | Web UI支持第三方/代理API网关 |
| v0.2.11 | 05-30 | 东财接口统一限流防封 |
| v0.2.12 | 06-03 | PDF中文崩溃 + Docker字体 + API Key提示 |
| v0.2.13 | 06-03 | CLI路径穿越安全加固 |
| v0.2.14 | 06-18 | Docker命名卷权限修复 |
| v0.2.15 | 06-20 | mootdx 0.11.x防崩 + A股日K滞后修复 + Web中断续跑 |
| v0.2.16 | 06-28 | 批量脚本 complete_report.md + httpx FAQ |

---

## 二、恢复用户自定义改动

| 文件 | 改动 |
|------|------|
| `tradingagents/dataflows/alpha_vantage_common.py` | `requests.get` 加 `timeout=30` 防挂死 |
| `tradingagents/llm_clients/azure_client.py` | 支持自定义 `base_url` API网关 |
| `web/app.py` | K线周期选择器 + 数据看板 |
| `web/data_functions.py` | 数据函数（腾讯行情/同花顺热点/百度概念等） |
| `web/chart_utils.py` | Altair图表工具 |
| `web/runner.py` / `web/progress.py` | 卡死检测 + 简化进度 |

---

## 三、双主题系统

| 功能 | 说明 |
|------|------|
| 亮色模式（默认） | 白底 `#fff` + 黑字 `#1a1a1a` + 橙色强调 |
| 暖暗色模式 | 暖黑底 `#1c1816` + 暖白字 `#ede4dc` + 暖橙强调 |
| 切换方式 | 顶部导航栏 ☀️/🌙 radio 按钮 |
| 实现 | `config.toml` base=dark 基座 + CSS变量 + session_state 驱动 |
| 涉及文件 | `web/app.py`, `.streamlit/config.toml` |

---

## 四、补回上游Web功能（按顺序）

| # | 文件 | 上游功能 |
|---|------|---------|
| 1 | `web/history.py` | 历史记录扫描/加载/信号提取/断点续跑索引 |
| 2 | `web/progress.py` | 暂停/继续/停止 + 卡死检测 |
| 3 | `web/runner.py` | 流式执行 stream() + 阶段检测 + 中断支持 |
| 4 | `web/components/progress_panel.py` | CSS变量 + 暂停状态处理 |
| 5 | `web/components/report_viewer.py` | PDF导出 + 结构化报告 + _strip_think |
| 6 | `web/components/sidebar.py` | 历史列表/搜索/信号徽章/render_sidebar |

---

## 五、配置文件变更

| 文件 | 变更 |
|------|------|
| `C:\Users\zhzsh\Desktop\AStock-UI.bat` | Python路径从 `pythoncore-3.14-64` → `Python313` |

---

## 六、保护分支

| 分支名 | 用途 |
|--------|------|
| `backup-before-upstream-merge-20260702` | 合并前完整备份 |
| `theme-backup-20260702` | 主题改造前备份 |

---

## 七、完整提交序列

```
48d43de restore: web/components/sidebar.py — 上游历史记录列表+搜索+信号徽章+render_sidebar
06018de restore: web/components/report_viewer.py — 上游PDF导出+结构化报告+_strip_think
d44213d restore: web/components/progress_panel.py — 上游CSS变量+暂停状态处理
87be16a restore: web/runner.py — 上游流式执行(stream)+阶段检测+中断支持
a72ab13 restore: web/progress.py — 上游暂停/继续/停止控制 + 卡死检测
3334147 restore: web/history.py — 上游历史记录管理(扫描/加载/信号提取/断点续跑)
3d233b1 fix: 亮色模式搜索按钮(formSubmitButton)改回橙色白字
0fcb825 fix: 策略翻转—config.toml设为dark基座,亮色CSS全面覆盖Streamlit原生组件
fe0acb7 fix: 添加Streamlit原生组件暗色模式覆盖(标题/表格/展开/度量等); 修复#333遗漏
b6e125d fix: 改用Streamlit原生主题切换(radio)替代被拦截的JS, CSS根据session_state动态注入
8607566 fix: 主题切换按钮移到顶部导航栏(之前因sidebar折叠不可见)
db71381 feat: 双主题系统 — 亮色/暖暗色模式 + 一键切换
6ad8790 style: 全局灰色字体调整为深色字体
4962175 restore: 恢复用户自定义改动 (超时保护 + Web UI增强)
e90fb90 merge: 合并上游 v0.2.7~v0.2.16
b811976 feat: v0.2.16 批量样例脚本 complete_report.md
```

---

## 八、项目当前状态

| 项目 | 值 |
|------|-----|
| 版本 | 0.2.16 |
| Python | 3.13.3 (`C:\Users\zhzsh\AppData\Local\Programs\Python\Python313`) |
| 上游 | simonlin1212/TradingAgents-astock |
| Fork | zhzshuai-create/TradingAgents-Astock |
| 启动方式 | `C:\Users\zhzsh\Desktop\AStock-UI.bat` |
| 本地目录 | `C:\Users\zhzsh\TradingAgents-astock` |
| 磁盘备份 | `C:\Users\zhzsh\TradingAgents-astock-backup-20260702` |
