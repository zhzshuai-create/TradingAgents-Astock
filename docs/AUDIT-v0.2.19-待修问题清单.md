# AStock Pro 待修问题清单 · v0.2.19

> 项目路径：`C:\Users\zhzsh\TradingAgents-astock`
> 审计日期：2026-09-28
> 审计对象：v0.2.19 当前树（commit `78a3ddb`，工作区干净）
> 核查方式：实跑测试套件 + ruff + 逐条 Read/Grep 核实到行号 + 一次真实网络请求实测
> 前序清单：`AStock-待修问题清单.md`（2026-09-27，基于 v0.2.18，P0–P7）

本清单**不沿用**前序清单的结论。所有条目都在当前树上重新核实过；前序清单的状态在第 1 节单独交代。凡未能核实的，明确标注"未核实"，不写成结论。

---

## 0. 本轮基线（实测，非引用）

| 项 | 实测值 |
|---|---|
| `pytest tests/` | **171 passed + 59 subtests passed**，22.95s，全绿 |
| `ruff check .` | **All checks passed**，0 告警 |
| Python 规模 | **21,863 行 / 134 个文件** |
| git 提交数 | **214** |
| tests/ 断言数 | **339** |
| `a_stock/` 数据层 | **2,519 行**（_common 770 / signals 746 / fundamentals 491 / news 275 / quote 176 / __init__ 61） |
| `web/` | **5,965 行**（theme 1130 / app 722 / pdf_export 652 / data_dashboard 595 / data_functions 423 …） |

测试与 lint 是全绿的。**下面所有缺陷都不会让 CI 变红**——这正是它们值得单独立一份清单的原因。

---

## 1. 前序清单 P0–P7 状态核实

| 编号 | 前序结论 | 当前树状态 | 证据 |
|---|---|---|---|
| P0 | CLAUDE.md 文档漂移（`a_stock.py` 已不存在等 5 处） | **已修** | CLAUDE.md 现写 `a_stock/` 包；版本号不再硬写，改指 `pyproject.toml`；仓库 URL 为 zhzshuai-create |
| P1 | `test_static_undefined_names.py` 两处 `subprocess.run` 缺 encoding | **已修** | 已补 `encoding="utf-8"` + `errors="replace"`；本轮实跑无 UnicodeDecodeError |
| P2 | `y_finance.py` / `yfinance_news.py` 9 处静默 except | **已修** | 已补 `logger.warning` |
| P3 | `theme.py` 约千行内联 CSS | **未做，且已增长** | 现 **1,130 行**（前序记录 1,087） |
| P4 | 桌面 `AStock-UI.bat` 硬编码路径 + 盲杀 8501 | **未做** | 见本轮 **H7**，两处硬伤原样存在 |
| P5 | `a_stock/` 数据层解析逻辑无直接测试 | **未做，仍是最大测试缺口** | 见本轮 **M14** |
| P6 | 数据源合规说明缺失 | **未做** | 仓库内仍无 `robots`/`合规`/`授权`/`条款` 相关说明 |
| P7 | 求职一页贡献清单 | **未做** | `CHANGES_FROM_UPSTREAM.md` 仍是长文档，且已整体过期（见 **H6**） |

前序清单判定为"低优先"的一条，本轮**被推翻并升级**：`web/data_functions.py` 的静默 except（见 **M8**）。

---

## 2. 高严重度

### H1 · 腾讯行情「总市值 / 流通市值」字段互换（已实测确证）

**这是本轮唯一一条用真实网络请求证实的数据正确性缺陷，也是危害最大的一条。**

`tradingagents/dataflows/a_stock/_common.py:389-390`

```python
"mcap_yi": float(vals[44]) if vals[44] else 0,
"float_mcap_yi": float(vals[45]) if vals[45] else 0,
```

**实测证据**（2026-09-28 直连 `qt.gtimg.cn`，工商银行 sh601398，价 8.13）：

| 字段位 | 返回值 | 反推股本 | 实际含义 |
|---|---|---|---|
| `v[44]` | 21,919.47 亿 | 2,696 亿股 | **流通市值**（工行 A 股流通股本） |
| `v[45]` | 28,975.83 亿 | 3,564 亿股 | **总市值**（工行总股本 3,564 亿股 × 8.13 = 28,976 亿，完全吻合） |

同向验证：宁德时代 sz300750 `v[44]=12,504.91 < v[45]=13,580.98`（H 股上市后总股本 > A 股流通）。两只票方向一致，**代码把两者标反了**。

**污染面（两条独立链路）**：

1. `fundamentals.py:42-43` — 直接写进给 LLM 的提示词：
   ```python
   f"Market Cap (100M CNY): {q['mcap_yi']}",
   f"Float Market Cap (100M CNY): {q['float_mcap_yi']}",
   ```
   基本面分析师拿到的是**颠倒的市值结构**，据此判断"盘子大小 / 拉升难度"会系统性错。
2. `web/components/data_dashboard.py:271-272` — 看板"总市值"卡片显示流通值，卡片副行"流通"显示总值。工行会显示成「总市值 21919亿 / 流通 28976亿」，流通大于总市值，肉眼即可发现矛盾。

**为什么测试抓不到**：`tests/test_astock_parsing.py:137` 的夹具把两位填成同一个值 —— `(44, "2100.5"), (45, "2100.5")`，L175-176 再分别断言两者等于 2100.5。互换后测试依然全绿。**夹具本身取消了这条断言的鉴别力。**

**修法**：`vals[44]` → `float_mcap_yi`、`vals[45]` → `mcap_yi`；同时把夹具两个值改成不同（如 2100.5 / 2800.7），并加一条 `assert q["float_mcap_yi"] < q["mcap_yi"]` 的方向断言，防止再被换回去。

---

### H2 · Web 端「断点续跑」实际从未生效，点击即全额重跑

**证据链（四段，全部核实）**：

1. `web/app.py:432` `def _build_config()` —— 整个函数**没有设置** `checkpoint_enabled`（全仓 `grep` 该键，web/ 下零命中）。
2. `tradingagents/default_config.py:34` —— `"checkpoint_enabled": False`，默认关闭。
3. `tradingagents/graph/trading_graph.py:356` —— `if checkpoint_enabled:` 才编译 checkpointer；`:409` 才写 checkpoint。**开关为假 → 从不落检查点。**
4. 唯一会打开这个开关的地方是 `cli/main.py:361`（命令行 `--checkpoint`）。Web 路径永远走不到。

**但 UI 完整呈现了"可续跑"的语义**：

- `web/components/sidebar.py:290-308` —— 未完成任务按钮，状态文案回退值是 **"可继续"**，还会拼上 `f" · step {step}"`。
- `web/history.py:181` —— docstring 明写 `"""Return unfinished tasks that can be resumed from their checkpoint."""`。

