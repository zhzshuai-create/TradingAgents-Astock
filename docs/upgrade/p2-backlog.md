# P2 任务拆票：React 外壳与分析任务中心

版本：v1（2026-11-05）
上游：`reviews/2026-11-05_P1出口判据验收.md` 结论为 Go。
依据：`AStock_Pro_专业投研工作台全面升级计划_2026-10-28.md` 第九节 P2 行；`contracts/core-wireframes.md` 的 W01 至 W04；`contracts/routes.md`；`contracts/interaction-checklist.md` 的 A01 至 A10、A14 与 M01 至 M03、M06 至 M07。
用途：把 P2 拆成可以独立验收的 13 个任务。每个任务单独提交、单独回退、单独跑测试。

P2 只做「外壳 + 分析任务中心」：工作台、统一启动器、任务列表、任务详情、跨页任务入口。报告库（W05、W06）、股票工作区（W07）、市场（W08）、日志（W09）、设置（W10）留给 P3 至 P5，本阶段只放占位页与路由。

## 0. 公共约束

- 技术选型固定，不在票内更换：
  - React 19 + TypeScript + Vite，包管理用 npm，提交 `package-lock.json`。
  - 路由用 React Router；服务端状态用 TanStack Query；不引入 Redux、axios、Ant Design 或 Tailwind。
  - 样式用 CSS Modules + CSS 变量；设计令牌集中在 `frontend/src/styles/tokens.css`。
  - 阶段报告用 `react-markdown` 渲染，开启 `skipHtml`，禁止原始 HTML。
  - 组件测试用 Vitest + Testing Library + MSW；端到端用全局 Python 3.13 的 Playwright + Chromium（与 P0 线框截图同一套环境）。
- 后端只补冻结契约里已经存在、P1 尚未实现的三条接口：`GET /api/v1/jobs`、`GET /api/v1/meta/options`、`GET /api/v1/market/search`。字段与错误码照 `api-v1.md`，不新增状态名、事件名或错误码。
- 不改 `tradingagents/`、`web/`、`run_all.bat` 与旧版 8501 入口。旧版仍是默认写入口，新前端不接管默认启动。
- 全部端到端测试使用假图、临时 `TA_JOBS_DB` 与 `TA_JOB_REPORTS_DIR`；不联网、不调用真实模型、不读取 API Key、不写 `~/.tradingagents`。
- 一票一提交，只留本地，不推送远端；提交说明写测试编号、命令、结果与回退方式。
- 每个任务完成后旧版 Streamlit 必须仍能启动，健康检查 ok。

## 1. 任务总表

| 编号 | 任务 | 依赖 | 主要验收编号 | 独立回退方式 |
| --- | --- | --- | --- | --- |
| P2-01 | 前端工程、设计令牌与开发入口 | 无 | WEB-01、WEB-02、DEV-01 至 DEV-03 | 删除 `frontend/` 与 `scripts/dev_backend.py` |
| P2-02 | 响应式外壳与九条路由 | P2-01 | E2E-01、E2E-02、WEB-03 | 删除 `frontend/src/shell/` 与 `routes.tsx` |
| P2-03 | 股票目录、搜索与任务投影 | P2-01（后端可独立） | SRCH-01 至 SRCH-05、PRJ-01 至 PRJ-03 | 下线 `/market/search` 与名称回填 |
| P2-04 | 任务列表与元信息接口 | P2-03 | LST-01 至 LST-06、META-01 至 META-05 | 下线 `/jobs` 列表与 `/meta/options` |
| P2-05 | 前端 API 客户端与错误映射 | P2-02、P2-04 | WEB-04 至 WEB-06 | 删除 `frontend/src/api/`，页面回占位 |
| P2-06 | 全局搜索与活动任务条 | P2-05 | WEB-07、E2E-07 | 删除 `SearchBox` 与 `ActiveJobBar` |
| P2-07 | 工作台首页 W01 | P2-06 | E2E-03、WEB-08 | 工作台回占位页 |
| P2-08 | 统一分析启动器 W02 | P2-07 | A01 至 A03、WEB-09 | 删除 `features/launcher/`，入口回空态 |
| P2-09 | 任务列表页 W03 | P2-04、P2-05 | E2E-04、M06、WEB-10 | 任务路由回占位 |
| P2-10 | 任务详情页 W04 静态与阶段报告 | P2-05 | E2E-05、WEB-11 | 详情路由回占位 |
| P2-11 | 任务详情 SSE 与重连 | P2-10 | A05、A06、WEB-12 | 关闭订阅，详情退化为手动刷新 |
| P2-12 | 暂停、取消、重试与续跑 | P2-11 | A07 至 A10、WEB-13 | 隐藏按钮，只按 allowed_actions 只读展示 |
| P2-13（已完成） | P2 出口验收与性能补测 | P2-12 | E2E 全量、M01 至 M03、M06 至 M07、P05-UI | 只增测试与记录，不改产品行为 |

