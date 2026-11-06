# P4 任务拆票：市场看板与股票工作区

版本：v1（2026-11-06）
上游：`docs/upgrade/reviews/2026-11-06_P3出口评审.md` 结论为 Go。
依据：`docs/AStock_Pro_专业投研工作台全面升级计划_2026-10-28.md` 第 2.3、2.4、3.1 至 3.4、4.1、4.3、4.4、9、10.1 至 10.4、11.3 节；`docs/upgrade/contracts/api-v1.md` 第 3 节；`docs/upgrade/contracts/market-data-envelope-v1.json`；`docs/upgrade/contracts/routes.md` 第 1 至 3 节；`docs/upgrade/contracts/core-wireframes.md` 第 7、8、11 节；`docs/upgrade/contracts/interaction-checklist.md` 的 M01、M06、M07、A01、A04；`docs/upgrade/contracts/error-codes-v1.md` 第 1、4 节。
用途：把 P4 拆成 13 张可独立验收的票（P4-00 至 P4-12）。每票单独提交、单独回退、单独跑测试。

P4 交付市场看板、股票工作区、工作台摘要补全、市场数据服务与刷新策略。完成后新版覆盖「市场 → 股票 → 分析 → 任务 → 报告」主链路，但**不切换默认入口**；旧版 Streamlit 仍是默认写入口，交易日志、设置与双栈灰度仍留给 P5/P6。

## 0. 公共约束

- 技术栈不换：React 19 + TypeScript + Vite + TanStack Query；后端 FastAPI + SQLAlchemy + Alembic。前端不新增运行时依赖，K 线与分时自绘 SVG。
- 只实现 `api-v1.md` 第 3 节已冻结的 12 个市场/股票端点（`/market/search` 已在 P2 实现，P4 新增其余 11 个）。不新增 HTTP 字段、错误码、状态名、事件名。
- P4 零迁移：不建表、不改表，迁移头保持 `0007`。
- 冻结契约不改。发现缺口先按第 1.2、1.3 节记录口径；确需改契约时走 `FREEZE-v1.md` 第 4 节解冻，不允许先改代码再补契约。
- 后端不得 `import web.*`（GF-06）；可 `import tradingagents.dataflows.*`。市场抓取只在 backend 服务层。
- 市场 GET 不写库、不写文件、不建目录：磁盘只读名称表与夹具，刷新只更新进程内缓存。外部网络只允许出现在 provider 层；测试全部注入假 provider。
- 不改 `tradingagents/`、`web/`、`run_all.bat` 与旧版 8501 入口。
- 断点仍为 767px；触控目标 ≥44px；360/390 无页面级横向溢出，只允许图表、页签、指数条在容器内滚动。
- 一票一本地提交，不推送；开工前与收工前预检必须 10 项 PASS。
- 测试不联网、不读 API Key、不读写真实 `~/.tradingagents`；市场数据用固定夹具与假 provider。
- 前端 `fetch` 与 `/api/v1` 字面量只出现在 `frontend/src/api/`；错误文案只来自 `ApiError.message` 或本地 copy 表，不渲染响应体、堆栈、绝对路径。
- 计划书与冻结契约冲突时以契约为准，冲突写进第 1.2 节，不临场扩契约。

## 1. 票内定稿（后续票不再临场决定）

### 1.1 十二项决定

**D1 数据分层**

`provider`（抓取与解析，返回结构化数据）→ `market_service`（TTL 缓存、陈旧判定、信封拼装）→ `router`（参数校验、HTTP 映射）。provider 通过 `app.state.market_providers` 注入，dev、单测与 E2E 都可用夹具替换。

理由：旧版把抓取、缓存、UI 文案混在 `web/data_functions.py`，无法在无网络下测试；分层后信封与状态机可以单测。

**D2 零写盘**

GET 路径不调用旧版会落盘的函数：名称表重建、日 K CSV、北向 CSV、公告 PDF 缓存。K 线/分时走 mootdx/新浪内存取数；名称表只读，不 `makedirs`。进程内 `_TTLCache` 承担缓存。

理由：旧版 `_common._load_ohlcv_astock` 会写 CSV，`signals.py` 会写北向快照；市场 GET 一旦复用就会污染 HOME，测试也无法断言零副作用。

**D3 信封与陈旧**

信封由单一 builder 生成：四态 `ok / empty / error / stale` 加修饰符 `partial` 与 `failed_blocks`。多块接口严格按 `api-v1.md` 3.0 的合并表：

- 请求失败但有旧数据 → `stale`，`stale_reason` 取 `ttl_exceeded` 或 `trading_day_mismatch`；
- 请求失败且无旧数据 → `error`，`error_code` 取数据源码；
- 主源失败、备用源成功 → 按新鲜度给 `ok` 或 `stale`；走备用源时 `stale_reason = upstream_fallback`；
- `empty` 只表示数据源正常但没有数据。

**D4 前端状态外壳**

`DataState` 负责 `loading / ok / empty / error / stale` 五态；`partial` 是修饰符，不是第五态（与 CT-05 的「partial 不是第五态」一致）。empty 与 error 必须有不同文案与不同 testid；stale 横幅按 `stale_reason` 显示中文原因；partial 显示 `failed_blocks` 对应的块名。

**D5 图表自绘**

`KLineChart` / `IntradayChart` 用 SVG 实现，不新增依赖；支持周期按钮、缩放、平移、十字光标、图例开关、数据时间、午休断线。若自绘达不到验收，再评估 `lightweight-charts`，且必须先完成 P4-04 的按路由拆包并记录 bundle 变化，不在票内临时加依赖。

**D6 路由拆包**

P4-04 把页面改为 `React.lazy` 按路由分包。首屏入口 chunk 的 JS gzip 不高于 P3 的 202.45 kB；新增页面各自成块，单块 ≤60 kB（gzip）。P2/P3 的 E2E 与 bundle 回归必须同过。

理由：P3 出口时距 30 kB 触发线只剩 5.47 kB，市场与股票页面必然超标；拆包是 P4 的前置条件，不是收尾优化。

**D7 页签口径**

按 `routes.md` 实现五个 tab：`valuation | kline | intraday | news | reports`。wireframe W07 的「任务」页签不实现为 tab，改为头部两个入口：「查看进行中任务」`GET /jobs?ticker=…&active=true&limit=1` 与「查看该股票任务」`/jobs?ticker=…`。Query 中非法 tab 回 `valuation`，不改写路径。