因为检查点从未写入，`_checkpoint_step()` 恒返回 `None`，`step` 标签恒不显示；点"可继续"只是 `st.session_state["start_analysis"] = {...}`，即**从零重跑一次完整的付费多智能体流水线**。

**为什么严重**：这不是"少了个功能"，是**界面承诺了一个它做不到的行为**，而且代价是真实的 LLM 费用。7 个分析师 + 多空辩论 + 三方风控 + 交易员 + PM 全套重跑。

**修法**：`_build_config()` 里补 `config["checkpoint_enabled"] = True`（或加侧边栏开关），并补一条 Web→resume 的集成测试断言 `checkpoint_step()` 非 None。**在修好之前，建议先把 sidebar 的"可继续"文案改成"重新分析"**，避免自欺。

---

### H3 · 龙虎榜「机构动向」跨 try 块取变量 + `except: pass`，双重静默

`tradingagents/dataflows/a_stock/signals.py`

- 第 2 节（席位明细）在 `try` 内定义 `buy_data`（L526）与 `sell_data`（L546）；该节失败只记 `logger.debug`（L564-565）。
- 第 3 节（机构动向）在**另一个 try** 里直接使用这两个变量：
  ```python
  for detail, side in [(buy_data, "buy"), (sell_data, "sell")]:
  ```
- 第 3 节的兜底是（L585-586）：
  ```python
  except Exception:
      pass
  ```

**失效路径**：第 1 节（龙虎榜列表）失败 → `data` 为空 → 第 2 节 `if data:` 不成立，`buy_data`/`sell_data` **从未被赋值** → 第 3 节抛 `NameError` → 被 `except: pass` 无声吞掉 → 报告里"机构动向"整节消失，**日志里连一行 debug 都没有**。

这正是 CLAUDE.md 记录过的百度 PAE 事故同型：宽泛捕获让"某个分析维度实际是空的"看起来像"这只票没有机构参与"。

**修法**：三个变量在函数开头初始化为 `None`；第 3 节 `except Exception as e: logger.warning(...)`；并在输出里显式写一行"机构动向：数据获取失败"而不是整节消失。

---

### H4 · 三个信号函数把「路径校验函数」当「代码规范化函数」用，带后缀代码静默查空

`signals.py` 里有两种写法并存：

| 用法 | 出现位置 |
|---|---|
| `code = _common._normalize_ticker(ticker)` | fundamentals.py ×6、news.py:116、quote.py:24/129、signals.py:289、signals.py:363 |
| `code = safe_ticker_component(ticker)` | **signals.py:482、611、694** |

`safe_ticker_component` 是**安全边界**（防路径穿越），不是规范化器：形如 `600379.SH` / `SH600379` 的输入匹配其白名单正则后**原样返回**，不会被剥成 6 位 `600379`。

后果：这三个函数（龙虎榜 / 解禁 / 行业对比）拿到带后缀代码后，直接拼进东财 datacenter 的 filter —— `SECURITY_CODE="600379.SH"` —— 查不到记录，函数正常返回，输出"近 30 日未上龙虎榜"。**是"没有数据"和"查询条件写错了"两种语义被压成同一句话。**

CLAUDE.md 已记录 deepseek-v4-flash 等模型在 tool call 时会返回非标准代码，而 `safe_ticker_component` 的中文兜底只处理中文，不处理后缀。

**修法**：三处改为 `_common._normalize_ticker(ticker)`（该函数内部最后一步仍会调 `safe_ticker_component`，安全性不丢）。

---

### H5 · 看板「30日涨幅」实际按约 50 个交易日计算

`web/components/data_dashboard.py:377-381`

```python
k30 = klines.tail(50).copy()  # 50 根算 MA，只显示最近 30 根
_show_candles(k30, display_tail=30, height=480)
closes = k30["close"]
chg = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
avg_vol = klines.tail(30)["vol"].mean()
```

取 50 根是为了让 MA20 在显示窗口左端不缺头——这个设计本身对（CHANGELOG 也这么写）。但 `chg` 直接用了这 50 根的首尾，**没有先 `tail(30)`**。紧邻的下一行 `avg_vol` 反而正确地用了 `klines.tail(30)`，说明这是漏写而非有意。

标签写的是"30日涨幅"，数值是约 50 个交易日涨幅。趋势行情下偏差可观。

**修法**：`closes = k30.tail(30)["close"]`。

---

### H6 · Apache 2.0 归属链失真：`CHANGES_FROM_UPSTREAM.md` 整体过期，`NOTICE` 仍写已移除的 akshare

前序清单 P0 修的是 CLAUDE.md 的漂移。**同型问题在合规文件里更严重，且没被修。**

**（1）`CHANGES_FROM_UPSTREAM.md` 自称记录"所有改动"，实际止于 2026-05-12**

- 文档最后三个章节是 Week 5.5 / Week 6 / Week 7，日期均为 **2026-05-12**。v0.2.5 → v0.2.19 之间的改动（akshare 移除、东财限流器、7 分析师并行、boot splash、蜡烛图、日志桥……）**一条都没有**。
- 仍在引用已不存在的文件 `tradingagents/dataflows/a_stock.py`：**L13、L21、L118、L170、L212、L255** 六处。该文件早已拆成 `a_stock/` 包——与前序 P0 里 CLAUDE.md 犯的是同一个错。

**（2）`NOTICE` 把这份过期文档当作权威**

- `NOTICE:20`：`See CHANGES_FROM_UPSTREAM.md for the full list of modifications.` —— 指向的是一份缺了 4 个多月改动的文档。
- `NOTICE:13`：`A-stock (China mainland) data layer using mootdx, Tencent Finance, and akshare` —— **akshare 已于 v0.2.5 完全移除**（CLAUDE.md、CHANGELOG 均已记录），现行是东财/新浪/同花顺/财联社/百度直连 HTTP。

**（3）作者归属与仓库身份冲突**（另见 M16）
- `NOTICE:2`：`Copyright 2026 Simon (github.com/simonlin1212)`
- `pyproject.toml:13`：authors = `simonlin1212`
- 而 Homepage/Repository、README 徽章与 clone URL 全是 `zhzshuai-create`

**为什么算高**：这是 fork 的合规门面。别人（或面试官）顺着 NOTICE 去核对改动边界，会读到一份指向不存在文件、漏掉近期全部工作、还写着一个已删依赖的文档。前序清单 P7 把"划清边界"列为求职加分项——**而当前这份边界文件本身是错的**。

**修法**：给 `CHANGES_FROM_UPSTREAM.md` 加显式过期声明（"本文档记录 Week 1–7，截至 2026-05-12；v0.2.5 之后见 CHANGELOG.md"），或补齐后续章节；六处 `a_stock.py` 改为 `a_stock/`；NOTICE:13 数据源描述改为 mootdx + 直连 HTTP；NOTICE:20 的指向同步调整。

