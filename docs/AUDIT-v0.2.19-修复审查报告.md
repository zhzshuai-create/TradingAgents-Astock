# AStock Pro 修复审查报告 · 对 v0.2.19 缺陷清单的逐条核实

> 项目路径：`C:\Users\zhzsh\TradingAgents-astock`
> 审查日期：2026-09-28
> 审查对象：审计基线 `78a3ddb` → 当前 HEAD `87662e3`，共 **12 个提交**，工作区干净
> 被审清单：`docs/AUDIT-v0.2.19-待修问题清单.md`（39 条：H1–H7 / M1–M16 / L1–L16）
> 核查方式：逐条读 diff + 回到当前树 Read/Grep 复核 + 实跑测试套件

本报告回答一个问题：**清单里的 39 条，哪些真的修好了，哪些只是看起来修好了。**

---

## 0. 结论摘要

| 状态 | 条数 | 说明 |
|---|---|---|
| **修复正确** | **22** | diff 与当前树双向核实，含新增测试钉子 |
| **部分修复** | **5** | H2、M12、M14、L6 —— 方向对但没做完，各自差在哪见第 3 节 |
| **修复无效** | **1** | **L12** —— 代码改了但新分支不可达，暗色主题下行为与修复前完全相同。见第 2 节 |
| **未动** | **11** | 见第 4 节 |

**回归检查**：`pytest tests/` **174 passed + 61 subtests**（基线 171 + 59，新增 3 个龙虎榜 fixture 用例）；`ruff check .` 全绿；无测试由绿转红。**没有引入回归。**

**总评**：这批修复的质量高于平均水平——几乎每处都带根因注释（如 `_common.py:402` 把工行实测数字写进了注释），H1/H3/H4 三条还配了能复现缺陷的离线 fixture 测试。**唯一的问题是 L12：修了一个不存在的开关。** 另外有两条修复引入了新的边界行为（第 5 节），都不严重但应当知道。

---

## 1. 逐条核实表

状态图例：✅ 修复正确 ｜ ◐ 部分修复 ｜ ❌ 修复无效 ｜ ⬜ 未动

### 高严重度

| 条 | 状态 | 核实证据 |
|---|---|---|
| H1 腾讯市值字段互换 | ✅ | `_common.py:399-405` 两位对调并附工行实测注释；`test_astock_parsing.py:137` 夹具改为 `2100.5 / 2800.7` 两个不同值，L175-178 增加方向断言 `float_mcap_yi <= mcap_yi`——**互换再发生会立刻红灯** |
| H2 Web 断点续跑失效 | ◐ | `sidebar.py:295` 文案由"可继续"改为"重新分析"并注释说明原因——**如实化了界面承诺**；但 `_build_config()` 仍未设 `checkpoint_enabled`，续跑功能本身未打通。这是清单里"修好前先改文案"建议的正确执行，功能欠账仍在 |
| H3 龙虎榜机构动向双重静默 | ✅ | `signals.py:497-499` 预置 `buy_data/sell_data = None` + `list_failed` 标志；第 3 节失败时显式输出"数据获取失败"两档文案；裸 `except: pass` 换成 `logger.warning`。`test_dragon_tiger_fixtures.py:74-81` 断言第 1 节抛异常时输出同时含"机构动向"与"数据获取失败" |
| H4 三处误用 safe_ticker_component | ✅ | `signals.py:494/634/717` 全部改 `_common._normalize_ticker`，`safe_ticker_component` 的 import 已从 signals.py 移除；`test_dragon_tiger_fixtures.py:46-58` 断言 `600379.SH` 进 filter 前被规范成 `SECURITY_CODE="600379"` 且不含 `.SH` |
| H5 30日涨幅按 50 根算 | ✅ | `data_dashboard.py:383` `closes = k30.tail(30)["close"]`，与下一行 `avg_vol` 口径一致 |
| H6 归属链失真 | ✅ | `CHANGES_FROM_UPSTREAM.md:3-8` 加时效声明（只覆盖 Week 1–7、`a_stock.py` 已拆包、v0.2.5 后见 CHANGELOG）；`NOTICE:13-15` 数据源改为 mootdx + 六家直连并注明 akshare 移除；`NOTICE:20-21` 指针拆成"早期见 CHANGES_FROM_UPSTREAM / v0.2.5 后见 CHANGELOG" |
| H7 桌面 bat 盲杀/硬编码 | ⬜ | `Desktop/AStock-UI.bat` 未改，且仍不在仓库内。清单里已注明"仅在准备分发时做"，可接受 |

### 中严重度