理由：`routes.md` 明确 `/stocks/:ticker` 的 tab 是估值/K线/分时/新闻/报告；新增第六个 tab 会改路由契约。

**D8 移动钻取**

行业成分股在移动端用全屏覆盖层表达：`/market?board=BKxxxx`。不新增路由；关闭与返回用 history 恢复原滚动位置。

**D9 刷新策略**

只轮询可见页面；`document.hidden` 时降频到 60 s，回到前台立即按 query 失效重取；手动刷新 500 ms 防抖；轮询间隔不小于契约 `stale_after`（指数 10 s、行情 60 s、快讯 120 s 等）；切页或离开立即停表。

**D10 股票解析**

路径只接受 6 位数字；格式非法或名称表查不到 → HTTP 400 `invalid_request`，`details.field="ticker"`，文案「没有这只股票」，给搜索框与回市场，不静默改写。名称表本身不可用 → 500 `internal_error`，不伪装成 400。

**D11 不扩契约**

参数范围、状态文案、tab 词表写在本文件。不为「数据源降级提示」「行业净流入」「北向历史」新增字段。确需新增时走解冻票，先改契约与测试，再改代码。

**D12 旧版等价例外**

北向 20 日历史、旧 K 线周期（单日/5日/30日/全部）、旧「行业资金」块（实为行业涨跌榜）不按原样复刻。差异写进第 1.5 节与 P4 评审，不伪造数据。

### 1.2 十处冲突

| 编号 | 冲突 | 定稿口径 |
| --- | --- | --- |
| C1 | 计划 4.3 写四个内容分区，wireframe W07 写六个页签，`routes.md` 写五个 tab | 按 `routes.md` 五 tab（D7）；四个内容分区映射进估值、K 线、分时、新闻、报告 |
| C2 | 计划 4.4 保留「行业资金」 | 旧版 `industry_comparison(15)` 只有涨跌幅、涨跌家数、领涨股，没有净流入；v1 行业端点已覆盖，不新增净流入字段 |
| C3 | 计划 4.4 写「快讯和个股新闻」，wireframe W08 只有快讯 | 市场页只放 `/market/newsflash`；个股新闻在 W07 新闻页签（`/stocks/{ticker}/news`） |
| C4 | 旧版北向有 20 日历史（本地 CSV），v1 只有 `points` 与 `latest` | P4 只画当日 `points` 与 `latest`，不做 20 日历史；差异进等价清单例外 |
| C5 | 旧 K 线周期是单日/5日/30日/全部，v1 是 `day/week/month` | 按 v1；旧周期不复刻 |
| C6 | 计划 4.4 有「题材归因」与「点击题材筛选相关股票」，v1 无题材端点 | 用 `/market/strong-stocks` 的 `reason` 在前端聚合 TOP8 题材；点题材只筛当前已加载的强势股，不做全市场题材检索 |
| C7 | wireframe W07 有「任务」页签，`routes.md` 没有 | D7：头部入口 + `/jobs?ticker=`，不增加 tab |
| C8 | `api-v1.md` 第 3 节未写参数级错误语义 | 用 400 `invalid_request` + `details.field`，不新增错误码；口径见 1.3 |
| C9 | `api-v1.md` 3.0 称市场文案见 `semantic-dictionary.md`，该文件没有市场文案 | P4 在 `frontend/src/features/market/copy.ts` 落地并有单测；契约不修改，记为已知瑕疵，P5 统一收口 |
| C10 | 工作台「最近报告」仍是 P3 占位（P2 留给 P3，P3 未接），「市场概览」是 P4 占位 | P4-05 一并补全，清掉过时文案 |

### 1.3 参数校验与错误映射（实现口径，不改契约）

| 参数 | 规则 | 违反时 |
| --- | --- | --- |
| `{ticker}` | `^\d{6}$` 且能在名称表解析 | 400 `invalid_request`，`details.field="ticker"`；名称表不可用则 500 `internal_error` |
| `{boardCode}` | `^BK\d{4}$` 且存在于最近一次行业快照 | 400 `invalid_request`，`details.field="boardCode"` |
| `period` | `day \| week \| month` | 400 `invalid_request`，`details.field="period"`，给 `allowed_values` |
| `limit` | K 线 1–5000 默认 120；新闻 1–100 默认 20；成分股 1–100 默认 10；快讯 1–100 默认 30 | 400 `invalid_request`，`details.field="limit"` |
| `top` | 1–50，默认 20 | 400 `invalid_request`，`details.field="top"` |
| `date`（强势股） | `YYYY-MM-DD` 或省略 | 格式非法 400 `details.field="date"`；非交易日返回 `empty` |
| `date`（分时） | `YYYY-MM-DD` 或省略 | 格式非法 400 `details.field="date"`；省略取最近交易日；非交易日回退最近交易日并在 `data.date` 如实返回；超出保留期返回 `empty` |
| `q` / `limit`（搜索） | 已由 `TickerDirectory` 实现，P4 不改 | 沿用现有实现 |

错误分层：

- 参数非法 → HTTP 400，标准错误体（`error-codes-v1` 第 1 节），不是市场信封。
- 数据源失败 → HTTP 200，市场信封 `status=error`，`error_code` 用 `upstream_timeout / upstream_error / upstream_rate_limited / data_parse_error`。
- 未实现 → 501 `not_implemented`；P4 完成后第 3 节端点不再返回 501。

### 1.4 状态与文案口径

| 界面状态 | 信封条件 | 文案与呈现 |
| --- | --- | --- |
| loading | 请求未返回 | 骨架屏，尺寸与最终内容一致；`aria-busy="true"` |
| ok | `status=ok`、`partial=false` | 内容 + 来源 + 数据时间 |
| empty | `status=empty` | 「暂无数据」；强势股非交易日「非交易日或盘后未更新」；分时超保留期「该日期没有分时数据」 |
| error | `status=error` | 「数据源请求失败」+「重试」；不显示内部错误码 |
| stale | `status=stale` | 「数据可能已过期」+ 原因：`ttl_exceeded`「超过新鲜度阈值」、`trading_day_mismatch`「数据日期早于最近交易日」、`upstream_fallback`「已使用备用数据源」 |
| partial | `partial=true` | 可用内容照常显示 +「部分数据不可用」+ 块名（行情/估值/板块/指数/北向） |

来源显示映射（`source` 值 → 中文）：`tencent` 腾讯、`eastmoney` 东方财富、`ths` 同花顺、`hexin` 同花顺、`cls` 财联社、`mootdx` 通达信、`mootdx-cache` 本地名称表、`baidu` 百度、`mixed` 多源、`static` 本地。