---

### H7 · 桌面启动器：盲杀 8501 端口占用者 + 硬编码本机路径 + 未纳入版本控制

文件 `C:\Users\zhzsh\Desktop\AStock-UI.bat`（**不在仓库内**，`git ls-files` 里 `.bat` 只有 `run_all.bat`）。前序 P4 两处硬伤原样存在，本轮补充第三点。

**（1）不校验进程身份就 `/F` 强杀，且吞掉错误**（L20-23）

```bat
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501.*LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
```

- 不检查占用 8501 的是不是自己的 python/Streamlit，直接强制终止；`>nul 2>&1` 连失败也吞了。
- 补充：`findstr ":8501"` 是**子串**匹配，`:18501`、`:85010` 之类端口同样命中，误杀面比前序清单描述的更宽。

**（2）硬编码绝对路径**（L5-6）

```bat
set "PYTHON=C:\Users\zhzsh\AppData\Local\Programs\Python\Python313\python.exe"
set "PROJECT=C:\Users\zhzsh\TradingAgents-astock"
```

L8-17 有存在性检查会报错退出，算兜底，但换机即废。

**（3）真实生产入口游离在版本控制外**

这是本轮新增的判定：双击桌面图标是**实际的启动方式**，但它不在仓库里、不可回溯、不可分发。仓库内的 `run_all.bat` 与它行为不一致（前者走 `launch.py --with-journal`，后者直接 `streamlit run web/app.py --server.port 8501`，不起日志服务）。

**修法**：去硬编码（`%~dp0` 推导 + `where python`）；杀端口前先 `tasklist /FI "PID eq %%a"` 确认映像名，匹配串收紧为 `:8501 .*LISTENING`；把清理过的脚本收进仓库 `scripts/`，桌面只留快捷方式。

---

## 3. 中严重度

### M1 · 主题桥首帧消息必然丢失，暗色用户首次进日志页看到白底

`web/components/trade_journal.py:33-37`

```javascript
var last = null;
setInterval(function() {
  var t = currentTheme();
  if (t !== last) { last = t; send(t); }
}, 600);
```

`last` 在**发送动作之后无条件置位**，不关心投递是否成功。而 `send()`（L29-31）靠 `querySelector('iframe[src*=":8502"]')` 找目标；接收端（`trade-journal/app.py` 的 `_inject_theme_listener`）是**纯被动监听**，不会主动来问。

时序：桥 iframe 第一个 600ms tick 就会发出主题消息，但此时 8502 的 Streamlit 冷启动还需数秒、监听器尚未注册 —— **消息丢失，且因为 `last` 已置位，主题不再变化就永不重发**。

CHANGELOG 声称"日志刷新后自动同步"，实际首进暗色用户拿到的是白底日志，直到手动切一次主题。

**修法**：send 前确认目标 iframe 存在且已就绪，否则不更新 `last`；或改为握手（日志侧就绪后主动 postMessage 请求一次当前主题）。

### M2 · 跨源 postMessage 双向都不校验 origin

- 发送端 `trade_journal.py:31`：`postMessage({...}, '*')` —— 目标源用通配。
- 接收端 `trade-journal/app.py`：`addEventListener('message', function(ev){ var d = ev.data || {}; if (d.type === 'astock-theme' && ...) })` —— **没有 `ev.origin` 检查**。

**实际影响有限，需如实说明**：载荷只有主题字符串，且接收端对 `d.theme` 做了 `'dark'/'light'` 白名单校验，最坏情况是任意页面能切换日志区的暗色 CSS 类。**不是可注入 XSS 的口子**，但作为一个跨源桥，两侧都不校验 origin 是错误的模式，将来载荷变复杂就会变成真漏洞。

**修法**：接收端加 `if (ev.origin !== 'http://localhost:8501') return;`；发送端把 `'*'` 换成 `http://localhost:8502`。

### M3 · `journal_alive()` 单次宽探活，而本机已实证过假 200

`web/journal_service.py:22-34`

```python
try:
    with urllib.request.urlopen(f"{JOURNAL_URL}/_stcore/health", timeout=1.0) as r:
        return r.status == 200
except Exception:
    # TCP 通了但健康端点没回 200, 仍认为进程在 (可能刚启动), 交给 iframe 重连
    return True
```

`DEV_LOG.md:553` 自己记录过本机 loopback 怪象：**无监听端口返回过假 200（dt≈0.01s，两轮复现）**，因此"就绪判定必须双探（间隔 ≥150ms 两次 200）"。`wait_ready()`（L49-64）确实照做了，但**决定"要不要拉起服务"的 `journal_alive()` 仍是单探针 + 宽判**。假阳性会让页面跳过启动直接嵌 iframe，得到白屏，只靠 iframe 自重连兜底。

**修法**：`journal_alive` 要求 TCP 与健康端点**两个条件都满足**才判活，或复用 `wait_ready` 的双探逻辑。

### M4 · `launch.py` 未固定平台端口，可能与日志服务抢 8502

`web/launch.py:38`

```python
subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)])
```

没有 `--server.port`。而日志服务固定 8502（`journal_service.py:18`）。8501 被占时 Streamlit 会协商到下一个可用端口，即 **8502**，与同一命令里刚拉起的日志服务直接撞车。对比：桌面 bat 反而显式传了 `--server.port 8501`。

**修法**：显式传 `--server.port 8501`，并决定 headless 策略。

### M5 · 日志自启失败后遗留孤儿子进程

`web/components/trade_journal.py:52-60`：`proc = journal_service.start_journal()`，若 `wait_ready()` 超时，只 `st.warning(...)` 然后 `return`，**没有 `proc.terminate()`**。半死的 Streamlit 进程可能占住 8502，让下次探活/启动的状态更难判断（叠加 M3）。

`launch.py:39-41` 的 finally 里有 terminate，正常退出路径是干净的；缺的只是这条失败分支。

**修法**：`wait_ready()` 失败时先 `proc.terminate()` 再提示。

### M6 · OHLCV 磁盘缓存非原子写 + 无锁，并行分析师会直接撞上

`_common.py:765` 写、`_common.py:710` 读，同一个文件 `{code}-astock-daily.csv`（L705），中间没有临时文件 + `os.replace`，也没有 per-key 锁。

v0.2.18 的并行分析师（`TA_PARALLEL_ANALYSTS=1`）让 market / hot_money / lockup 三个 ToolNode 在**同一 super-step 内并发**执行，都挂着 `get_stock_data` —— 同一标的的写者与读者可以交错，读到半截 CSV。

**修法**：写临时文件后 `os.replace()`（Windows 上也是原子的），或按 code 加文件锁。

### M7 · `_build_name_code_map` 全局缓存 check-then-set 无锁

`_common.py:101-103`