P2-01 至 P2-13 全部完成，出口评审结论为 Go，证据见 `reviews/2026-11-05_P2出口评审.md`。P2-13 唯一的产品改动是 A14 的列表滚动与分页恢复，理由与回退在该评审第 3 节。

表里的 A01 至 A10、A14 与 M01 至 M03、M06 至 M07 来自冻结的交互走查清单，沿用原编号。WEB、E2E、DEV、SRCH、PRJ、LST、META 是本阶段新增的测试编号，不占用契约编号。

## 2. 依赖顺序

```text
P2-01 工程与令牌
  ├─ P2-02 外壳与路由
  │    └─ P2-05 API 客户端
  │         ├─ P2-06 搜索与任务条
  │         │    └─ P2-07 工作台 W01
  │         │         └─ P2-08 启动器 W02
  │         ├─ P2-09 任务列表 W03
  │         └─ P2-10 任务详情 W04
  │              └─ P2-11 SSE
  │                   └─ P2-12 控制与重试
  │                        └─ P2-13 出口验收
  └─ P2-03 股票目录与搜索接口
       └─ P2-04 任务列表与元信息接口
            └─ P2-05
```

实际执行按编号 01 到 13。P2-03 与 P2-04 是纯后端，可以在 P2-02 期间并行推进；P2-05 必须等 P2-04 完成后再接真实接口。

## 3. 逐任务说明

### P2-01 前端工程、设计令牌与开发入口

目标：让新前端能本地跑起来，并有一个能同时拉起 API 与 Worker 的开发入口。

依赖：无。

涉及文件：

- 新增 `frontend/package.json`、`package-lock.json`、`tsconfig.json`、`vite.config.ts`、`index.html`。
- 新增 `frontend/src/main.tsx`、`frontend/src/App.tsx`、`frontend/src/styles/tokens.css`、`global.css`。
- 新增 `frontend/src/ui/`：Button、Badge、Dialog、Drawer、Skeleton、EmptyState、Toast。
- 新增 `scripts/dev_backend.py`：用 `create_app()` 起 uvicorn，同一进程起 Worker；`--no-worker`、`--port`、`--stage-delay-ms`、`--ticker-fixture` 四个开关。`--ticker-fixture` 给端到端测试注入离线的股票名称表。
- 修改 `pyproject.toml` 与 `constraints.txt`：backend extra 声明并锁定 `uvicorn`。
- 新增 `tests/backend/test_dev_entry.py`。

要求：

- 令牌覆盖颜色（亮/暗）、字号、行高、间距、圆角、阴影、动效、层级与断点；页面不写裸色值。
- 组件只用语义令牌，不直接引用基础色阶。
- `dev_backend.py` 的 Worker 必须拿到与 API 相同的 `ReportStore` 和 `JobService`，不能另建一套。
- `--stage-delay-ms` 只用于端到端测试放慢阶段边界，默认 0；不得改假图模块。

测试：

- WEB-01：`npm ci && npm run build` 通过；令牌文件包含颜色、间距、字号、圆角、断点五组；`frontend/src` 除 `tokens.css` 外不出现十六进制色值。
- WEB-02：四个 UI 组件能渲染；Dialog 与 Drawer 打开后焦点进入容器，Esc 关闭并还原焦点。
- DEV-01：临时库启动入口，`POST /api/v1/jobs` 后任务跑到 succeeded，12 个阶段文件齐全，SIGINT 后进程干净退出。
- DEV-02：入口只写临时目录，不创建、不修改 `~/.tradingagents/jobs.db` 与默认报告根目录。
- DEV-03：`--no-worker` 时任务停在 queued，不被认领；恢复 Worker 后继续执行。

回退：删除 `frontend/`、`scripts/dev_backend.py` 与对应测试。后端行为不变。

验收：前端构建通过；开发入口能完成一次假图任务；旧版健康检查 ok。