| 条 | 状态 | 核实证据 |
|---|---|---|
| M1 主题桥首帧丢失 | ✅ | `trade_journal.py:35-52`：`send()` 返回布尔，`last` 仅在投递成功时更新（失败下个 tick 重发）；新增握手——日志侧就绪后发 `astock-theme-request`，桥监听 `window.parent` 立即回送。外部仓库 `trade-journal/app.py:638` 确有对应的 request 发送，**两侧闭环** |
| M2 postMessage 无 origin 校验 | ⬜ | 桥与日志侧均无 `ev.origin` 检查。清单已评估实际影响有限（载荷仅主题字符串且有白名单），保持开放合理 |
| M3 journal_alive 宽探活 | ✅ | `journal_service.py:29-39` 改为两次探测、间隔 1.5s，两次都拿不到 200 才判死。**但引入了一个新边界，见第 5 节** |
| M4 launch.py 未固定端口 | ✅ | `launch.py:39` 显式 `--server.port 8501` |
| M5 自启失败遗留孤儿进程 | ✅ | `trade_journal.py:74-76` 失败路径先 `proc.terminate()` 再提示 |
| M6 OHLCV 缓存非原子写 | ✅ | `_common.py:734-736` 与 `:785-787` 两处均改为临时文件 + `os.replace` |
| M7 name-code map 无锁 | ✅ | `_common.py:99-110` 新增 `_NAME_MAP_LOCK`，check-then-set 整段持锁，逻辑拆到 `_build_name_code_map_unlocked` |
| M8 data_functions 静默 except | ✅ | 模块级 `logger` + 各函数 `logger.warning(..., exc_info=True)`，含 `index_spot` 等 UI 层自实现函数 |
| M9 北向快照无收盘守卫 | ✅ | `signals.py:226-229` `if datetime.now().strftime("%H%M") >= "1505"` 才落盘。**依赖本地时区，见第 5 节** |
| M10 东财空结果负缓存 | ✅ | `_common.py:541-544` `if rows:` 才 set；`:519` 缓存键补 `columns` |
| M11 市场前缀 5 处各写一份 | ⬜ | 仍在：`_common.py:600`、`fundamentals.py:81`、`fundamentals.py:217`、`news.py:75`（第三种变体）。8 开头北交所仍会被路由成 `sz8xxxxx` |
| M12 pip-audit 观察模式 | ◐ | `ci.yml:22-24` 仍 `continue-on-error: true`，但注释补了已知通告名单（soupsieve/torch/urllib3）与**复评期限 2026-12**。从"无限期观察"变成"有期限的观察"，方向对 |
| M13 Docker 无 Web 入口 | ⬜ | Dockerfile / docker-compose.yml 未改：仍 `ENTRYPOINT ["tradingagents"]`、无 EXPOSE/HEALTHCHECK/ports |
| M14 数据层测试缺口 | ◐ | 新增 `tests/test_dragon_tiger_fixtures.py`（3 用例，离线 mock）——**正是清单建议的起步点**，且顺手把 H1 的夹具鉴别力修了。但 16 个公开函数里其余 13 个仍无直接测试 |
| M15 质量门不阻断、Trader/PM 盲 | ⬜ | `quality_gate.py` 未改；`data_quality_summary` 消费方仍只有 bull/bear researcher |
| M16 作者归属冲突 | ✅ | `pyproject.toml:13` authors 改 zhzshuai-create；`NOTICE:2-3` 改为"Copyright zhzshuai-create / Based on … by Simon"，Apache 归属链完整且保留了上游与中间层声明 |

### 低严重度