```python
global _name_to_code, _code_to_name
if _name_to_code is not None:
    return _name_to_code, _code_to_name
```

无锁的"检查后设置"。触发链是 `utils.py:31-34` 的中文名兜底 → `resolve_ticker` → 本函数，**7 个分析师线程可以同一刻进来**。后果是并发重复全市场 TCP 拉取（慢 + 撞 mootdx），以及 L148 并发 `open(disk_cache, "w")` 写同一 JSON 可能写坏（目前只靠 L118 的 except 自愈）。

同文件里 `_TTLCache`、`_EMRateLimiter`、`_LockedTdxClient` 都正确加了锁，唯独这处进程级缓存没有。

**修法**：模块级 `threading.Lock` 包住"检查—构建—落盘—赋值"整段。

### M8 · `web/data_functions.py`：15 处 except、0 处日志（**推翻前序清单的"低优先"判定**）

实测计数：该文件 `except Exception` **15 处**，`logger`/`logging` 出现 **0 次**。

前序清单 P2 把这里判为低优先，理由是"均为 `_core` 的薄包装，下层 `quote.py` 自带 logger.warning，信息未丢"。**这个理由只对一部分函数成立。** 反例已核实：

`web/data_functions.py:405-421` 的 `index_spot` 是 UI 层**自己实现**的腾讯指数解析（自己 split `~`、自己取 `vals[3]/vals[31]/vals[32]`），不经核心层，内层 `except Exception: continue`、外层 `except Exception: pass`，**任何一层都不会留下记录**。同类还有 `hsgt_realtime`、`industry_comparison`、`cls_telegraph`、`eastmoney_stock_news`、`baidu_concept_blocks`、`ths_hot_reason`。

顶栏指数条整块空白而无任何日志，与 H3 是同一个失效模式。

**修法**：加模块级 logger，这些自实现函数补 `logger.warning(..., exc_info=True)`。薄包装那部分可维持现状。

### M9 · 北向资金「日收盘」缓存无收盘时点守卫，盘中调用会污染历史

`signals.py:225-227`

```python
if got_realtime:
    today_str = datetime.now().strftime("%Y-%m-%d")
    _save_northbound_snapshot(today_str, hgt_close, sgt_close)
```

只要实时接口返回成功就落盘，**没有"已过 15:00 收盘"的判断**。盘中 10:30 调用一次，就会把当时的分钟级累计值当作当日 close 写进 `northbound_daily.csv`。

这件事的权重来自一个事实：上游北向历史 API 已于 2024-08 停更（`signals.py:165-166` 注释自证），**这份自建 CSV 是历史数据的唯一来源**。脏一次就永久留着，且后续趋势对比（today vs N-day avg）会拿它当基准。

**修法**：仅当本地时间 ≥15:05（或数据时刻为 15:00）才落盘。

### M10 · 东财空结果也进缓存，风控瞬时返空被固化 5 分钟

`_common.py:518-527`

```python
r = _em_get(_DATACENTER_URL, params=params, timeout=15)
d = r.json()
if d.get("result") and d["result"].get("data"):
    rows = d["result"]["data"]
else:
    rows = []
_data_cache.set(cache_key, rows)
```

`rows = []` 同样被 `set` 进缓存。东财风控（`_common.py:417-418` 注释记录了阈值：每秒 >5 次 / 单 IP 并发 ≥10 / 1 分钟 ≥200 次 → 临时封 IP）瞬时返空时，这个空结果会被固化整个 TTL，**叠加 H3/H4 就变成报告里一句理直气壮的"未上榜"**。

另：`_common.py:504` 的缓存键未包含 `columns` 参数（当前所有调用方都用默认值，属潜伏）。

**修法**：空结果不缓存或单独给一个很短的 TTL；缓存键补上 `columns`。

### M11 · 市场前缀规则被复制了 5 份，北交所（8 开头）全部错路由

`_common.py:38-42` 的 `_get_prefix` 是正确的那份（6/9→sh，8→bj）。但另外几处各写各的：

| 位置 | 写法 | 8xxxxx 的结果 |
|---|---|---|
| `_common.py:582` | `"sh" if code.startswith("6") else "sz"` | `sz8xxxxx` ✗ |
| `fundamentals.py:217` | 同上 | `sz8xxxxx` ✗ |
| `news.py:75` | 第三种变体（6,9→sh） | ✗ |
| `fundamentals.py:81`、`signals.py:364` | secid `1 if startswith("6") else 0` | 900xxx 沪 B 也被归到深市 ✗ |

**修法**：统一走 `_get_prefix`，secid 与新浪前缀由它派生。

### M12 · pip-audit 处于永久"观察模式"，CI 不会因依赖漏洞变红

`.github/workflows/ci.yml:22-24`

```yaml
audit:
  # 依赖漏洞扫描：先观察模式（不阻塞 CI），评估完传递依赖升级空间后转硬闸门
  runs-on: ubuntu-latest
  continue-on-error: true
```

`continue-on-error: true` 意味着**任何结果都显示绿色**。注释写了"评估完…转硬闸门"但没有期限，`78a3ddb` 的提交信息也称其为"观察模式"。这是一个能静默通过的步骤，属于前序清单 P7 里"面试官会问的生产化短板"。

**修法**：设定转正期限；或至少对 Critical/High 级别 `--disallow` 并去掉 `continue-on-error`。

### M13 · Docker 镜像只能跑 CLI，Web UI 完全不可达

- `Dockerfile:43`：`ENTRYPOINT ["tradingagents"]` —— 纯 CLI 入口；全文**无 `EXPOSE`、无 `HEALTHCHECK`**。
- `docker-compose.yml`：**无 `ports:` 映射**（两处 `env_file`，L4 / L20）。

即 8501/8502 在容器外都不可达。而"Web 平台"是这个 fork 相对上游的主要卖点之一，`docs/DEPLOY.md` 也写了 VPS 部署路线。**容器化覆盖的场景与产品主诉求是脱节的。**

（另：mootdx 需大陆 IP + TCP 7709，境外容器环境下数据层是否可用 —— **未核实**，需在容器内实测。）

Dockerfile 其余部分是干净的：非 root 运行（L27-28 `useradd` + `USER appuser`）、多阶段构建、CJK 字体、预建数据目录权限修复（L37-39，对应 issue #46）。

**修法**：为 web 场景加 `EXPOSE 8501` + compose 端口映射 + `HEALTHCHECK`（探 `/_stcore/health`）。

### M14 · 数据层 16 个公开函数，只有 1 个有直接测试（前序 P5，仍开放）

`a_stock/` 共 **2,519 行**（比前序记录的 2,114 行又长了 405 行）。逐个核实：