### P2-02 响应式外壳与九条路由

目标：先定「从哪来、回哪去」，再填页面内容。

依赖：P2-01。

涉及文件：

- 新增 `frontend/src/shell/AppShell.tsx`、`Sidebar.tsx`、`TopBar.tsx`、`MobileNav.tsx`。
- 新增 `frontend/src/routes.tsx`、`frontend/src/pages/Placeholder.tsx`、`NotFoundPage.tsx`、`InvalidTickerPage.tsx`。
- 新增 `frontend/src/shell/AppShell.test.tsx`。

要求：

- 桌面：左侧导航可折叠（232px / 72px），顶栏含全局搜索位、活动任务位、主题切换、服务状态位（P2-04 接真实值）；内容区独立滚动。
- 移动：顶部标题加搜索，底部五导航（工作台/市场/任务/报告/更多），更多里放日志、设置、旧版入口。
- 九条路由全部可直达：`/workbench`、`/market`、`/stocks/:ticker`、`/jobs`、`/jobs/:jobId`、`/reports`、`/reports/:reportId`、`/journal`、`/settings`。
- 未知路由给 404，两个出口：回工作台、回任务列表；不自动跳转。
- 非法 ticker 给 400 页，文案「没有这只股票」，给搜索框与回市场。
- P3 至 P5 的页面先渲染带页面名的占位页，不伪造数据。

测试：

- WEB-03：九条路由匹配；未知路由 404；侧栏与底栏当前项高亮；非法 ticker 渲染 400 页。
- E2E-01：桌面 1440 与移动 390 各走一遍导航；404 两个出口可用；九条深链接直接打开都渲染对应页面。
- E2E-02：390 与 360 下 `documentElement.scrollWidth == clientWidth`；导航项与主按钮高度不小于 44px；底部导航留 `env(safe-area-inset-bottom)`。

回退：删除外壳与路由文件，`App.tsx` 回单一占位页。不影响旧版。

验收：E2E-01、E2E-02 通过；360px 无页面级横向滚动。

### P2-03 股票目录、搜索与任务投影

目标：给搜索与列表提供股票名称，并补齐 `JobSummary` 投影。

依赖：P2-01（后端可独立开工）。

涉及文件：

- 新增 `backend/app/services/ticker_directory.py`：名称索引、`search(q, limit)`、`name(code)`，数据源通过构造参数注入。
- 新增 `backend/app/api/v1/market.py`：`GET /api/v1/market/search`。
- 修改 `backend/app/api/v1/serializers.py`：新增 `job_summary()`，`job_detail()` 接受可选名称覆盖。
- 新增 `tests/backend/test_market_search.py`、`tests/backend/test_job_projection.py`。

要求：

- 搜索返回 `{items: [{ticker_code, ticker_name, market}], truncated}`，按代码精确命中优先、名称前缀次之、名称包含最后；`market` 按代码前缀判定 sh/sz/bj。
- 契约未给搜索的条数上限，本阶段默认 10、超过 50 按 50 截断；这是一处契约空白，写进提交说明，要改先走解冻流程。
- `q` 为空返回 `empty` 信封，不报错；多命中如实列出，不做消歧。
- 数据源失败返回 200 信封 `status = error` 加 `upstream_error` 或 `upstream_timeout`，不返回 500。
- 名称索引默认读 mootdx 的按日磁盘缓存；不可用时返回 null，不阻塞任务读取，也不在请求里同步拉全市场。
- `job_summary` 与 `job_detail` 字段一致，只去掉 `stages`；`ticker_name` 为空时用目录补，目录也解析不到就保持 null。

测试：

- SRCH-01：代码、完整名称、部分名称三种命中；`truncated` 正确。
- SRCH-02：空查询返回 empty；多候选按规则排序。
- SRCH-03：注入的数据源抛错时返回 `upstream_error`，HTTP 200。
- SRCH-04：搜索零副作用，不建库、不写事件。
- SRCH-05：`limit` 默认 10、最大 50；越界按上限截断。
- PRJ-01：`job_summary` 不含 `stages`，其余字段与 `job_detail` 逐项相等。
- PRJ-02：`ticker_name` 为空且目录可解析时回填；目录失败时保持 null。
- PRJ-03：投影不写库、不改 `updated_at`。

回退：下线 `/market/search` 路由，`ticker_name` 回退为库内值。任务读写不受影响。

验收：搜索三类命中与失败信封正确；`JobSummary` 与契约一致。