### 1.5 等价清单与例外

P4 出口按这张表逐项核对旧版能力。

| 编号 | 旧版能力 | 旧版位置 | P4 对应 | 结论 |
| --- | --- | --- | --- | --- |
| E1 | 指数概览 | `web/app.py:413-452`、`index_spot` | `/market/overview` 的 `indices` + W08 指数卡 | 等价 |
| E2 | 行业涨跌榜 | `industry_comparison` | `/market/industries` + W08 行业表 | 等价 |
| E3 | 行业成分股 | `industry_stocks` | `/market/industries/{code}/stocks` + 抽屉/全屏 | 等价 |
| E4 | 强势股 | `ths_hot_reason` | `/market/strong-stocks` + W08 表格/卡片 | 等价 |
| E5 | 题材归因 | 旧版对 `reason` 做 TOP8 | 前端对 `reason` 聚合 TOP8 + 本地筛选 | 部分等价（见 C6） |
| E6 | 北向资金 | `hsgt_realtime` + 20 日 CSV | `/market/overview` 的 `northbound` | 例外（无 20 日历史，见 C4） |
| E7 | 行业资金 | `industry_comparison(15)` | `/market/industries` 的 top/bottom | 等价（旧版本也是涨跌榜，见 C2） |
| E8 | 快讯 | `cls_telegraph` | `/market/newsflash` + W08 快讯区 | 等价 |
| E9 | 个股新闻 | `eastmoney_stock_news` | `/stocks/{ticker}/news` + W07 新闻 tab | 等价 |
| E10 | 行情快照 | `tencent_quote` | `/stocks/{ticker}/snapshot` 的 `quote` | 等价 |
| E11 | 一致预期与估值 | `ths_eps_forecast` + 旧计算 | `snapshot.valuation`（缺失为 null，界面「—」） | 等价 |
| E12 | 行业/概念/地域 | `baidu_concept_blocks` | `snapshot.sector_blocks` | 等价 |
| E13 | 历史报告 | `web/history.py` | `/stocks/{ticker}/reports` + W07 报告 tab | 等价 |
| E14 | K 线与成交量 | `_get_kline_full` | `/stocks/{ticker}/kline` + KLineChart | 等价（周期不同，见 C5） |
| E15 | 分时 | `get_intraday_view` | `/stocks/{ticker}/intraday` + IntradayChart | 等价 |
| E16 | 资金流 | 旧资金流数据 | `/stocks/{ticker}/fund-flow` + 估值 tab | 等价 |
| E17 | 自动刷新 | `st_autorefresh` 交易 45 s / 非交易 3600 s | D9 可见页轮询 | 行为差异，记录 |
| E18 | 数据状态 | 旧版空/失败混同，无 stale/partial | 四态 + partial | 新版增强 |

### 1.6 其它锁定项

- 查询键（`frontend/src/lib/query.ts`）：`market:overview`、`market:industries(top)`、`market:constituents(board,limit)`、`market:strong(date)`、`market:newsflash(limit)`、`stock:snapshot(ticker)`、`stock:kline(ticker,period,limit)`、`stock:intraday(ticker,date)`、`stock:news(ticker,limit)`、`stock:fundFlow(ticker)`、`stock:reports(ticker,cursor)`。
- `staleTime` 取契约新鲜度阈值；`refetchInterval` 只经 P4-11 的可见页 hook 设置，不在组件里各写一份。
- URL：`/market?top=20&date=YYYY-MM-DD&board=BK0475&theme=算力`；`/stocks/:ticker?tab=valuation|kline|intraday|news|reports&period=day|week|month&date=YYYY-MM-DD`。
- 滚动记忆键：`market:scroll:<top>:<date>`、`stock:<ticker>:<tab>:scroll`。只在点击跳转与 popstate 时写入，刷新后列表回顶部（与 P3-04 的返回现场实现同法）。
- testid：`page-market`、`page-stock`、`market-session`、`market-indices`、`market-industries`、`market-strong`、`market-newsflash`、`stock-header`、`stock-tabs`、`stock-valuation`、`stock-kline`、`stock-intraday`、`stock-news`、`stock-reports`；状态外壳用 `data-state="loading|ok|empty|error|stale"` 与 `data-partial`。
- bundle 预算：入口 chunk ≤202.45 kB gzip；单个新路由 chunk ≤60 kB gzip；记录全部 chunk 原值，不四舍五入。
- 证据文件：后端与前端结果写 `docs/upgrade/reviews/2026-11-XX_P4-0x*.json`；出口评审写 `2026-11-XX_P4出口评审.md`。
- 截图落 `ui_shots_p4/<票号>/`，不入库。

## 2. 任务总表

| 编号 | 任务 | 依赖 | 主要验收 | 独立回退方式 |
| --- | --- | --- | --- | --- |
| P4-00 | 拆票与口径定稿 | 无 | 本文件与 `P4-01交接卡.md`；预检 10 PASS | 删除两份文档，不碰产品代码 |
| P4-01 | 市场数据服务内核 | P4-00 | ENV-01 至 ENV-08 | 删除三个服务与测试；路由未接 |
| P4-02 | 市场接口组 | P4-01 | MKT-01 至 MKT-09；R-10 | 下线五个市场 GET；服务层保留 |
| P4-03 | 股票接口组 | P4-01 | STK-01 至 STK-10；R-12 | 下线六个股票 GET；报告接口不受影响 |
| P4-04 | 路由拆包与数据状态外壳 | P4-00 | DS-01 至 DS-08；bundle | 还原静态 import 与 `routes.tsx` |
| P4-05 | 工作台摘要补全 | P4-02、P3 报告接口 | WB-01 至 WB-04 | 工作台恢复 P3/P4 占位文案 |
| P4-06 | 市场看板 W08 桌面 | P4-02、P4-04 | W08-01 至 W08-08；R-10、R-11 | `/market` 回占位页 |
| P4-07 | 市场看板 W08 移动 | P4-06 | W08M-01 至 W08M-04；R-14 | 移动分支回桌面单栏 |
| P4-08 | K 线与分时图表 | P4-00 | CHT-01 至 CHT-08 | 删除图表组件；页面显示占位 |
| P4-09 | 股票工作区 W07 桌面 | P4-03、P4-04、P4-08 | W07-01 至 W07-10；R-12、R-13 | `/stocks/:ticker` 回占位页 |
| P4-10 | 股票工作区 W07 移动 | P4-09 | W07M-01 至 W07M-04；R-14 | 移动分支回桌面单栏 |
| P4-11 | 可见页刷新与上下文贯穿 | P4-06、P4-09 | REF-01 至 REF-04、CTX-01 至 CTX-03；R-15 | 关闭轮询，保留手动刷新；链接回退 |
| P4-12 | P4 出口验收 | 全部 | 四条出口判据、R-10 至 R-16、性能、bundle | 只增脚本与记录 |