| 文件 | 公开函数（行号） | 直接测试 |
|---|---|---|
| `quote.py` | `get_stock_data`(18) | **部分** — `test_astock_sina_supplement.py` 只覆盖新浪补数这一条路径 |
| `quote.py` | `get_indicators`(118) | ✗ |
| `fundamentals.py` | `get_fundamentals`(20)、`get_balance_sheet`(256)、`get_cashflow`(288)、`get_income_statement`(320)、`get_insider_transactions`(352)、`get_profit_forecast`(402) | ✗ 全部无 |
| `news.py` | `get_news`(110)、`get_global_news`(180) | ✗ |
| `signals.py` | `get_hot_stocks`(19)、`get_northbound_flow`(156)、`get_concept_blocks`(279)、`get_fund_flow`(348)、`get_dragon_tiger_board`(466)、`get_lockup_expiry`(595)、`get_industry_comparison`(678) | ✗ 全部无 |
| `_common.py` | `_normalize_ticker`/`_get_prefix`/`resolve_ticker`/`_normalize_ohlcv_dates`/`_needs_sina_supplement`/`_merge_ohlcv`/`_tencent_quote` | ✓ `test_astock_parsing.py` |

**16 个业务函数里 15 个无直接测试**，且 `_common` 的测试恰恰因为夹具取值问题放过了 H1。

这块最值得补的理由没变：全是确定性的字符串 / DataFrame / JSON 解析，不含 LLM 调用，完全可测；接口改版是**已发生过的真实故障**（百度 PAE、北向历史 API 停更）。有了 fixture 测试，改版当场红灯，而不是等报告里出现空数据。

**建议起步**：先给 `get_dragon_tiger_board`（覆盖 H3）、`get_industry_comparison`（覆盖 H4）加 fixture，顺手把 `_tencent_quote` 的夹具改成两个不同值（覆盖 H1）。三个高严重度缺陷都能被这批测试钉住。

### M15 · 质量门评 F 不阻断，且评级结果 Trader / PM 看不到

`tradingagents/agents/quality_gate.py:144-165`：统计 `fail_count`（F/D 档数量），`fail_count < 4` 时跳过 LLM 复审，最后无论评级如何都只 `return {"data_quality_summary": summary}` —— **纯写状态，不做门控**。

消费方全仓核实：只有 `bull_researcher.py:20/29` 与 `bear_researcher.py:22/31` 把它拼进 prompt；`report_viewer.py:123` 展示它。**Trader 与 Portfolio Manager 拿不到质量评级** —— 也就是说，最终给出买卖建议的两个角色，是在不知道"输入数据有 4 个维度是 F 档"的情况下做决策的。

`web/runner.py:44-47`：分析师 content 为空时不 `mark_stage_done`，UI 阶段条永久停在 pending（配合 `market_analyst.py:104-112` 空 content 仍自报 `analysts_completed`）。

**修法**：把 `data_quality_summary` 注入 Trader/PM 的 prompt；F 级维度在最终报告顶部显著标注；考虑对关键维度全 F 的情况触发重试或拒绝出报告。

### M16 · `pyproject.toml` 把他人署为作者，与仓库归属冲突

- `pyproject.toml:13`：`{name = "simonlin1212", email = "simonlin1212@users.noreply.github.com"}`
- `NOTICE:2`：`Copyright 2026 Simon (github.com/simonlin1212)`
- 而 `pyproject.toml:42-43` 的 Homepage/Repository、README 徽章与 clone URL 全是 **zhzshuai-create**
- `pyproject.toml:46` 另有一个 `AstockFork` 指向 simonlin1212

`CHANGE_LOG_20260702.md:109-110` 记录了真实关系：simonlin1212 是上游 fork，本仓库是在其基础上的再 fork。**归属链本身没问题，问题是发布元数据把中间那层写成了作者**，而真正的致谢位置（`README.md:351`）反而才是对的表达。

对求职作品集来说这是自伤：`pip show` 出来的 author 不是仓库所有者。

**修法**：`pyproject.toml` authors 改为本仓库所有者；simonlin1212 保留在 `AstockFork` URL 与 README 致谢里；NOTICE 的版权行相应调整（Apache 2.0 要求保留原始版权声明，因此 TauricResearch 与 simonlin1212 的既有声明应保留，追加本仓库的修改声明即可）。

---

## 4. 低严重度

### L1 · `web/chart_utils.py`：321 行死代码，依赖未声明的 matplotlib，且涨跌配色与 web 端相反

三重问题叠在同一个文件上：

1. **死代码** —— 全仓 `grep -rn "chart_utils"` 除自身外**零命中**。PDF 出图实际由 `web/pdf_export.py`（652 行）自己做。
2. **依赖未声明** —— `chart_utils.py:8` `import matplotlib`，但 `pyproject.toml` 的 dependencies 里**没有 matplotlib**。任何代码一旦真的 import 它，fresh install 环境直接 ImportError。
3. **配色是美股惯例** —— `chart_utils.py:140-141`、`181-182`：
   ```python
   is_green = row["Close"] >= row["Open"]
   body_color = GREEN if is_green else RED
   ```
   涨绿跌红。而 web 端 `data_dashboard.py:83` 与 `theme.py:45-46` 都是涨红跌绿。**两套 K 线实现的配色约定已经分叉。**

因为是死代码，第 3 点目前不会实际显示出来 —— 所以定为低。但它的存在是陷阱：将来谁想"复用现成的 PDF 画图工具"，会同时踩到 ImportError 和配色反向。

另 `CHANGE_LOG_20260702.md:33` 称它是"Altair 图表工具"，与文件自称的 matplotlib 又不一致。

**修法**：删掉；若确定要保留 PDF 出图能力，则声明 matplotlib 依赖、修正配色、并真正接进 `pdf_export.py`。

### L2 · `_TTLCache` docstring 称 LRU，实现是 FIFO

`_common.py:278`：`"""Thread-safe TTL cache with LRU eviction."""`
但 `get()`（L289-299）命中时**不刷新时间戳**，`set()`（L304-306）按最旧 `ts` 逐出 —— 这是 FIFO，不是 LRU。热键会被误逐。

**修法**：改 docstring，或在 `get()` 命中时更新 `ts`。

### L3 · `web/app.py` 两处过期字面值

- `:661` `_ver = "0.2.18"` —— 取包版本失败时的回退值，pyproject 已是 0.2.19。这类回退值注定会漂移，建议回退成 `"unknown"` 而不是硬写一个旧版本号。
- `:538` banner 副标题写死 `v2026-05-22` —— 已过期 4 个多月，而这段时间恰好是改动最密的。

### L4 · CLAUDE.md 的本地测试命令会二次拉起 Streamlit

`CLAUDE.md:66`：`Web UI 改动在 web/ 目录，用 streamlit run web/launch.py 本地测试`