| 条 | 状态 | 核实证据 |
|---|---|---|
| L1 chart_utils 死代码 | ✅ | 文件已删除（-321 行）；全仓除文档外零引用 |
| L2 TTLCache docstring | ✅ | `_common.py:290` 改为 "FIFO eviction（按插入时间逐出, 非 LRU）" |
| L3 app.py 过期字面值 | ✅ | `:538` banner 改 `v0.2.19`；`:661` 回退值改 `"unknown"` 并注释防漂移 |
| L4 CLAUDE.md 启动命令 | ✅ | `CLAUDE.md:66` 改 `streamlit run web/app.py`，并补一句"launch.py 是会二次 spawn 的启动器" |
| L5 DEV_LOG 待决策四项 | ⬜ | `DEV_LOG.md:588-591` 四个未勾选框原样保留 |
| L6 README 徽章 | ◐ | 两版 `alt="Version 0.2.19"` 已修、测试数徽章同步 174；**但 `README.en.md:10` 仍是静态 `shields.io/badge/CI-passing`，CI 挂掉时英文版恒绿** |
| L7 cached_call 死代码 | ⬜ | `_common.py:334` 仍在，docstring 仍引用不存在的 `_tencent_quote_raw` |
| L8 news 时间窗语义 | ⬜ | `news.py` 未改：解析失败的文章仍保留；`look_back_days` 仍只影响表头 |
| L9 scan_sectors akshare | ✅ | 裸字符串改真注释并指认 `.[scripts]`；`pyproject.toml:50` 新增 `scripts = ["akshare"]` extra |
| L10 generate_report 硬编码路径 | ✅ | `tools/generate_report.py:337` 改 `os.environ.get('ASTOCK_REPORT_OUT', 'A股科技板块投资分析报告.docx')` |
| L11 rangebreaks 只排周末 | ⬜ | `data_dashboard.py:120` 未改 |
| L12 蜡烛色硬编码亮色值 | ❌ | **修复无效**，见第 2 节 |
| L13 LLM 无默认超时 | ✅ | `openai_client.py:153-154` `llm_kwargs.setdefault("timeout", 120)` |
| L14 行业对比 docstring 不符 | ⬜ | `signals.py:715-717` docstring 与 "top/bottom" 文案未改 |
| L15 新浪兜底 volume 单位 | ⬜ | 未改，且仍未实测（清单第 8 节挂着） |
| L16 并发/续跑只做静态断言 | ⬜ | 无新增并行图端到端测试；`test_parallel_analysts.py` 仍只断言拓扑 |

---

## 2. 唯一一条修复无效：L12

**提交做了什么**（`data_dashboard.py:83-88`）：

```python
# L12: 跟随当前主题的 --up/--down（亮 #e03131/#2f9e44, 暗 #ff6b6b/#51cf66）
if st.session_state.get("theme") == "dark":
    up_c, dn_c = "#ff6b6b", "#51cf66"
else:
    up_c, dn_c = "#e03131", "#2f9e44"
```

**为什么无效**：`st.session_state["theme"]` 在全仓**只有一处写入**——`web/app.py:67-68` 的初始化，且恒为 `"light"`：

```python
if "theme" not in st.session_state:
    st.session_state["theme"] = "light"
```

真实主题载体是浏览器侧的 `localStorage['astock-theme']` 与 `<html>` 的 class（`app.py:76-78` 读取、`:354-356` 的 rope 开关切换）。那个开关**只写 localStorage 和 DOM class，不写 session_state，也不触发 rerun**。

所以 `st.session_state.get("theme") == "dark"` 在任何会话里都恒为 False，新加的分支**不可达**。暗色用户看到的蜡烛颜色与修复前逐像素相同。这不是"修得不够好"，是"修了一个不存在的开关"——与 H2 的病灶同型（界面/代码承诺了一个没有接线的状态）。

**两个可行修法**（按投入排序）：

1. **诚实的最小修法**：删掉条件分支，选一组在亮暗两主题下都可读的配色（现有的 `#e03131/#2f9e44` 在暗底上其实可辨，只是不如主题变量亮）。一行删除，消灭"看似跟随主题"的错觉。
2. **真接通**：rope 开关的 JS（`app.py:354-356`）在写 localStorage 的同时用 `history.replaceState` 把 `?theme=dark` 写进父页 URL；`app.py:67-68` 改为优先从 `st.query_params.get("theme")` 初始化 session_state。这样**下一次任意 rerun**（搜索、切 tab）就能拿到正确配色。代价是暗色切换后蜡烛颜色要等一次交互才跟上——但至少是真的在跟随。

不建议维持现状：一段永远走不到的分支比没有分支更糟，它会让下一个读者以为主题联动已经做了。

---

## 3. 四条部分修复，各自差在哪

| 条 | 已完成 | 欠账 | 建议 |
|---|---|---|---|
| **H2** | sidebar 文案改"重新分析"，界面不再承诺做不到的事 | `_build_config()` 仍未开 `checkpoint_enabled`；`history.py:181` 的 docstring 仍写 "can be resumed from their checkpoint"，与文案自相矛盾 | 要么开开关 + 补 Web→resume 集成测试，要么把 docstring 也改如实。**文案和 docstring 二选一地撒谎是不行的** |
| **M12** | 注释里写了已知通告名单与复评期限 2026-12 | 仍 `continue-on-error: true`，CI 不会因漏洞变红 | 期限到了必须转硬闸门；建议把期限写进 CHANGELOG 的 Unreleased，否则 12 月没人记得 |
| **M14** | 龙虎榜 3 个离线 fixture（含 H1 夹具鉴别力修复） | 其余 13 个公开函数仍无直接测试 | 下一批建议 `get_lockup_expiry` + `get_industry_comparison`（清单里点名的两个），再补 `_tencent_quote` 以外的 fundamentals 三表 |
| **L6** | 两版 alt 文本、测试数徽章同步 | `README.en.md:10` 静态 CI 徽章 | 换成与中文版同一个 `badge.svg`，一行 |