### P2-04 任务列表与元信息接口

目标：实现活动任务条与启动器依赖的两条只读接口。

依赖：P2-03。

涉及文件：

- 修改 `backend/app/api/v1/jobs.py`：新增 `GET /api/v1/jobs` 列表路由。
- 新增 `backend/app/api/v1/meta.py`：`GET /api/v1/meta/options`。
- 新增 `backend/app/core/journal_probe.py`：日志服务 TCP 探活，可注入。
- 修改 `backend/app/services/job_service.py`：只读 `list_jobs()` 与游标查询。
- 新增 `tests/backend/test_jobs_list.py`、`tests/backend/test_meta_options.py`。

要求：

- 列表支持 `status` 多值、`ticker`、`date_from`、`date_to`、`active`、`limit`、`cursor`；`active=true` 与 `status` 同时出现返回 400 `invalid_request`，`details.field = "active"`。
- 排序固定 `created_at` 倒序、同秒按 `job_id` 升序；游标是 `created_at + job_id` 的不透明编码，翻页不重不漏。
- `limit` 默认 20，超过 100 按 100 截断；非法游标返回 400 `invalid_request`；日期非法或晚于今天返回 422 `invalid_date`。
- 列表零副作用：不触发对账、不改状态、不发事件、不创建任务。
- 响应带 `ticker_name`（能为空）与 `links`。
- `meta/options` 返回 `app_version`、`server_time`（`+08:00`）、`default_analysis_date`（按北京时间）、`llm_profiles`、`stage_toggles`、`limits`、`journal`、`contract_version`。
- 日志探活只做 TCP 连接与身份校验，超时 300ms；三种原因 `not_running`、`not_installed`、`probe_failed` 如实返回，不自动拉起日志服务。
- `meta/options` 不泄露密钥、环境变量或绝对路径。

测试：

- LST-01：默认 20 条，排序稳定。
- LST-02：`active` 与 `status` 互斥；`active=true` 只返回五个非终态。
- LST-03：股票与日期闭区间筛选正确。
- LST-04：游标两页无重复、无遗漏；同秒创建的多条顺序稳定。
- LST-05：调用前后任务、阶段、事件行数不变，`updated_at` 不变。
- LST-06：`limit` 截断、非法游标 400、非法日期 422。
- META-01：字段齐全，`server_time` 带 `+08:00`，默认日期按北京时间。
- META-02：三种日志原因与 available 分支；探活失败不影响主响应。
- META-03：零副作用，反复调用行数不变。
- META-04：`llm_profiles` 与 `stage_toggles` 来自服务端配置，不被请求参数覆盖。
- META-05：响应不含密钥、Token、绝对路径。

回退：下线两条路由，活动任务条与启动器改用静态占位。任务内核不受影响。

验收：两条接口通过契约字段断言；列表翻页稳定；探活不拉起外部服务。

### P2-05 前端 API 客户端与错误映射

目标：页面只通过一个类型化客户端读写 API，错误文案不散落在组件里。

依赖：P2-02、P2-04。

涉及文件：

- 新增 `frontend/src/api/client.ts`、`types.ts`、`errors.ts`、`jobs.ts`、`meta.ts`、`market.ts`。
- 新增 `frontend/src/lib/query.ts`、`frontend/src/lib/idempotency.ts`。
- 新增 `frontend/src/api/client.test.ts`、`errors.test.ts`。

要求：

- 所有请求带 `Accept: application/json`；创建与重试带 `Idempotency-Key`。
- 错误统一转成 `{code, message, details, status}`；文案优先取服务端 `message`，未知码回退通用文案，不显示堆栈、路径或原始响应。
- `429` 暴露 `retry_after_ms`，页面按秒退避；`410` 标记为需要整页重建。
- 查询键固定：`["jobs", filters]`、`["job", id]`、`["meta", "options"]`、`["market", "search", q]`；控制动作后失效 `job` 与 `jobs`。
- 幂等键在每次「提交意图」创建时生成一次；网络错误后的同一次重试复用，用户改表单后重新生成。
- 不缓存 `meta/options` 超过 60 秒；任务详情不设长缓存。

测试：

- WEB-04：400/401/404/409/410/422/429/500/502 九种错误映射；不泄露响应原文。
- WEB-05：幂等键在重试中复用、改表单后更换；动作后查询失效。
- WEB-06：字段可空、`next_cursor` 为 null、`details` 缺失时类型与渲染都不崩。