`web/launch.py:21-38` 是个 argparse 启动器，自己会 spawn `streamlit run web/app.py`。在 streamlit 下跑它 = 二次拉起，且 argparse 会吞掉 streamlit 传进来的参数。README.md:244、README.en.md:160、docs/DEPLOY.md:13、docs/demo-script.md:12、DEV_LOG.md:409 全都写的是 `web/app.py` —— **只有 CLAUDE.md 这一处错**，而 CLAUDE.md 恰恰是给 AI 助手读的。

**修法**：改成 `streamlit run web/app.py`（或 `tradingagents-web`）。

### L5 · DEV_LOG「开放问题（待决策）」四项全部已落地，仍挂着未勾选框

`DEV_LOG.md:588-591`：

| 未勾选项 | 实际状态 |
|---|---|
| 要不要加 Web UI？— 倾向**先不加** | `web/` 全套 5,965 行 |
| 要不要做 Docker 镜像？ | `Dockerfile` + `docker-compose.yml` |
| 要不要 GitHub Actions CI？ | `.github/workflows/ci.yml`（含 windows 矩阵） |
| 要不要英文 README？ | `README.en.md`（v0.2.19 新增） |

四项全做完了，文档还在说"倾向先不加"。同文件 `:597` 还写着 `CHANGES_FROM_UPSTREAM.md`（**待建**）—— 该文件早已存在（虽然内容过期，见 H6）；`:581` 的风险表仍建议"海外用户用 akshare fallback"，而实际兜底是新浪 HTTP。

**修法**：勾选并注记落地版本，或整段移入"已决策"归档；风险表的 akshare 改为新浪 HTTP。

### L6 · README 徽章两处小瑕

- `README.md:7` 与 `README.en.md:7`：`badge/version-0.2.19-green" alt="Version 0.2.18"` —— 图片是 0.2.19，alt 文本是 0.2.18。
- `README.md:10` 用实时 Actions `badge.svg`；`README.en.md:10` 用静态 `shields.io/badge/CI-passing` —— **CI 挂掉时英文版仍然恒绿**。

### L7 · `cached_call` 是死代码，且 docstring 引用不存在的函数

`_common.py:321` 定义 `cached_call`，全仓唯一另一处出现是它自己 docstring 里的示例（`:325`），而示例调用的 `_tencent_quote_raw` **在全仓不存在**（grep 仅命中该 docstring 行）。

**修法**：删除，或接进实际调用点。

### L8 · `news.py` 两处时间窗语义与实现不符

- `news.py:144-149`：时间解析失败时 `except (ValueError, IndexError): pass`，该文章**不被过滤、直接保留** —— 区间外的新闻可能混进结果。
- `news.py:186-189`：`look_back_days` 参数实际只影响 `:272` 的表头文案，函数只取最新 `limit` 条，**不做任何时间窗过滤**。参数是装饰性的。

**修法**：解析失败的文章丢弃或显式标注；`get_global_news` 按 time 字段做真实窗口过滤，或删掉该参数。

### L9 · `scan_sectors.py` 依赖未声明的 akshare，且警告写成了裸字符串

`scan_sectors.py:6` `import akshare as ak`，而 akshare 不在 `pyproject.toml` 依赖里（v0.2.5 已移除）。fresh install 下这个根目录脚本直接 ImportError。

更别扭的是 L2：

```python
"# 独立脚本：需自行 pip install akshare（不在 pyproject 依赖中）"
```

这是一个**字符串字面量表达式，不是注释**（注释不会带引号）。它不报错、不显示、对读者几乎不可见 —— 恰恰是唯一那句警告。

**修法**：加 `[project.optional-dependencies] scripts = ["akshare"]`；把那行改成真注释 `# ...`。

### L10 · `tools/generate_report.py:336` 硬编码桌面输出路径

```python
output_path = 'C:/Users/zhzsh/Desktop/A股科技板块投资分析报告.docx'
```

写死用户名，他人运行即失败或写到错误位置。同类问题另见 `tools/boot_verify/`（DEV_LOG 记录该目录的硬编码路径**已参数化**为 `ASTOCK_REPO`/`ASTOCK_JOURNAL` 环境变量，可作为改法参照）。

### L11 · 蜡烛图 `rangebreaks` 只排周末，法定节假日留空隙

`data_dashboard.py:116`：`rangebreaks=[dict(bounds=["sat", "mon"])]`

春节、国庆等长假在图上会留出一段空白，5 日视图跨假期时还会缺棒。docstring（`:69`）自称"周末 rangebreaks 去掉非交易日空隙"，措辞上没错，但效果上不完整。

**修法**：用交易日历生成 `values=[...]` 形式的 rangebreaks（数据层的 `_needs_sina_supplement` 附近已有交易日判断可复用）。

### L12 · 蜡烛色硬编码亮色主题值，与 CHANGELOG 的说法不符

`data_dashboard.py:83`：`up_c, dn_c = "#e03131", "#2f9e44"` —— 这是 `theme.py:45-46` 的**亮色**变量值。暗色主题是 `theme.py:140-141` 的 `#ff6b6b` / `#51cf66`。

CHANGELOG v0.2.19 写的是"涨红跌绿与主题 `--up`/`--down` 同色系" —— 实际是写死了亮色值，暗色下不会跟随。（同文件 `:381` 的文字涨幅用的是 `var(--up)`，是对的，说明只有 plotly 这条路径漏了。）

**修法**：把当前主题的 up/down 值作为参数传进 `_show_candles`。

### L13 · LLM 调用无默认超时

`tradingagents/llm_clients/openai_client.py:150-152` 只 `setdefault("max_retries", 3)`；`:108` 的 `timeout` 在透传白名单里，但 `default_config.py` 没有 timeout 键 —— 即**只有用户显式配置才有超时**。否则走 SDK 默认（600s）× 3 次重试，单次挂起可阻塞约 30 分钟。

辩论轮数（`conditional_logic.py:81,91` + `default_config.py:44-45`）与 `recursion_limit=100` 都有上限，重试也封顶 3 次，**成本控制这块整体是干净的**，缺的只是超时。

**修法**：`llm_kwargs.setdefault("timeout", 120)`。

### L14 · `get_industry_comparison` docstring 与实现不符，"top/bottom"只有 top

`signals.py:687-688` docstring 称会 "highlight the sector the target stock belongs to"，但代码从未定位该股所属行业（`code` 只出现在 `:697` 的标题里）。
`:737-738` 的 `if i >= top_n * 2 - 1` 之后打印 "showing top/bottom {top_n}"，而列表按涨幅降序（`po=1`，`:705`）只取了前 40 名 —— **没有 bottom**。

**修法**：实现行业定位，或改 docstring 与文案。

### L15 · 新浪兜底的成交量单位疑与 mootdx 差 100 倍（**未核实**）