新编号说明：ENV、MKT、STK 是后端测试编号；W08、W08M、W07、W07M、DS、CHT、WB、REF、CTX 是前端测试编号；R-10 至 R-16 是 P4 端到端编号（沿用 P3 的 R 系列，不占用契约编号）；E1 至 E18 是等价清单编号。A01、A04、M01、M06、M07 沿用交互走查编号。

## 3. 依赖顺序

```text
P4-00 拆票
  ├─ P4-01 数据服务内核
  │    ├─ P4-02 市场接口组
  │    │    ├─ P4-05 工作台摘要
  │    │    └─ P4-06 市场看板桌面
  │    │         └─ P4-07 市场看板移动
  │    └─ P4-03 股票接口组
  │         └─ P4-09 股票工作区桌面
  │              └─ P4-10 股票工作区移动
  ├─ P4-04 路由拆包与状态外壳
  │    └─ P4-06 / P4-09 及之后所有前端票
  └─ P4-08 图表组件
       └─ P4-09
P4-06 + P4-09 → P4-11 刷新与上下文 → P4-12 出口
```

- P4-01 必须先完成；P4-02 与 P4-03 可并行，但共用 provider 与缓存设施，建议先 P4-02。
- P4-04 必须早于任何页面票，否则 bundle 预算先被撑破、状态外壳会被各页重复实现。
- P4-08 只依赖夹具，可与 P4-06/P4-07 并行。
- 每票只动自己那一层：P4-01 不接路由，P4-02 不做页面，P4-04 不改页面内容，P4-06 不做股票页，P4-09 不做市场页。

## 4. 逐任务说明

### P4-00 拆票与口径定稿（本对话完成）

目标：把 P4 拆成可独立验收的 13 票，定稿参数、状态、文案、页签、刷新与等价例外。

交付：`docs/upgrade/p4-backlog.md`、`docs/upgrade/P4-01交接卡.md`；在 `P3进度存档.md` 第 6 节加 P4 立项指针。

边界：不写产品代码，不改 `backend/`、`frontend/`、`tradingagents/`、`web/`；不建迁移；不改冻结契约。

验收：预检 10 PASS；`P4-01交接卡.md` 的十项必答齐全；本文件第 1.1 至 1.6 节没有「待定」。

回退：删除两份新文档，还原存档指针。

### P4-01 市场数据服务内核

目标：把信封、缓存、陈旧判定与 provider 注入做成可单测的一层，不接 HTTP。

依赖：P4-00。

涉及文件：

- 新增 `backend/app/services/market_envelope.py`：单块与多块信封构造、合并表、字段约束。
- 新增 `backend/app/services/market_cache.py`：进程内 TTL 缓存、单飞、`stale_after` 表、失败回退。
- 新增 `backend/app/services/market_providers.py`：provider 协议与默认实现（腾讯、东财、同花顺、财联社、百度、mootdx）；只做抓取与解析，不拼信封。
- 新增 `backend/app/services/market_clock.py`：北京时间、交易日与 `market_session` 判定（节假日按「指数日期早于今天 → stale/closed」处理，不引入交易日历表）。
- 新增 `tests/backend/test_market_envelope.py`、`test_market_cache.py`、`test_market_providers.py`。
- 修改 `backend/app/main.py`：只注入 `app.state.market_providers` 与 `market_cache`，不挂新路由。

要求：

- 信封字段与 `market-data-envelope-v1.json` 完全一致；`is_stale` 恒等于 `status=="stale"`。
- 四态约束：`empty`/`error` 时 `data=null`、`as_of=null`；`error` 必须有数据源码；`stale` 必须有 `data`、`as_of`、`stale_reason`。
- 多块合并严格按 `api-v1.md` 3.0；`partial=true` 时 `failed_blocks` 非空。
- `source` 使用 1.4 节的固定值；多源写 `mixed`。
- 缓存键为 `(endpoint_id, 规范化参数)`；同键并发只打一次 provider；provider 超时/限频/解析失败分别映射到四个数据源码。
- 零写盘：provider 不得调用 `web.*`，不得调用会写 CSV/名称表的旧函数；测试对 HOME 与临时目录做前后快照。
- 时间统一 CST（`+08:00`），`fetched_at` 为服务端取数时间。

测试：

- ENV-01：四态字段约束逐条断言。
- ENV-02：多块合并表五行；全 ok、全 empty、全 error、混合、ok/stale 混合。
- ENV-03：缓存命中（不调 provider）、过期重取、失败回退 stale、无旧数据 error。
- ENV-04：20 个并发同键请求只调用 provider 1 次。
- ENV-05：四种 provider 异常到四个错误码的映射。
- ENV-06：GET 路径不创建目录、不写文件；前后目录树与 mtime 快照一致。
- ENV-07：`as_of` / `fetched_at` 格式与 CST 偏移；`YYYY-MM-DD` 与 ISO 时间点两种形态都通过 Schema。
- ENV-08：五份冻结样本 `market_ok/empty/error/stale/partial.json` 能由 builder 重新生成同构信封并通过 Schema。

回退：删除四个服务、三个测试与 `main.py` 的注入；无路由受影响。

验收：`pytest tests/backend/test_market_envelope.py tests/backend/test_market_cache.py tests/backend/test_market_providers.py -q` 全过；预检 10 PASS。

### P4-02 市场接口组

目标：五个市场 GET 按冻结契约返回信封，参数非法给 400，数据源失败给 `empty/error/stale/partial`。

依赖：P4-01。

涉及文件：

- 修改 `backend/app/api/v1/market.py`：新增 `/overview`、`/industries`、`/industries/{board_code}/stocks`、`/strong-stocks`、`/newsflash`；保留 `/search` 行为不变。
- 新增 `backend/app/services/market_service.py`：五个端点的编排与缓存键。
- 新增 `tests/backend/test_market_api.py`、`test_market_service.py`。

要求：