回退：删除 `frontend/src/api/` 与 `lib/query.ts`，页面回到占位。后端不变。

验收：MSW 下九种错误文案与退避正确；没有组件直接拼 URL。

### P2-06 全局搜索与活动任务条

目标：任何页面都能搜到股票、看到正在跑的任务，并且点进去不创建任何东西。

依赖：P2-05。

涉及文件：

- 新增 `frontend/src/features/search/SearchBox.tsx`、`useStockSearch.ts`。
- 新增 `frontend/src/shell/ActiveJobBar.tsx`、`useActiveJobs.ts`。
- 新增对应测试与 `frontend/src/shell/ActiveJobBar.test.tsx`。

要求：

- 搜索输入 250ms 防抖、最少 1 个字符、最多 10 条；上下键选择、回车执行。工作台里的搜索进入启动器；其他页面的顶栏搜索进入股票占位页。无结果显示「没有找到，检查代码或名称」。
- 活动任务条只在存在五个非终态任务时出现；显示最近创建的一个：股票名或代码、阶段 n/12、查看；多于一个显示「还有 N 个」。
- 每 10 秒刷新一次活动任务；控制动作后立即失效；终态后任务条消失。
- 点击任务条只导航到 `/jobs/:jobId`，不发 `POST /jobs`。

测试：

- WEB-07：防抖、键盘选择、空结果、请求失败的重试按钮。
- E2E-07：从工作台、任务列表占位页、报告占位页分别点任务条，都导航到同一个 `/jobs/:jobId`，全程没有 `POST /jobs`；终态后任务条消失。
- 多任务时显示「还有 N 个」由 WEB-07 用 MSW 覆盖；A04 的完整返回路径与「还有 N 个」跳转放到 P2-13 验收，因为详情页与列表页要到 P2-09、P2-10 才存在。

回退：删除搜索与任务条组件，顶栏留静态搜索图标。

验收：搜索无重复请求；活动任务条不出现终态任务；进入详情零创建。

### P2-07 工作台首页 W01

目标：首屏两步内发起分析，并能回到未完成的研究。

依赖：P2-06。

涉及文件：

- 新增 `frontend/src/features/workbench/WorkbenchPage.tsx`、`ActiveJobCard.tsx`、`RecentJobs.tsx`。
- 新增 `frontend/src/features/workbench/WorkbenchPage.test.tsx`。

要求：

- 桌面顺序：活动任务条、搜索加「开始分析」、最近任务 3 行、最近报告占位、精简市场占位。
- 移动：主按钮固定在首屏，不藏进菜单；最近报告收起为「查看全部」，但 P2 只显示「报告库将在 P3 开放」。
- 最近任务来自 `GET /jobs?limit=3`；点击进详情；空态给「开始第一次分析」。
- 搜索选中股票后打开启动器，不在首页创建任务。
- 失败任务显示「查看错误」与「重新分析」；中断任务显示「等待人工处理」，不显示「进行中」。
- 市场与报告占位不伪造数字，写明后续阶段。

测试：

- E2E-03：390 首屏可见主按钮；活动卡与最近任务无需展开可见；打开启动器再关闭不创建任务。
- WEB-08：无活动任务时不留空白；无最近任务时空态；失败与中断任务的文案分支。

回退：工作台回占位页，保留搜索与任务条在顶栏。

验收：首屏主操作明确；返回首页任务数不变。

### P2-08 统一分析启动器 W02

目标：所有发起分析的入口共用一套表单与提交规则。

依赖：P2-07。

涉及文件：

- 新增 `frontend/src/features/launcher/LauncherDialog.tsx`、`TickerField.tsx`、`ConfigFields.tsx`、`SubmitState.tsx`、`useCreateJob.ts`。
- 新增 `frontend/src/features/launcher/LauncherDialog.test.tsx`。

要求：

- 打开入口：工作台、股票占位页、任务重试（P2-12 接入）都用同一组件；报告重跑在 P3 接入。桌面居中对话框，移动全屏。
- 深链接 `/workbench?launch=1&ticker=000629` 直接打开并预填。
- 顺序：标的、分析日期（默认取 `meta/options.default_analysis_date`，不按本地时区推导）、模型配置、并行开关、三个阶段开关（默认收起）、费用提示、提交。
- 点击后按钮立即禁用并显示「提交中」；同一提交意图复用一把幂等键。
- 201 跳 `/jobs/:jobId`；200 且带 `X-Existing-Job` 跳已有任务并提示「已有一个相同分析」；409 `active_conflict` 给「查看进行中的任务」与「取消」，不提供强制新建；422 字段错误留在表单内且不清空；429 按 `retry_after_ms` 显示等待秒数。
- 提交前说明会调用付费模型；取消说明已发生的调用无法撤销。