`web/data_functions.py:205-216` 的兜底把 `_load_ohlcv_astock` 的 `Volume` 重命名为 `vol`；该 Volume 来自 `_common.py:610` `"Volume": int(item["volume"])`（新浪返回股数），而 mootdx 直连路径的 `vol` 是手数；`data_dashboard.py:383` 标注为 `{avg_vol/10000:.1f}万手`。

**这条只是代码推理，没有实测两个源的返回值，因此标为未核实。** 若成立，兜底生效时"日均成交量"会大 100 倍。

**核实办法**：同一标的同一交易日，分别走 mootdx 与新浪通道取一根 K 线，比对 volume 数量级。

### L16 · 并发与续跑的测试只做静态断言，不真正跑图

- `tests/test_parallel_analysts.py:17-20`：只取 `tg.graph.get_graph().edges` 断言拓扑，**全文件不 invoke/stream**。CHANGELOG 声称的"计数闸门保证质量门恰好执行一次"没有运行时验证。
- `tests/test_checkpoint_resume.py:37-44`：用两节点串行 toy graph，不覆盖并行 fan-out 的续跑（也就抓不到 H2）。
- `tests/test_safe_ticker_component.py`：无中文名兜底用例（`resolve_ticker` grep 零命中）。

**修法**：加一个假 LLM（错峰完成 + 其中一个抛异常）的并行图端到端测试，断言质量门调用次数 == 1。这一个测试能同时钉住 M15 与 H2。

---

## 5. 建议修复顺序

排序依据：**是否会产生错误结论（而非仅仅不便）> 是否面向他人 > 改动量**。

| 序 | 项 | 改动量 | 理由 |
|---|---|---|---|
| 1 | **H1** 市值字段互换 | 2 行 + 夹具 | 已实测确证；同时污染 LLM 输入与看板显示；改动最小、收益最大 |
| 2 | **H5** 30日涨幅按 50 根算 | 1 行 | 用户直接看到的错数字，一行修完 |
| 3 | **H4** 三处误用 safe_ticker_component | 3 行 | 静默查空 → 输出"未上榜"这种错误结论 |
| 4 | **H3** 龙虎榜机构动向双重静默 | ~6 行 | 同型错误结论；与 H4 在同一函数群，可一并改 |
| 5 | **M14** 给上面三处补 fixture 测试 | 新增测试 | **建议与 1/3/4 同批做**：先写能复现缺陷的测试，再修，缺陷才钉得住 |
| 6 | **H2** Web 续跑失效 | 1 行 + 文案 | 一行开开关即可；但要先确认 checkpoint 落盘目录与清理策略。**修好前先把"可继续"文案改成"重新分析"** |
| 7 | **H6 + M16** 归属链与 NOTICE | 文档 + 元数据 | 面向外部读者，且是 fork 合规门面 |
| 8 | **M8** data_functions 补日志 | ~8 处 | 与 H3 同一失效模式，防下一次"百度 PAE" |
| 9 | **M9 + M10** 缓存污染两则 | ~6 行 | 数据正确性，且北向 CSV 是唯一历史来源，脏了不可逆 |
| 10 | **M1 / M3 / M4 / M5** 启动与主题桥 | 各 3-10 行 | 都是小改，集中在 `journal_service.py` / `trade_journal.py` / `launch.py` 三个文件，可一批做完 |
| 11 | **M6 / M7** 并发缓存加锁 | ~10 行 | 并行分析师是 opt-in，暴露面较小，但改法明确 |
| 12 | **H7** 桌面 bat | ~5 行 | 仅在准备分发时做；但**杀端口前先校验映像名**建议尽早，误杀无关进程是真损失 |
| 13 | **M12 / M13 / M15 / L13** CI 与生产化 | 中等 | 前序 P7 说的"主动认下短板"就是这几条，可以暂时不修但要能讲清楚 |
| 14 | **L1–L16** 其余 | 小 | 顺手清；其中 **L1（删死代码）** 与 **L4（CLAUDE.md 命令）** 建议尽早，两者都会误导读者 |
| — | **P3** theme.py 1130 行拆分 | 大 | 投入产出比最低，继续搁置 |

**一条贯穿性建议**：本轮 7 条高严重度里，H1/H3/H4/H5 的共同点是**"错误被静默地当成正常结果输出"**。测试全绿、ruff 全绿、日志无异常，但报告里的数字是错的。补 fixture 测试（M14）比逐条打补丁更能防止这类问题复发——因为它们的共同特征就是"不会报错"。

---

## 6. 已核实为干净的范围（审计边界）

列出这些是为了说明**本清单的覆盖面**，以及哪些方向不必再查。

**数据层**
- **东财限流覆盖完整**：全部 7 处 eastmoney 请求都走 `_em_get`（`fundamentals.py:89`；`news.py:55,232`；`signals.py:381,430,713`；`_common.py:520`）；9 处裸 `requests.get` 均为非东财域名（同花顺/新浪/财联社/hexin/百度），与 `_common.py:417-418` 的设计声明一致。
- **TDX 锁覆盖完整**：全仓无 `_common.py` 之外的 pytdx/mootdx 导入；所有 client 调用经 `_LockedTdxClient.__getattr__`（L199-214）持 `_TDX_LOCK`。唯一缺口是客户端创建期竞态（`_get_mootdx_client` L242-253 单例无锁）。
- **资金流字段映射正确**：`get_fund_flow` 实时/历史两处 `parts[1..5]` → 主力/小单/中单/大单/超大单，与东财 f52-f56 顺序一致（`signals.py:391-398, 443-453`），元→万换算正确。
- **前视偏差防护到位**：`_load_ohlcv_astock` 按 `curr_date` 截断（L768-769）；`_realtime_disclaimer` 机制设计合理。
- 六个文件均**无可变默认参数**。
- **路径穿越未发现绕过**：`safe_ticker_component` 对分隔符/空白/NUL/纯点均拒绝（`utils.py:39-44`）。H4 是"没规范化"，不是"能被穿越"。

**Web 层**
- 顶部搜索框**确实存在**（`data_dashboard.py:201-205`），回调与侧边栏同源 `resolve_ticker`；只捕 `ValueError` 是安全的——`_common.py:138-143` 已把 mootdx 网络异常包装为 ValueError。
- web 端蜡烛图**涨红跌绿正确**；MA 先算后 tail，**无未来函数**；`copy()` + `st.cache_data` 返回副本，**无缓存原地污染**；`chg5`/`eps` 有除零防护。
- 骨架屏门控与 `ph.empty()` 清理逻辑正确。
- 行情字段（pe_ttm/limit_up/amount_wan 等）与核心层 `_tencent_quote` 返回完全对应（**44/45 两位除外**，见 H1）。
- `history.py` 原子写盘 + 锁使用正确；`boot_splash.py` 看门狗设计自洽；`runner.py` finally 双调 `close_graph_run` 幂等（`trading_graph.py:416-421` 有 None 守卫）。
- postMessage 桥与骨架屏**无字符串插值注入用户数据的 XSS 面**（`__CODE__` 已校验为 6 位代码）。
- `ruff check web/` 全通过。