- `overview`：`market_session` 由服务端按北京时间判定；指数固定三大；北向失败只影响北向块。
- `industries`：`top` 1–50 默认 20；`bottom` 与 `top` 等量；行字段齐全。
- 成分股：`boardCode` 校验；停牌价格 null；`limit` 1–100 默认 10。
- 强势股：日期省略取最近交易日；非交易日 `empty`；`reason` 原样返回。
- 快讯：`untrusted=true`；`limit` 1–100 默认 30。
- 所有参数违反 1.3 节 → 400 `invalid_request` 且 `details.field` 正确。
- GET 零写盘、零库写；外部网络只在 provider 层。

测试：

- MKT-01 概览：三指数、北向、`market_session` 四段边界（09:29/09:30/11:30/13:00/15:00/15:01、周末）。
- MKT-02 概览部分成功：北向失败 → `ok` + `partial` + `failed_blocks=["northbound"]`。
- MKT-03 行业：top/bottom/total、领涨股、top 边界 1/50/51。
- MKT-04 成分股：boardCode 非法与不存在、停牌 null、limit 边界。
- MKT-05 强势股：交易日、非交易日 empty、date 非法 400。
- MKT-06 快讯：limit、`untrusted`、字段完整性。
- MKT-07 参数矩阵：每个字段一条 400，`details.field` 与 `allowed_values`。
- MKT-08 零副作用：GET 前后文件树、数据库行数、provider 调用计数符合预期。
- MKT-09 陈旧：指数 11 s、北向 31 s、行业 6 min → `stale` 与对应 `stale_reason`。

回退：删除五个路由与 `market_service.py`；P4-01 保留。

验收：`pytest tests/backend/test_market_api.py -q` 全过；`/api/v1/market/search` 旧用例仍过；预检 10 PASS。

### P4-03 股票接口组

目标：六个股票 GET（快照、K 线、分时、新闻、资金流、股票报告）按冻结契约返回信封；ticker 非法给 400。

依赖：P4-01。

涉及文件：

- 新增 `backend/app/api/v1/stocks.py`：六个 GET；与 `reports.py` 共用 `report_query`，不复制分页逻辑。
- 新增 `backend/app/services/stock_service.py`：三块快照、K 线、分时、新闻、资金流的编排与缓存键。
- 新增 `tests/backend/test_stocks_api.py`、`test_stock_snapshot.py`、`test_stock_kline.py`。
- 修改 `backend/app/main.py`：挂载 `stocks_router`。

要求：

- `snapshot` 三块 `quote / valuation / sector_blocks` + `units`；估值任一字段不可算时为 null，不用 0 冒充。
- `kline`：`adjust="none"`、`period` 三种、`limit` 1–5000、`bars` 升序、`amount` 可为 null。
- `intraday`：默认最近交易日；`session_gaps=[["11:30","13:00"]]`；超保留期 `empty`。
- `news`：纯文本字段 + `untrusted=true`。
- `fund-flow`：五路净额、升序、单位元。
- `stocks/{ticker}/reports`：与 `/reports?ticker=` 同构，复用 `report_query` 与游标。
- ticker 校验按 1.3 节；名称表不可用 500。

测试：

- STK-01 快照三块 ok、字段与旧 `tencent_quote` 键一致、units。
- STK-02 快照部分成功：估值失败 → `ok` + `partial` + `failed_blocks=["valuation"]`。
- STK-03 快照全失败 → `error` + 数据源码。
- STK-04 K 线三周期、limit、升序、`adjust`、`amount` null。
- STK-05 分时默认日期、非交易日回退、`session_gaps`、超保留期 empty。
- STK-06 新闻字段、`untrusted`、limit 边界。
- STK-07 资金流五路、升序、单位。
- STK-08 股票报告与 `/reports?ticker=` 同构、游标、空页。
- STK-09 ticker 格式/不存在/名称表不可用三条分支。
- STK-10 零副作用 + 七条陈旧阈值（行情 60 s、估值 4 h、板块 24 h、K 5 min、分时 30 s/1 h、新闻 5 min、资金流 60 s）。

回退：删除 `stocks.py`、`stock_service.py` 与三个测试，去掉 `main.py` 挂载；报告接口不受影响。

验收：`pytest tests/backend/test_stocks_api.py tests/backend/test_stock_snapshot.py tests/backend/test_stock_kline.py -q` 全过；预检 10 PASS。

### P4-04 路由拆包与数据状态外壳

目标：前端在页面开工前解决 bundle 预算与状态一致性，避免每页各写一套空/错/旧态。

依赖：P4-00。

涉及文件：

- 修改 `frontend/src/routes.tsx`、`frontend/src/App.tsx`：页面改 `React.lazy` + `Suspense`，按路由分块。
- 新增 `frontend/src/ui/DataState.tsx`、`StaleBanner.tsx`、`PartialNotice.tsx`。
- 新增 `frontend/src/features/market/copy.ts`（状态、来源、会话文案）。
- 修改 `frontend/src/api/market.ts`、`api/types.ts`：信封类型与现有端点类型。
- 修改 `frontend/src/lib/query.ts`：P4 查询键与 `staleTime`。
- 新增组件测试与 bundle 断言。

要求：

- `DataState` 五态 + `partial` 修饰；loading 骨架与最终高度差 ≤8px；error 有重试；empty/error 文案与 testid 不同；stale 横幅按 reason 显示。
- 所有页面共用一个 copy 源；组件不硬编码中文状态词。
- 拆包后入口 chunk ≤202.45 kB gzip，单块 ≤60 kB；P2/P3 E2E 与 bundle 回归同过。
- `Suspense` fallback 使用与页面首屏一致的骨架，不出现空白闪烁。

测试：

- DS-01 五态渲染与文案/ testid 差异。
- DS-02 partial 修饰 + 块名列表。
- DS-03 stale 三种 reason 的文案。
- DS-04 骨架与内容高度差（jsdom 用固定尺寸断言）。
- DS-05 error 重试只回调一次。
- DS-06 语义：loading `aria-busy`、error `role="alert"`、stale `role="status"`。
- DS-07 路由懒加载：只进入 `/market` 时才出现对应 chunk。
- DS-08 bundle：入口与各懒加载块 gzip 数字写证据 JSON。

回退：还原静态 import 与 `routes.tsx`；删除新组件与测试；页面功能不受影响。

验收：`node node_modules/vitest/vitest.mjs run`、`tsc --noEmit`、`vite build` 全过；入口 gzip 不高于 202.45 kB；P2/P3 E2E 0 failures。