---

## 4. 未动的 11 条

按"是否会产生错误结论"排序，前四条建议下一批处理：

1. **M11** 市场前缀 4 处各写一份 —— 8 开头北交所标的仍会被拼成 `sz8xxxxx` 查空。**与 H4 同型：静默查空变成错误结论。** 修法是让四处都走 `_get_prefix`。
2. **M15** 质量门评 F 不阻断、Trader/PM 看不到评级 —— 最终给买卖建议的两个角色在不知道输入质量的情况下决策。
3. **L16** 并行编排无运行时测试 —— CHANGELOG 声称的"质量门恰好一次"至今只有结构论证。
4. **L8** `get_global_news` 的 `look_back_days` 是装饰性参数 —— 参数语义与实现不符，属于会误导调用方的接口谎言。
5. M2 origin 校验（影响有限，载荷变复杂前修）
6. M13 Docker 无 Web 入口（决定容器化定位后再做）
7. L5 DEV_LOG 待决策四项（纯文档，5 分钟）
8. L7 `cached_call` 死代码（删）
9. L11 节假日 rangebreaks（ cosmetic ）
10. L14 行业对比 docstring（ cosmetic ）
11. L15 新浪兜底 volume 单位（**先实测再决定**，清单第 8 节挂着核实办法）

另有两条清单外、按设计搁置的：P3（theme.py 1,130 行内联 CSS）、P6（数据源合规声明——NOTICE 已修数据源列表，但 README 仍无"非官方接口/失效风险"的说明）。

---

## 5. 修复引入的两条新边界行为

都不严重，但属于"改完之后世界变了"，应当记录：

**（1）M3 的双探活让"服务在跑但健康端点慢"变成"再拉一个进程"。**
旧逻辑：TCP 通但健康端点异常 → 判活 → 不拉起，交给 iframe 重连。
新逻辑（`journal_service.py:29-39`）：两次探测都拿不到 200 → 判死 → `render_journal_mode` 调 `start_journal()` 再 spawn 一个 streamlit。
若 8502 上真有一个**在跑但 /_stcore/health 卡住**的实例，新进程会抢不到端口。概率低（Streamlit 的 health 端点极轻），且比旧的"假 200 跳过启动得白屏"更可控——**接受这个权衡是对的**，但值得在 `journal_service.py` 的注释里写明，否则下次有人看到孤儿进程会以为是 M5 没修干净。

**（2）M9 的收盘守卫依赖本地时区。**
`datetime.now().strftime("%H%M") >= "1505"` 用的是机器本地时间。在 CST 机器上正确；在 UTC 机器上，北京时间 15:05 = UTC 07:05，守卫会在错误的时间窗放行/拦截。这与清单里未收录的一条潜在问题同源（数据层多处用本地 `datetime.now()` 判断交易日）。**当前部署环境是 CST，所以不是缺陷；一旦容器化（M13）或换机部署就会变成真 bug。** 建议与 M13 一起处理：容器里显式设 `TZ=Asia/Shanghai`，或把守卫改成基于数据时间戳而非墙钟。

---

## 6. 回归与规模核对

| 项 | 审计基线 | 当前 | 变化 |
|---|---|---|---|
| `pytest tests/` | 171 passed + 59 subtests | **174 passed + 61 subtests** | +3 用例（龙虎榜 fixture），无转红 |
| `ruff check .` | 全绿 | 全绿 | — |
| `web/chart_utils.py` | 321 行死代码 | 已删除 | -321 行 |
| README 徽章测试数 | 171 | 174 | 已同步 |
| 工作区 | 干净 | 干净 | — |

---

## 附：审查方法

1. `git log 78a3ddb..HEAD` 取 12 个提交，`git diff --stat` 定改动面（26 文件）。
2. 逐文件读 diff；对每条声称的修复，回到当前树用 Read/Grep 复核行号与上下文，**不信提交信息**。
3. 对 L12 这类"改了但可能没生效"的修复，额外追查其依赖的状态载体（`session_state["theme"]` 的写入点）——这是本轮唯一一条被判定无效的修复，靠的是追写入点而不是看 diff。
4. 外部仓库 `trade-journal/app.py` 的握手发送点（:638）单独核实，确认 M1 是双侧闭环而非单侧。
5. 实跑 `pytest tests/` 与 `ruff check .` 确认无回归。