**编排层**
- **质量门"恰好一次"在结构上成立**：`setup.py:179-190` 的 Analyst Join 每 super-step 至多执行一次，路由 lambda 读 reducer 合并后的状态，`agent_states.py:7-9` 的 `merge_unique` 集合去重封顶 7。**未能构造出双触发路径**（但无运行时验证，见 L16）。
- **worker 异常不会静默悬挂 fan-out**：7 个分析师文件 `try:` 零命中，异常沿 Pregel 上抛 → `runner.py:189-207` `mark_error`；ToolNode 默认把工具错误转为 ToolMessage。
- **锁完备的组件**：`ProgressTracker`（`progress.py:55-206` 全方法持锁 + snapshot）、`StatsCallbackHandler`（`stats_handler.py:14`）、`_TTLCache` / `_EMRateLimiter` / `_LockedTdxClient`。
- **checkpoint 落盘位置正确**：checkpoint 与结果均写 `~/.tradingagents`（`default_config.py:7-9`），**不在仓库树内**；thread_id 按 ticker+date 隔离（`checkpointer.py:28-30`）；表名与本机 langgraph-checkpoint-sqlite 3.1.0 的 CREATE TABLE 匹配（`checkpointer.py:84-85` 的 DELETE 有效）。
- **成本有上限**：辩论/风控轮数封顶、`recursion_limit=100`、LLM 重试上限 3，**无无限重试**（缺的只是超时，见 L13）。

**工程化**
- **`[google]` extra 隔离成立**：`llm_clients/google_client.py:3` 是唯一顶层导入点，生产代码仅 `factory.py:46` 函数内懒导入；主依赖不含 langchain-google-genai。
- **`plotly>=6.0.0` 三处一致**：`pyproject.toml:23` 声明；`requirements.txt` 仅 `-e .` 转发（无独立枚举）；`Dockerfile:11` `pip install .` 走 pyproject。**无遗漏。**
- **CI 矩阵含 windows-latest**：`ci.yml:41` `os: [ubuntu-latest, windows-latest]`，Python 3.10 / 3.13。ruff 版本已固定（`ci.yml:17` `ruff==0.15.20`）。
- **`.env.example` 存在**（含 `DEEPSEEK_API_KEY`）。
- `wait_ready()` 的双探活（`journal_service.py:49-64`）已按 DEV_LOG:553 的教训实现"两次 200 且间隔 ≥150ms"。

**文档**
- **CLAUDE.md 关键路径全部属实**：`a_stock/` 包 5 模块、`dataflows/utils.py`、`interface.py`、`_EMRateLimiter`（`_common.py:425`）、`EM_MIN_INTERVAL`、`resolve_ticker` / `_build_name_code_map` 均存在；版本号确未硬写（`:9` 指向 pyproject）。**唯一错处是 L66 的启动命令**（见 L4）。
- **测试数 171 与文档一致**：实测 `pytest --collect-only` = 171，与 `README.md:11/199`、`README.en.md:11/142` 相符。
- README 两版引用的**全部资源路径均存在**：assets 图片、demo.gif、`docs/boot-splash/evidence/`、`experiments/README.md`、`.env.example`、`run_all.bat`、`examples/run_cases.py`、`scripts/make_demo_gif.py`、`.streamlit/config.toml`。
- **入口命令与 `[project.scripts]` 一致**：`tradingagents` / `tradingagents-web` / `python web/launch.py --with-journal`（`launch.py:23` 确有该参数）/ `streamlit run web/app.py`；`pip install -e ".[google]"` 在 README.md:227、CLAUDE.md:42、CHANGELOG.md:308 三处写法一致且正确。
- README/README.en/DEPLOY/demo-script **正文均无 akshare 残留**（残留只在 NOTICE 与 DEV_LOG，见 H6 / L5）。

---

## 7. 本轮推翻的三条判断（含子代理误判）

按"结论要能被证据推翻"的原则，记录本轮被否掉的说法：

| 被推翻的判断 | 核实结果 |
|---|---|
| 前序 P2："`web/data_functions.py` 14 处静默 except 属低优先，下层自带日志" | **推翻并升级为 M8**。实测该文件 15 处 except、0 处 logging，其中 `index_spot` 等 7+ 个函数是 UI 层自实现解析，**根本不经核心层**，无任何一层会记录 |
| 子代理："docker-compose 强依赖被 gitignore 的 `.env`，且仓库无 `.env.example` 引导" | **后半句错**。`.env.example` 确实存在（已 `ls` 核实）。该条不成立，未收录 |
| 子代理："PDF 涨跌配色反了"定为**高**严重度 | **降级为 L1**。`chart_utils.py` 是死代码（全仓零引用），配色错误当前不会显示出来；真正的问题是"死代码 + 依赖未声明"这个陷阱本身 |

---

## 8. 明确未核实的项（不作为结论）

| 项 | 缺什么证据 |
|---|---|
| **L15** 新浪兜底 volume 单位是否与 mootdx 差 100 倍 | 需同一标的同一交易日双通道实测比对数量级 |
| **M13** 容器内 mootdx（TCP 7709）是否可用 | 需在容器内实测；mootdx 需大陆 IP 属环境约束推断 |
| `[google]` extra 与 mootdx 的 httpx 版本是否真互斥于同一环境 | 需实装 `pip install -e ".[google]"` 后跑测试 |
| `CLAUDE.md:57` PR #18（hejingchi）是否仍待处理 | v0.2.6 时代所写，距今 4 个多月，需联网查 PR 状态 |
| `CLAUDE.md:69` a-stock-data 外链是否有效 | 需联网核实（DEV_LOG:567 亦记录"保留待确认"） |
| `signals.py:46` 键名 `"errocode"` 是否为上游拼写 | 需比对东财接口原始返回 |
| `theme.py:455-495` `:has` 顶栏 CSS 的实际渲染效果 | 结构已读通，浏览器渲染未实测 |

---

## 附：本轮审计方法

1. 实跑 `pytest tests/`（171 passed + 59 subtests）与 `ruff check .`（全绿），确立基线。
2. 五个方向并行审计：数据层 / web UI（重点 v0.2.19 新增代码）/ 启动链与打包 / agents 编排 / 文档一致性。
3. **逐条回到当前树核实**：每条收录的缺陷都有本人实读过的 `file:line` 与代码引用；子代理提出但未能核实的，一律标注"未核实"或剔除（见第 7、8 节）。
4. 对唯一一条可实测的数据正确性缺陷（H1），直接发真实请求到 `qt.gtimg.cn` 取回字段并用总股本反推验证，而不是依赖字段表文档。