测试：

- A01：搜索「宁德」→ 选中 → 默认日期 → 提交 → URL 为新 jobId，任务数加一。
- A02：连点三次只创建一个任务，按钮在首次点击后禁用。
- A03：同配置再提交跳已有任务；改配置提交显示 409 冲突与已有任务入口。
- WEB-09：422 字段错误保留输入；429 显示秒数；双击只发一次请求。

回退：删除启动器，入口按钮回空态或跳工作台。

验收：A01 至 A03 通过；重复提交不产生第二个任务；默认日期与服务器一致。

### P2-09 任务列表页 W03

目标：按状态、股票、日期找到任务，返回时筛选不丢。

依赖：P2-04、P2-05。

涉及文件：

- 新增 `frontend/src/features/jobs/JobListPage.tsx`、`JobFilters.tsx`、`JobTable.tsx`、`JobCards.tsx`。
- 新增 `frontend/src/features/jobs/listParams.ts` 与测试。

要求：

- 筛选：九状态多选（默认全选）、股票代码、分析日期范围、「只看活动任务」开关、重置。
- 筛选与游标写进 query；直接打开深链接按 query 重建；返回列表恢复筛选、已加载页与滚动位置。
- 桌面表格：股票、分析日期、状态、当前阶段、耗时、创建时间、查看；活动阶段带进度条；失败行显示安全错误文案。
- 移动卡片：股票加状态、日期加阶段、耗时；整卡可点；筛选进全屏页，应用后显示条件 chips。
- 底部「加载更多」用 `next_cursor`；空列表、筛选为空、接口错误、加载更多失败分别有文案与下一步。
- 不自动轮询整页；活动行的当前阶段可每 10 秒刷新一次。

测试：

- E2E-04：深链接 `/jobs?status=failed&ticker=000629` 直接打开即筛选；重置后回默认；刷新不丢筛选。
- A14 的「进详情再返回恢复滚动位置」放到 P2-13 验收，因为详情页要到 P2-10 才存在。
- M06：390 下不渲染表格，每行是摘要卡片。
- WEB-10：query 与筛选状态双向转换；空数组不写成 `status=`；非法状态被忽略。

回退：任务路由回占位页；活动任务条仍可用。

验收：E2E-04、M06、WEB-10 通过；翻页不重不漏；移动端无表格。

### P2-10 任务详情页 W04 静态与阶段报告

目标：九个状态、十二个阶段、统计与阶段报告都能如实展示。

依赖：P2-05。

涉及文件：

- 新增 `frontend/src/features/jobs/JobDetailPage.tsx`、`StatusHeader.tsx`、`StageTimeline.tsx`、`StatsBar.tsx`、`StageReportView.tsx`、`JobNotice.tsx`。
- 新增 `scripts/seed_e2e_jobs.py`：仅测试用，经服务层创建任务，再用测试夹具把行推进到九种状态与断点；必须带 `TA_E2E=1` 才运行，不进产品路径。
- 新增 `frontend/src/features/jobs/JobDetailPage.test.tsx`。

要求：

- 头部：股票名或代码、分析日期、状态徽标、按 `allowed_actions` 渲染的按钮组。
- 阶段：桌面 7 个分析阶段一行、5 个流程阶段一行；移动单列时间线，不出现两列；当前阶段高亮。
- 统计条：模型调用、输入 Tokens、输出 Tokens、耗时。
- 阶段报告：按阶段倒序，最近完成的自动展开；展开时请求 `GET /jobs/{id}/stages/{stageId}`；显示前若干行与「展开全文」；`pending`、`active`、`skipped` 显示「尚未产出」；markdown 禁用原始 HTML，外链新窗口且带 `rel="noopener"`。
- 状态区：failed 显示安全错误与下一步；interrupted 显示「从检查点继续」与说明；pause_requested 显示「正在暂停，将在当前阶段结束后生效」；succeeded 且 `report_id` 非空时显示「打开报告」，P2 阶段点击进入报告占位页。
- 任务不存在显示 404 页「没有找到这个任务」，只给回任务列表，不创建任务。
- 移动端阶段报告用底部抽屉，抽屉内独立滚动，页面不出现双层滚动。