### P4-05 工作台摘要补全

目标：补上 P2 留到 P3、P3 未接的「最近报告」，并把「市场概览」占位换成精简摘要。

依赖：P4-02；P3 报告接口。

涉及文件：

- 新增 `frontend/src/features/workbench/MarketSummary.tsx`、`RecentReports.tsx`。
- 修改 `frontend/src/features/workbench/WorkbenchPage.tsx`：替换两处占位与过时文案。
- 修改 `frontend/src/api/reports.ts`（如需 `limit=3` 类型）与 `lib/query.ts`。
- 新增组件测试；更新 `e2e/workbench_e2e.py`。

要求：

- 最近报告：`GET /api/v1/reports?limit=3`，行显示股票、分析日期、评级、生成时间；点击进阅读器；空/错态；移动端默认收起。
- 市场摘要：三大指数 + 行业前 3 + 强势股前 3；四态；点击股票进 `/stocks/:ticker`，点击「查看市场」进 `/market`。
- 最近研究股票：从最近报告的去重 ticker 生成，不新增接口；没有报告时不显示。
- 工作台打开零 `POST`、零额外行情请求（摘要只读）。
- 移除「将在 P3/P4 接入」字样。

测试：

- WB-01 最近报告 3 条、点击进阅读器、空/错态、移动折叠。
- WB-02 市场摘要三块、四态、点击钻取。
- WB-03 44px 与移动折叠。
- WB-04 打开工作台零 `POST`，请求集合只含工作台所需 GET。

回退：工作台恢复两处占位；删除两个组件。

验收：组件测试全过；`e2e/workbench_e2e.py` 0 failures；预检 10 PASS。

### P4-06 市场看板 W08 桌面

目标：桌面市场页按 W08 形态落地，钻取与返回现场可用。

依赖：P4-02、P4-04。

涉及文件：

- 新增 `frontend/src/features/market/MarketPage.tsx`、`MarketSessionBar.tsx`、`IndexCards.tsx`、`IndustryTable.tsx`、`ConstituentDrawer.tsx`、`StrongStocksTable.tsx`、`NewsflashList.tsx`、`marketParams.ts`。
- 替换 `frontend/src/pages/MarketPage.tsx` 为路由转出壳，保留 `page-market`。
- 新增组件测试与 `e2e/market_e2e.py`。

要求：

- 市场状态条：`market_session` 中文 + 最近更新时间。
- 指数三卡：价格、涨跌幅、数据时间、来源。
- 行业：涨幅前 20 与末位若干；点击行开右侧抽屉（前 10 成分股）；点成分股进 `/stocks/:ticker?tab=valuation`。
- 强势股：表格；非交易日「非交易日或盘后未更新」；题材 TOP8 由 `reason` 前端聚合，点击只筛当前列表。
- 快讯：纯文本列表，外链新窗口 + `rel="noopener noreferrer"`。
- 状态：每块独立 `DataState`；partial 标块名；stale 横幅。
- URL：`top`、`date`、`board`、`theme` 写进 query；非法/越界回默认，不改写路径。
- 返回：从股票回市场恢复行业、topN、强势日期、抽屉与滚动（点击捕获 + popstate，刷新回顶部）。

测试：

- W08-01 会话条、指数卡、来源与时间。
- W08-02 行业 top/bottom、领涨、涨跌家数。
- W08-03 抽屉成分股、钻取到股票、tab=valuation。
- W08-04 强势股表格、非交易日文案、题材聚合与本地筛选。
- W08-05 快讯纯文本与外链属性。
- W08-06 四态 + partial + stale。
- W08-07 query 状态与非法值回默认。
- W08-08 返回恢复 5 项（行业、topN、日期、抽屉、滚动）。

回退：`/market` 回占位页，删除 `features/market/` 组件；后端保留。

验收：组件测试全过；`e2e/market_e2e.py` R-10/R-11 0 failures；桌面 1440 无控制台错误。

### P4-07 市场看板 W08 移动

目标：≤767 下指数横滑、行业与强势股卡片、成分股全屏覆盖层，无页面横向溢出。

依赖：P4-06。

涉及文件：

- 新增移动分支组件（可放在 `features/market/mobile/`）与全屏 `BoardStocksDialog`。
- 补充组件测试；扩展 `e2e/market_e2e.py` 的 390×844 与 360×800。

要求：

- 指数区容器内横滑，页面本身不横滑。
- 行业与强势股用卡片，不渲染 `<table>`（M06）。
- 成分股全屏二级层（`board` query），点股票进 W07；关闭/返回恢复原滚动。
- 触控目标 ≥44px；`scrollWidth === clientWidth`（M07）。

测试：

- W08M-01 390/360 指数横滑。
- W08M-02 行业/强势卡片，无 table。
- W08M-03 全屏成分股开合与返回。
- W08M-04 44px 与无页面级横向溢出。

回退：移动分支回桌面单栏；保留 query 状态。

验收：两档视口 0 failures；无控制台错误。

### P4-08 K 线与分时图表

目标：不新增依赖的前提下，把 K 线与分时的交互做完整，供 W07 使用。

依赖：P4-00（只依赖夹具与类型）。

涉及文件：

- 新增 `frontend/src/features/charts/KLineChart.tsx`、`IntradayChart.tsx`、`chartScale.ts`、`chartCrosshair.ts`。
- 新增组件测试与固定 bar 夹具。
- 样式与图表容器（容器内横向滚动）。

要求：

- K 线：蜡烛 + 成交量副图；日/周/月切换；滚轮/拖拽缩放与平移；十字光标读数；图例开关；数据时间；不复权标注。
- 分时：价格线 + 均价线 + 成交量；午休断线；空态；单点数据不崩。
- 移动：周期按钮 ≥44px；图表容器内滚动，页面不横滑。
- 数据缺失（`amount=null`、空 `bars`）有明确空态，不画假点。
- 无 canvas 也可以被 jsdom 断言：用 SVG 的 `data-*` 标记几何与状态。

测试：

- CHT-01 价格/成交量坐标映射。
- CHT-02 周期切换重算。
- CHT-03 缩放与平移边界（最早/最晚不越界）。
- CHT-04 十字光标读数与吸附。
- CHT-05 图例开关。
- CHT-06 午休断线与均价线。
- CHT-07 空/单点/缺 amount。
- CHT-08 容器内滚动、页面无溢出。

回退：删除图表组件；W07 对应页签显示占位。

验收：组件测试全过；图表在 1440 与 390 下可操作；bundle 单块 ≤60 kB。

### P4-09 股票工作区 W07 桌面

目标：固定头部 + 五页签，把快照、估值、K 线、分时、新闻、报告串起来，并接上分析与活动任务入口。

依赖：P4-03、P4-04、P4-08。

涉及文件：

- 新增 `frontend/src/features/stocks/StockPage.tsx`、`StockHeader.tsx`、`StockTabs.tsx`、`ValuationTab.tsx`、`KLineTab.tsx`、`IntradayTab.tsx`、`NewsTab.tsx`、`ReportsTab.tsx`、`stockParams.ts`、`useStockActions.ts`。
- 替换 `frontend/src/pages/StockPage.tsx` 为路由转出壳，保留 `page-stock`；格式非法的 ticker 仍走 `InvalidTickerPage`。
- 修改 `frontend/src/api/market.ts`、`lib/query.ts`；新增 `e2e/stock_e2e.py`。

要求：

- 头部：名称+代码、市场、现价、涨跌幅、来源、数据时间；stale 横幅。
- 主操作：无活动任务时「分析这只股票」打开启动器并预填；有活动任务时主按钮改「查看进行中任务」，跳 `/jobs/:id`；「查看最新报告」跳 `/reports?ticker=`；「查看该股票任务」跳 `/jobs?ticker=`。
- 估值 tab：价格/PE/PB/市值/换手/成交额、EPS 一致预期、动态 PE、PEG、消化年数、行业/概念/地域、资金流；缺失显示「—」并注明不可得。
- K 线 tab：图表 + 周期按钮 + 不复权标注 + 数据时间。
- 分时 tab：日期选择、午休断线、超保留期 empty 文案。
- 新闻 tab：纯文本、来源、时间、外链新窗口。
- 报告 tab：`GET /stocks/{ticker}/reports`，点击进阅读器；空/错态。
- tab、`period`、`date` 进 query；刷新恢复；非法 tab 回 valuation，非法 period 回 day，非法分时日期回最近交易日（不 400）。
- 每个 tab 独立滚动位置；刷新后 tab 内回顶部。
- 6 位但名称表没有的 ticker → 400 页「没有这只股票」，给搜索框与回市场。

测试：

- W07-01 头部字段、来源/时间、stale 横幅。
- W07-02 两种主按钮状态与跳转。
- W07-03 估值缺失「—」、板块三组、资金流。
- W07-04 K 线周期与不复权标注。
- W07-05 分时日期、断线、empty。
- W07-06 新闻纯文本与外链。
- W07-07 报告列表、进阅读器、空/错。
- W07-08 深链与刷新恢复、非法值回默认。
- W07-09 格式非法与不存在 ticker 的 400 页。
- W07-10 部分失败：估值失败时行情仍显示，块名可见。

回退：`/stocks/:ticker` 回占位页；删除 `features/stocks/`；后端保留。

验收：组件测试全过；`e2e/stock_e2e.py` R-12/R-13 0 failures；桌面 1440 无控制台错误。

### P4-10 股票工作区 W07 移动

目标：≤767 下页签横滑、吸底分析条、图表可操作，无页面横向溢出。

依赖：P4-09。

涉及文件：

- 移动分支组件与样式；吸底条；图表移动包装。
- 扩展 `e2e/stock_e2e.py` 的 390×844 与 360×800。

要求：

- 页签容器内横滑，页面不横滑。
- 「分析这只股票」吸底，位于底部导航之上（`bottom = 56px + env(safe-area-inset-bottom)`），44px。
- K 线与分时用周期按钮，不依赖精细手势；图表容器内横向滚动。
- 决策/估值卡不撑破页面。

测试：

- W07M-01 页签横滑与 44px。
- W07M-02 吸底条位置与按钮可见。
- W07M-03 图表容器滚动与周期按钮。
- W07M-04 360/390 无页面横向溢出。

回退：移动分支回桌面单栏；保留深链。

验收：两档视口 0 failures；无控制台错误。

### P4-11 可见页刷新与上下文贯穿

目标：把轮询、降频、手动刷新与跨页股票上下文收口到一套实现，避免各页各写。

依赖：P4-06、P4-09。

涉及文件：

- 新增 `frontend/src/lib/useVisibleRefetch.ts`、`useDebouncedRefresh.ts`。
- 修改市场页与股票页的查询配置；修改阅读器、任务页的股票链接。
- 新增组件测试；扩展 E2E。

要求：

- 轮询只挂在可见页面；`document.hidden` 时 60 s，回前台立即按 query 失效重取。
- 手动刷新 500 ms 防抖；一次点击只发一组请求；继续走服务端缓存约束。
- 页面切换或离开立即清定时器；无重复请求。
- 上下文：市场→股票保留行业/topN/日期；股票→报告→返回股票；报告与任务页的 ticker 可点回股票；活动任务按钮直达任务详情。
- 不因轮询产生 `POST`、不创建任务、不生成 PDF。

测试：

- REF-01 可见页轮询间隔（指数 10 s、行情 60 s 用假表断言）。
- REF-02 隐藏降频与回前台立即重取。
- REF-03 手动刷新防抖，一次只发一组。
- REF-04 切页停表、无重复请求。
- CTX-01 市场→股票→返回恢复。
- CTX-02 股票→报告→返回股票；报告→股票链接。
- CTX-03 股票→任务；活动任务按钮。

回退：关闭轮询与降频 hook，保留手动刷新；上下文链接回退为普通文本。

验收：组件测试全过；R-15 0 failures；预检 10 PASS。

### P4-12 P4 出口验收

目标：四条出口判据逐条取证，一条命令复跑。

依赖：全部。

交付：

- 新增 `e2e/e2e_p4.py`：构建、preview、后端夹具、R-10 至 R-16、bundle、性能与等价清单检查。
- 新增 `scripts/p4_market_perf.py`：`--fixture`（CI）与 `--live`（人工，记录时间与网络）。
- 新增 `docs/upgrade/reviews/2026-11-XX_P4出口评审.md`、`2026-11-XX_P4-12性能结果.json`、`2026-11-XX_P4等价清单.md`。

要求：

- 只增测试与记录，不改产品行为；发现缺陷退回对应票修。
- 等价清单按 1.5 节逐项打勾；例外必须写明原因与影响。
- 出口脚本任一套失败即非零退出。

验收：见第 6 节。

## 5. 测试与证据口径

### 5.1 后端