测试：

- E2E-05：九种状态各渲染一次；12 个阶段布局；阶段报告展开与全文；404 页。
- WEB-11：原始 HTML 不执行；`<script>` 被丢弃；外链带 `rel="noopener noreferrer"`。
- WEB-14：`allowed_actions` 为空时按钮区不渲染；`report_id` 为空时不显示「打开报告」。

回退：详情路由回占位页；已生成的任务数据不变。

验收：九个状态没有错误文案；阶段报告按需加载；移动端单列时间线。

### P2-11 任务详情 SSE 与重连

目标：进度真实、断线可恢复、重连不创建任务。

依赖：P2-10。

涉及文件：

- 新增 `frontend/src/api/sse.ts`、`frontend/src/features/jobs/useJobStream.ts`。
- 新增 `frontend/src/api/sse.test.ts`、`frontend/src/features/jobs/useJobStream.test.tsx`。

要求：

- 首帧 `snapshot` 直接更新详情；随后按 `stage_changed`、`status_changed`、`stats`、`report_ready` 更新对应区域。
- `Last-Event-ID` 存在 `sessionStorage`（按 jobId 分开）；刷新后带上游标续传。
- 断线显示顶部黄条「正在重连，阶段可能延迟」；按 1s、2s、4s、8s 退避，恢复后自动消失；终态后关闭连接，不再重连。
- 410 `sse_cursor_expired`：黄条改为「刷新以恢复」并给刷新按钮，不用旧游标重放。
- 订阅只读：重连过程不得发 `POST /jobs`，也不得调用任何控制接口。

测试：

- A05：详情刷新后阶段与按钮一致，`Last-Event-ID` 续传，任务数不变。
- A06：离线 10 秒再恢复，黄条出现后消失；事件序号无空洞；终态连接关闭。
- WEB-12：SSE 帧解析、退避序列、410 分支、终态停止重连；重连不发创建请求。

回退：删除订阅，详情改为进入时拉一次加手动刷新按钮。

验收：A05、A06 通过；重连零创建；终态后无新连接。

### P2-12 暂停、取消、重试与续跑

目标：控制动作只在安全边界生效，按钮只按服务端状态重画。

依赖：P2-11。

涉及文件：

- 新增 `frontend/src/features/jobs/JobActions.tsx`、`ConfirmDialog.tsx`、`useJobActions.ts`。
- 新增 `frontend/src/features/jobs/JobActions.test.tsx`。

要求：

- 暂停：点后显示「暂停中」与「已受理，将在当前阶段结束后生效」；收到 `paused` 才显示「已暂停」；重复请求 200 `already_pending` 不报错。
- 取消：二次确认写明「已产生的模型费用不退，且不会生成完整报告」；确认后显示「取消中」，`allowed_actions` 为空时不显示按钮；任务刚好完成时 409 `illegal_transition`，刷新为已完成并给报告入口。
- 重试：failed 的 `retry` 用 `same_config` 创建新任务并跳新详情；cancelled 没有 retry，只给「重新分析」走启动器新幂等键。旧任务不变；重复点击不产生两个新任务。
- 续跑：interrupted 且指纹一致时显示「从检查点继续」，新任务带 `resume_of_job_id`；`resume_fingerprint_mismatch` 时隐藏续跑，只给「重新分析」。
- 所有动作后以服务端返回的 `allowed_actions` 为准，不在前端自己推状态表。

测试：

- A07：暂停到阶段边界后变 paused，继续后从下一阶段接着跑，同一个 jobId。
- A08：取消确认与不确认两支；终态 cancelled 无报告入口。
- A09：失败任务重试创建新任务，旧任务字段不变。
- A10：中断任务续跑创建新任务并带溯源；指纹不一致只给重新分析。
- WEB-13：确认框焦点与 Esc；按钮禁用与加载态；409 后触发详情刷新。

回退：隐藏动作按钮，只按 `allowed_actions` 只读展示；后端接口保留。

验收：A07 至 A10 通过；暂停与取消状态只在服务端事件后变化。

### P2-13 P2 出口验收与性能补测

目标：用真实浏览器跑完 P2 主线，并补上 P05 的界面段。

依赖：P2-12。

涉及文件：