| 编号 | 范围 | 期望 |
| --- | --- | --- |
| ENV-01 至 ENV-08 | 信封、缓存、provider、零写盘 | 全部通过 |
| MKT-01 至 MKT-09 | 市场五个端点、参数、状态、陈旧 | 全部通过 |
| STK-01 至 STK-10 | 股票六个端点、三块快照、参数、ticker | 全部通过 |
| 回归 | `pytest tests/backend -q` | 不倒退；新增用例全绿 |

### 5.2 前端

| 编号 | 范围 |
| --- | --- |
| DS-01 至 DS-08 | 状态外壳与拆包 |
| W08-01 至 W08-08 | 市场桌面 |
| W08M-01 至 W08M-04 | 市场移动 |
| CHT-01 至 CHT-08 | 图表 |
| W07-01 至 W07-10 | 股票桌面 |
| W07M-01 至 W07M-04 | 股票移动 |
| WB-01 至 WB-04 | 工作台摘要 |
| REF-01 至 REF-04、CTX-01 至 CTX-03 | 刷新与上下文 |

### 5.3 端到端

| 编号 | 场景 | 归属 |
| --- | --- | --- |
| R-10 | 市场看板：会话条、指数、行业、强势股、快讯与四态 | P4-06 |
| R-11 | 市场钻取：行业→成分股→股票→返回恢复 5 项 | P4-06 |
| R-12 | 股票工作区：五 tab、深链、刷新、非法 ticker 400 | P4-09 |
| R-13 | 股票↔报告/任务：上下文与活动任务按钮 | P4-09/P4-11 |
| R-14 | 390×844 与 360×800：市场与股票移动形态、无溢出 | P4-07/P4-10 |
| R-15 | 刷新策略：可见轮询、隐藏降频、手动防抖、切页停表 | P4-11 |
| R-16 | 部分成功与陈旧在浏览器中的可见差异 | P4-06/P4-09 |

### 5.4 性能

| 指标 | 硬线 | 测法 |
| --- | --- | --- |
| 股票快照暖缓存 p95 | ≤1.5 s | `p4_market_perf.py --live`，30 样本；`--fixture` 只验逻辑 |
| 正常供应商冷加载 p95 | ≤4 s | 同上；单块失败不阻塞其他块 |
| 缓存命中路由切换 p95 | ≤300 ms | 构建产物 + 固定服务器时间，Playwright 导航 |
| 首屏入口 chunk | ≤202.45 kB gzip | P4-04 与 P4-12 测量 |
| 单个新路由 chunk | ≤60 kB gzip | 同上 |
| 外部网络调用（测试） | 0 | provider 注入计数 |

LCP、CLS、INP 与 axe 全量检查留到 P6 性能与 P5 可访问性；P4 只记录不设出口门槛。

### 5.5 数据与证据

- 市场测试只用 `tests/fixtures/upgrade/market_*.json` 与假 provider；不读真实 HOME，不联网。
- 分时、K 线用固定 bar 夹具；不提交行情数据文件。
- 每条证据写测试编号、命令、输出摘要、提交号；没有证据写「未通过」，不写「基本通过」。
- 截图放 `ui_shots_p4/<票号>/`，不入库。

## 6. P4 出口判据

P4 完成必须同时满足：

1. 与旧看板逐项等价：第 1.5 节 E1 至 E18 全部有对应实现或书面例外；例外不得新增假数据。
2. 错误、空、陈旧、部分成功可区分：接口信封四态与 `partial` 正确；界面 empty 与 error 文案不同，stale 显示原因，partial 标出失败块。
3. 市场→股票→返回保留上下文：行业、topN、强势日期、tab、K 线周期、分时日期、抽屉与滚动按 `routes.md` 恢复；刷新可重建身份，非法值按 1.3/1.6 回默认。
4. 移动可操作：390/360 无页面级横向溢出；触控 ≥44px；图表容器内滚动；页签横滑；快照暖缓存 p95 ≤1.5 s、冷加载 p95 ≤4 s、路由切换 p95 ≤300 ms。

门禁：预检 10 PASS；Python 全量不倒退；前端单元、`tsc`、`vite build` 全过；R-10 至 R-16 0 failures；入口 chunk ≤202.45 kB；旧版冒烟 ok；无新增迁移。

## 7. 与冻结契约的对应

| 实现面 | 契约 |
| --- | --- |
| 搜索、快照、K 线、分时、新闻、股票报告、概览、行业、成分股、强势股、资金流、快讯 | `api-v1.md` 3.1 至 3.6 |
| 信封四态、`partial`、`stale_reason`、新鲜度阈值、多块合并 | `market-data-envelope-v1.json`；`api-v1.md` 3.0 |
| 市场路由、返回、深链、刷新、非法 ticker | `routes.md` 第 1 至 3 节 |
| W07 股票工作区、W08 市场与钻取 | `core-wireframes.md` 第 7、8 节 |
| M01、M06、M07、A01、A04 | `interaction-checklist.md` |
| `invalid_request`、数据源四码 | `error-codes-v1.md` 第 1、4 节 |
| 冻结与解冻 | `FREEZE-v1.md` 第 4 节 |

## 8. 留给后续阶段

| 内容 | 阶段 | P4 的处理 |
| --- | --- | --- |
| 生成日期筛选、`signal` 筛选（P3 的 O4） | 单独解冻票或 P5 | P4 不做：它改的是 `/reports` 参数，与市场票不同层；需要解冻票先改契约与测试 |
| 北向 20 日历史 | P5/P6 或解冻 | 见 C4；P4 只做当日 points 与 latest |
| 旧 K 线周期（单日/5日/30日/全部） | 解冻后再说 | 见 C5；P4 按 v1 的 day/week/month |
| 数据源降级提示（`provider`/`warning` 字段） | P6 或解冻 | 见 D11；P4 只用 `source` + `stale_reason` |
| 投影失败的 UI 警告（P3 的 O1） | P6 或解冻 | 不在 P4 范围 |
| 导出产物清理与图表快照（P3 的 O3、O5） | P6 | 不在 P4 范围 |
| 交易日志、设置、主题与可访问性收尾 | P5 | 占位页保持 |
| 默认入口切换、双栈灰度、真实回滚演练 | P6 | 旧版仍是默认写入口 |
| LCP、CLS、INP 与 axe 全量门禁 | P6/P5 | P4 只记录性能原值，不设出口门槛 |
| 全市场题材检索 | 未来或解冻 | 见 C6；P4 只做已加载强势股的题材筛选 |