- 新增 `scripts/e2e_p2.py`：Playwright 驱动，临时库与临时报告目录，收集截图、控制台错误与页面溢出。
- 新增 `tests/frontend/` 下的运行说明或脚本入口。
- 新增 `docs/upgrade/reviews/2026-11-05_P2性能结果.json`（以实际日期为准）。
- 新增 `docs/upgrade/reviews/2026-11-05_P2出口评审.md`。

要求：

- 端到端覆盖：A01 至 A10、A14（任务部分）、M01 至 M03、M06 至 M07；桌面 1440、移动 390、窄屏 360 三档。A04 的跨页返回与「还有 N 个」跳转在这一票补齐。
- P05 界面段：测「SSE 帧到达浏览器到阶段状态可见」的耗时，记 P05-c；P05 总时延按 P05-a（P1 服务端中位）加 P05-c 的中位汇报，硬线仍是 500ms。
- 断言：页面脚本错误为 0；360/390 无页面级横向滚动；触控项不小于 44px；重连不创建任务；终态任务条消失。
- 旧版仍是默认写入口：`run_all.bat`、`web/launch.py`、8501 端口未改；旧版健康检查 ok。
- 回退演练：只跑 P1 后端套件（508 条）证明新前端可整体删除；再跑一次 `npm run build` 前端的独立构建。

测试编号：E2E 全量、M01 至 M03、M06 至 M07、P05-c。

回退：本票只加测试、脚本与文档，删除即可。产品行为不变。

验收：出口评审记录给出七条判据的测试名、命令、输出摘要与提交号。

## 4. P2 出口判据

P2 完成必须同时满足：

1. 跨页和刷新不丢任务：任务条在非终态页面常驻；详情刷新后按 `Last-Event-ID` 续传；任务列表返回恢复筛选与滚动位置。
2. 暂停与取消状态真实：界面只在服务端事件到达后变化；暂停落在阶段边界；取消二次确认且终态无报告入口。
3. 360 与 390px 无页面级横向溢出；触控项不小于 44px；移动端不渲染桌面表格。
4. 旧版仍是默认写入口：`run_all.bat`、`web/launch.py`、8501 入口未改，健康检查 ok。
5. 启动器重复提交只创建一个任务；同配置复用与异配置冲突都按契约提示。
6. 全部端到端测试使用假图与临时目录；真实模型默认关闭；不联网、不读取 API Key。
7. 每票一个本地提交，回退方式经过演练；每票完成后预检与旧版冒烟通过。

详细证据格式沿用 P0：测试编号、命令、输出摘要、提交号。

## 5. 与冻结契约的对应

- 路由、返回与刷新恢复：`contracts/routes.md` 九条路由与十条全局规则。
- 页面结构与状态：`contracts/core-wireframes.md` W01 至 W04。
- 字段与按钮：`contracts/api-v1.md` 1.1、1.4、1.5、1.6、1.8；`contracts/semantic-dictionary.md`。
- 状态与转换：`contracts/job-state-machine.md` T01 至 T20、I01 至 I11。
- 事件与序号：`contracts/sse-events-v1.md`。
- 错误码与文案：`contracts/error-codes-v1.md`。
- 市场数据信封：`contracts/market-data-envelope-v1.json` 与 `api-v1.md` 3.0。
- 走查与移动专项：`contracts/interaction-checklist.md` A01 至 A10、A14、M01 至 M03、M06 至 M07。
- 冻结与变更：`contracts/FREEZE-v1.md`。

P2 不允许在代码里另立状态名、事件名或错误码。发现契约缺陷时先走 `FREEZE-v1.md` 第 4 节的解冻流程。

## 6. 留给后续阶段

| 内容 | 阶段 | P2 的处理 |
| --- | --- | --- |
| 报告库 W05、阅读器 W06、PDF 导出 | P3 | 占位页与顶栏入口；工作台「最近报告」显示 P3 说明 |
| 旧报告导入与兼容投影 | P3 | 不做 |
| 股票工作区 W07、市场 W08、行情数据 | P4 | 占位页；搜索可跳转但页面未实现 |
| 日志 W09、设置 W10、主题与可访问性收尾 | P5 | 占位页；顶栏主题切换只切令牌，不读服务端设置 |
| 写入开关、默认入口切换、真实 Canary | P6 | 不做；旧版仍是默认写入口 |
| 运行期配置隔离验收 | P6 | 在 P1 出口评审里已列为前置条件 |
