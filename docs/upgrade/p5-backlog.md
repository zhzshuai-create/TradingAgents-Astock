# P5 任务拆票：交易日志、设置、主题与可访问性收尾

版本：v1（2026-11-07）
上游：`docs/upgrade/reviews/2026-11-07_P4出口评审.md` 结论为 Go；`docs/upgrade/P4-12交接卡.md` 给出票序 P4-12 → P5。
依据：`docs/AStock_Pro_专业投研工作台全面升级计划_2026-10-28.md` 第 2.3、2.4、3.1、3.2、4.9、4.10、5.2、10.4、11.1 节与附录 A「交易日志与设置」；`docs/upgrade/contracts/routes.md` 第 1、2 节；`core-wireframes.md` 第 9、10 节；`interaction-checklist.md` 的 M03、M07、M08；`api-v1.md` 1.8、4.2、4.3；`FREEZE-v1.md` 第 1、4 节。
用途：把 P5 拆成 10 张可独立验收的票（P5-00 至 P5-09）。每票单独提交、单独回退、单独跑测试。

P5 收口交易日志外壳、设置页、主题与密度、键盘、读屏、减少动态效果、axe 与移动收尾。完成后新版具备完整导航与设置，但**不切换默认入口**；旧版 Streamlit 仍是默认写入口，双栈灰度与回滚留给 P6。交易日志保持独立服务与独立数据：不合并数据库，不把业务重写为 React 子模块。

## 0. 公共约束

- 技术栈不换：React 19 + TypeScript + Vite + TanStack Query；后端 FastAPI + SQLAlchemy + Alembic。前端不新增运行时依赖；`axe-core` 只允许作为开发依赖，且不进入构建产物。
- 只使用已冻结的 `GET /api/v1/meta/options` 与既有报告、任务接口。**不新增 HTTP 端点、字段、错误码、状态名、事件名**；`meta/options` 的八个顶层键保持不变（`tests/backend/test_meta_options.py` 的 META-01 逐键断言）。
- P5 零迁移：不建表、不改表，迁移头保持 `0007`。
- 冻结契约不改。发现计划书与契约冲突时，冲突写进第 1.2 节，不临场扩契约；确需解冻时走 `FREEZE-v1.md` 第 4 节，先改契约与测试，再改代码。
- 后端不得 `import web.*`；GET 零写盘；测试不联网、不读 API Key、不读写真实 `~/.tradingagents`。
- 不改 `tradingagents/`、`web/`、`run_all.bat` 与旧版 8501 入口；不改 `trade-journal` 仓库。旧版仍是默认写入口。
- 前端 `fetch` 与 `/api/v1` 字面量只出现在 `frontend/src/api/`；组件只读 props。密钥、Base URL、任意模型地址不得出现在前端输入、存储、URL、DOM 或错误文案。
- 断点仍为 767px；触控目标 ≥44px；360/390 无页面级横向溢出，只允许图表、页签、指数条、目录在容器内滚动。
- 一票一本地提交，不推送；代码与证据分开提交。开工前与收工前预检必须 10 项 PASS。
- 计划书与冻结契约冲突时以契约为准；本文件的 D/C 口径优先于临时口头约定。

## 1. 票内定稿

### 1.1 十二项决定

**D1 偏好只存本地非敏感项**

新增 `frontend/src/lib/preferences.ts`，用单一版本键 `astock.prefs.v1` 保存：

```text
density: "comfortable" | "compact"
refresh: "standard" | "relaxed" | "manual"
export: "pdf" | "markdown"
launcher: { llm_profile?: string, parallel_analysts?: boolean }
```

主题继续用既有键 `astock.theme`（`frontend/src/shell/useTheme.ts`），不迁移、不改名。读取失败、JSON 非法、枚举越界一律回默认值，不抛异常；存储被禁用时用内存默认值。偏好不含密钥、Base URL、日志地址、数据目录。

理由：设置接口不在冻结契约内；本地偏好不冒充服务端配置，也不改变已有任务的配置快照。

**D2 主题与密度**

主题沿用 `light | dark` 加 `prefers-color-scheme` 默认，已有顶栏与移动端切换。密度新增根属性 `data-density="comfortable|compact"` 与两组令牌：

```text
--row-height: 44px | 36px
--row-padding-y: 10px | 6px
```

紧凑密度只作用于桌面列表与表格：任务表、报告表、市场行业行、强势股行、股票报告行。≤767px 强制标准密度，保证 M03 的 44px 触控目标。图表、正文、对话框不参与密度切换。

**D3 刷新偏好只能变慢**

`usePolling(interval)` 读取偏好：`standard` 用契约间隔，`relaxed` 用 2 倍间隔，`manual` 关闭自动轮询。任何档位都不得快于 `api-v1.md` 3.0 的 `stale_after`；隐藏页 60s 下限保持不变（`HIDDEN_POLL_MS`）。`manual` 同时关闭回前台自动重取，手动刷新按钮仍可用。

**D4 导出偏好与 Markdown 入口**

报告阅读器同时提供 PDF 与 Markdown 下载。Markdown 直接链接既有 `GET /api/v1/reports/{id}/markdown`（`api-v1.md` 2.3），不新开接口、不拼 blob。偏好只决定哪个按钮为主操作，两种格式始终可达。

**D5 设置页只展示契约给得起的信息**

设置页分四组，深链 id 固定为 `group-basic`、`group-model`、`group-data`、`group-about`，对应 `routes.md` 的「基本/模型/数据源/关于」：

- 基本：接口可达（meta 查询结果）、最近一次 SSE 连接结果、`app_version`、`contract_version`、`server_time`（标 `+08:00`）、日志状态与 `/journal` 链接。
- 模型：`llm_profiles` 只读列表、默认模型（本地偏好，预填启动器）、默认并行分析师开关与实验性说明；明确写出 Base URL 与密钥由服务端环境配置，页面不提供输入。
- 数据源：刷新偏好、导出偏好、日志入口地址只读展示；行情数据源与最近成功时间以市场页信封为准，设置页不另造状态。
- 关于：版本、构建说明、许可与免责声明、旧版入口。

不展示 Worker 健康、数据目录绝对路径等契约没有的字段（见 C1、C2）。`meta/options` 的顶层键不增加。

**D6 日志三态与手动启动**

`/journal` 只有三种界面状态：

- 可用：顶部一行「日志服务运行中」+「新窗口打开」+「刷新」，下方整页 iframe。
- 启动中：用户点「已启动，重试」后，每 2s 重取 `meta/options`，最多 30s；期间显示「正在等待日志服务就绪…」。后端从不自动拉起进程。
- 不可用：按 `journal.reason` 分支给指引，`not_running` 给 `trade-journal/run.bat` 与重试按钮，`not_installed` 给安装说明不给命令，`probe_failed` 提示端口占用与代理绕过检查；三种都写「本系统不会读取或修改交易日志的数据」。

探活仍是后端 `JournalProbe` 的 300ms TCP+health 检查；前端不直连端口。

**D7 主题消息校验目标来源**

React 向 iframe 发送主题时使用 `journalOrigin`（由 `entry_url` 解析出的 `http/https` origin）作为 `targetOrigin`，不用 `'*'`。监听回执时同时校验 `event.origin === journalOrigin`、`event.source === iframe.contentWindow`、`event.data.type === "astock-theme-request"`，三者缺一即忽略。`entry_url` 非法或不是 `http/https` 时不嵌 iframe，按不可用处理。

旧版 `web/components/trade_journal.py` 仍用任意目标；本次不改旧版，也不改 `trade-journal` 仓库（见 C4）。

**D8 日志高度与单滚动容器**

可用时 iframe 容器高度为 `calc(100dvh - 顶栏 - 间距)`，iframe 占满容器；`/journal` 页面自身在移动端不滚动，只保留 iframe 内部滚动，并用 `overscroll-behavior: contain` 阻止滚动穿透。不可用时回到普通说明页滚动。跨源 iframe 无法测量内容高度，所以不做自动高度（见 C11）。

**D9 旧版入口补全**

桌面侧栏次级导航补「旧版入口」，与移动端「更多」面板一致，指向 `LEGACY_ENTRY_URL`（`http://localhost:8501`），新窗口打开、`rel="noreferrer"`。设置页「关于」组再给一处相同入口。

**D10 键盘与焦点**

- 路由切换后把焦点移到 `#main-content`（或页面 `h1`），并把 `document.title` 更新为「页面名 · AStock Pro」；首屏不强制抢焦点。
- 现有 `Dialog`/`Drawer` 的焦点陷阱、Escape 关闭、关闭后焦点归还继续复用；P5 只补审计与回归。
- 自定义可点击容器一律改为 `button`/`a`；图标按钮必须有可访问名称；不得用 `div onClick` 新增键盘不可达控件。
- 主流程仅键盘可完成：跳过链接 → 导航 → 搜索 → 股票页 → 启动器 → 任务详情 → 报告阅读器 → 设置分组 → 日志重试。

**D11 axe 只做开发依赖**

新增 `axe-core` 开发依赖，E2E 从本地 `node_modules/axe-core/axe.min.js` 注入，不联网、不打进 bundle。核心九个页面在 1440 与 390 宽度跑 WCAG 2.2 AA 规则，critical 与 serious 必须为 0；moderate/minor 记录数量与规则名。若 npm 安装不可用，改为在 `e2e/vendor/` 放置带许可证头的 `axe.min.js`，二选一在 P5-08 定稿，不允许 CDN。

**D12 C9 收口为书面例外**

`api-v1.md` 3.0 指向 `semantic-dictionary.md` 作为市场文案来源，但该文件没有市场文案；P4 已把文案落在 `frontend/src/features/market/copy.ts`。P5 不修改冻结文件，不搬文案；在出口评审把 C9 记为「长期书面例外」，写明路径、单测与不修改理由。若将来解冻，再把文案迁入语义词典。

### 1.2 十二处冲突

| 编号 | 冲突 | 定稿口径 |
| --- | --- | --- |
| C1 | 计划 4.10 要 Worker 状态与数据目录，但冻结接口没有这两个字段；`META-01` 断言 `meta/options` 恰好八个键 | 不新增字段/端点。设置页只展示契约已有信息；Worker 状态改为「以任务页活动任务为准」的链接，数据目录写「由服务端本地管理」，不显示绝对路径（`api-v1.md` 4.2.3 也禁止返回文件系统路径） |
| C2 | 计划 4.10 要模型供应商、Base URL，但 `api-v1.md` 4.2.2/4.2.4 不返回密钥与任意模型地址 | 只读展示 `llm_profiles` 的 id 与名称；Base URL 与密钥写「服务端环境配置」，不提供输入 |
| C3 | 计划 4.9 的状态含「启动中」 | 启动中是前端本地等待态，不是服务端状态；后端仍只做探活，不自动拉起，不新增状态名 |
| C4 | 旧版日志桥用 `postMessage(..., '*')`，外部 `trade-journal` 监听也不校验来源 | 新 React 页只对自己的消息做严格校验并按 origin 发送；旧版与外部仓库不在本票改，记入遗留事项 |
| C5 | 密度若全局缩放间距，会破坏移动端 44px 触控与既有密集布局 | 密度只改桌面列表行高与行内边距；≤767px 强制标准密度 |
| C6 | 「行情刷新偏好」若允许加速，会违反契约新鲜度下限 | 偏好只能等间隔或变慢：`standard` / `relaxed` / `manual`；隐藏页 60s 下限与 R-15 断言不变 |
| C7 | axe 需要第三方脚本 | 只作开发依赖，E2E 本地注入；不进 bundle、不联网 |
| C8 | W10 要「SSE 可达（用最近一次连接结果）」，但没有健康接口 | 在 `api/sse` 记录最近一次连接结果（成功/失败/未连接）到模块级只读状态，设置页展示；它不代表 Worker 健康 |
| C9 | P4 的 C9 市场文案位置与契约指向不一致 | 长期书面例外；不修改冻结文件，不新增文案源 |
| C10 | 计划 3.1 的桌面导航第 8 项是旧版入口，当前桌面侧栏没有 | 桌面侧栏补齐；移动端已有，不改路由 |
| C11 | 跨源 iframe 无法测内容高度 | 用视口固定高度与单滚动容器，不做自动高度 |
| C12 | W10 移动端是「分组列表，点进二级页」，但路由只有 `/settings` | 二级页用 `#group-xxx` 与本地选中态表达，不新增路由；非法 hash 回顶部 |

### 1.3 文案与词表

新增 UI 文案只用于界面，不进入 `api-v1.md` 状态词表。

| 场景 | 固定文案 |
| --- | --- |
| 日志可用 | 日志服务运行中 |
| 日志启动中 | 正在等待日志服务就绪… |
| 日志不可用 | 交易日志是独立应用，当前没有在运行。 |
| 数据隔离 | 本系统不会读取或修改交易日志的数据。 |
| 设置分组 | 基本 / 模型 / 数据源 / 关于 |
| 密度 | 标准 / 紧凑 |
| 刷新 | 标准 / 省流 / 手动 |
| 导出 | PDF 优先 / Markdown 优先 |
| SSE 最近结果 | 未连接 / 最近一次连接成功 / 最近一次连接失败 |

不得使用 `error`、`failed` 等英文状态作为用户文案；不得把 `empty` 写成「出错」，不得把 `stale` 写成「正常」。

### 1.4 现状盘点（写卡时实测）

| 面 | 现状 | 对 P5 的影响 |
| --- | --- | --- |
| `/journal` | `frontend/src/pages/JournalPage.tsx` 仍是占位页，只有「回工作台」 | P5-04 整页替换 |
| `/settings` | `frontend/src/pages/SettingsPage.tsx` 仍是占位页，文案还写「P2-04 接入」 | P5-03 整页替换并清掉过时阶段号 |
| 日志探活 | `backend/app/core/journal_probe.py` 已实现 300ms TCP + `/_stcore/health`；三原因 `not_running` / `not_installed` / `probe_failed`；不自动启动 | 后端零改动，前端直接用 `meta/options.journal` |
| 元信息 | `backend/app/api/v1/meta.py` 返回八个顶层键；`META-01` 逐键断言 | 不新增字段，见 C1 |
| 主题 | `useTheme` 已支持亮/暗、系统默认、`astock.theme` 持久化；顶栏与移动端「更多」有切换 | P5-03 在设置页再给一处，其他不改 |
| 密度 | 仓库无 `data-density`、无可切换行高；列表间距写在各 CSS Module | P5-01 新增令牌并接入五类列表 |
| 刷新 | `lib/useVisibleRefetch.ts` 的 `REFRESH_INTERVALS` 是唯一毫秒表；`usePolling` 固定取契约间隔 | P5-02 在 `usePolling` 内乘系数，其他调用点不改 |
| 导出 | `ReportActions.tsx` 只有 PDF；后端 `GET /reports/{id}/markdown` 已存在 | P5-02 补 Markdown 链接与偏好 |
| 键盘 | 跳过链接、`:focus-visible`、Dialog/Drawer 焦点陷阱与 Escape 已有；路由切换不移动焦点，`document.title` 不更新 | P5-06 补焦点与标题，回归既有对话框 |
| 读屏 | 任务详情已有 `role=status`/`aria-live`；错误多为 `role=alert`；图表 SVG 的可访问名称未系统审计 | P5-07 审计并补 |
| 减少动态 | `global.css` 与 `Skeleton.module.css` 已有 `prefers-reduced-motion`；无 JS 数字滚动 | P5-07 验证并补脉冲类动画 |
| 旧版入口 | 只有移动端「更多」有；桌面侧栏没有 | P5-05 补 |
| axe | 依赖与 E2E 都没有 axe | P5-08 新增；只做开发依赖 |

### 1.5 与旧版的差异

| 面 | 旧版 | 新版 | 口径 |
| --- | --- | --- | --- |
| 日志启动 | Streamlit 页自动懒加载拉起 8502 | 只探活，用户手动启动 | 计划 4.9 明确不自动拉起；回退方式写进说明页 |
| 日志主题 | `postMessage(..., '*')` + 轮询父页 class | 按 origin 发送，握手校验来源与窗口 | 新版更严格；外部监听器加固另票 |
| 日志高度 | 固定 1800px | 视口高度 + 单滚动容器 | 计划 4.9 与 M08 |
| 设置 | Streamlit 侧栏配置 | 独立 `/settings` 四组 | 配置只预填新任务，不改已有快照 |
| 旧版入口 | 平台内已有 | 桌面与移动都提供 | 补齐计划 3.1 的导航第 8 项 |

### 1.6 明确不做

- 不合并交易日志数据库，不重写日志业务，不改 `trade-journal`。
- 不新增设置写接口，不把 Base URL、API Key、日志地址提交给后端。
- 不新增 `meta/options` 字段、新端点、新错误码、新状态名、新事件名。
- 不切换默认入口，不做双栈灰度、真实 Canary 与回滚演练（P6）。
- 不做 LCP/CLS/INP 全量性能门禁（P6）；P5 只保证新增交互不拖慢首屏。
- 不修 R1（百度 403 风控 / 负缓存）；它仍是独立后续票。
- 不把 C9 的市场文案搬进冻结契约。

## 2. 任务总表

工期按 1 名熟悉项目的开发者全职投入估算，含测试与修复缓冲。

| 票 | 主题 | 工期 | 主要交付 | 依赖 | 退出验收 |
| --- | --- | --- | --- | --- | --- |
| P5-00 | 基线与拆票 | 0.5 天 | 本文件、P5-01 交接卡、基线数字 | P4 出口 Go | 预检 10 PASS；票表与判据可执行 |
| P5-01 | 偏好内核与密度基础 | 1 天 | `lib/preferences.ts`、密度令牌、五类列表接入 | P5-00 | PREF/DEN 用例全绿；移动端仍 44px |
| P5-02 | 刷新与导出偏好 | 1.5 天 | `usePolling` 系数、手动档、Markdown 下载与排序 | P5-01 | REF/EXP 用例全绿；R-15 不倒退 |
| P5-03 | 设置页 W10 | 2.5 天 | 四组、深链、只读状态、本地偏好、SSE 最近结果 | P5-02 | SET 用例全绿；无密钥输入；已有任务快照不变 |
| P5-04 | 交易日志外壳 W09 | 2 天 | 三态、重试轮询、iframe 高度、主题来源校验、新窗口 | P5-03 | JRN 用例全绿；M08；日志故障不影响其他页 |
| P5-05 | 旧版入口与关于 | 0.5 天 | 桌面侧栏入口、关于组、文案清理 | P5-03 | 两处入口可用；无 8501 路由改写 |
| P5-06 | 键盘与焦点 | 1.5 天 | 路由焦点、`document.title`、键盘主流程 E2E | P5-03、P5-04 | KB 用例全绿；对话框焦点归还 |
| P5-07 | 读屏、对比度、减少动态 | 1.5 天 | 可访问名称、实时区、图表说明、动画审计 | P5-03、P5-04 | SR/RM 用例全绿；对比度 ≥4.5:1 |
| P5-08 | axe 与移动收尾 | 1.5 天 | axe E2E、360/390 截图与量测、触控审计 | P5-06、P5-07 | critical/serious 0；无页面级横向溢出 |
| P5-09 | 出口验收与回归 | 1.5 天 | `e2e/e2e_p5.py`、出口评审、证据 JSON | 全部 | 四条判据全 true；门禁全绿 |

合计约 14 个工作日，落在计划书的 1.5–2 周区间。

## 3. 每票说明

### P5-00 基线与拆票

只写文档：本文件与 `P5-01交接卡.md`。不改代码、不改契约、不加迁移。

写卡时 HEAD 为 `f83a937`，工作区干净；`.venv/Scripts/python.exe scripts/p0_preflight.py --full --smoke` 为 10 PASS / 0 FAIL（789 passed / 4 skipped，旧版冒烟 ok）。P4 出口基线：前端 34 个文件 / 431 条测试，入口 gzip 123.74 kB（预算 202.45），11 个路由块全 lazy 且单块 ≤20.72 kB，迁移头 `0007`。

### P5-01 偏好内核与密度基础

- 新增 `frontend/src/lib/preferences.ts`：类型、默认值、`readPreferences`、`writePreferences`、`subscribePreferences`、`usePreferences`；容错与版本键见 D1。
- 新增 `frontend/src/lib/preferences.test.ts`：非法 JSON、越界枚举、存储抛异常、订阅广播。
- `frontend/src/styles/tokens.css`：新增 `--row-height`、`--row-padding-y` 的标准/紧凑两组值；`tokens.test.ts` 断言存在。
- `frontend/src/shell/AppShell.tsx`：读取密度并写 `document.documentElement.dataset.density`。
- 五类列表改用密度令牌：`features/jobs/JobTable.module.css`、`features/reports/ReportTable.module.css`、`features/market/MarketPage.module.css`（行业表与强势股行）、`features/stocks/StockPage.module.css`（股票报告行）。≤767px 覆盖回标准值。
- 不做设置页控件（P5-03 做），不做刷新/导出（P5-02）。

验收：PREF-01 至 PREF-04、DEN-01 至 DEN-03；1440 下任务表行高 44/36，390 下始终 ≥44；`tsc`、vitest、build 绿；bundle 入口不高于 202.45 kB。

回退：删除偏好模块与测试，移除密度令牌与 `data-density` 写入，五类列表恢复字面间距。

### P5-02 刷新与导出偏好

- `lib/useVisibleRefetch.ts`：`usePolling` 读取 `refresh` 偏好，`standard` 原值、`relaxed` ×2、`manual` false；隐藏下限仍 60s。
- `lib/useVisibleRefetch.test.tsx`：三档与隐藏下限、切换即时生效。
- `features/reports/ReportActions.tsx`：新增 Markdown 下载链接，URL 来自 `api/reports.ts` 的封装；两种格式始终可见，偏好只决定主次。
- `api/reports.ts`：新增 `reportMarkdownUrl(reportId)`，仍是同源 `/api/v1/reports/...`。
- 更新阅读器测试：两种下载都在；Markdown 链接 `download` 且 href 正确；偏好排序。

验收：REF-01 至 REF-04；EXP-01 至 EXP-03；`market_e2e.py` 与 `stock_e2e.py` 的 R-15 全过；默认档下轮询间隔不变。

回退：恢复 `usePolling` 固定取间隔，删除 Markdown 链接与偏好分支。

### P5-03 设置页 W10

- 重写 `frontend/src/pages/SettingsPage.tsx` 与新增 `features/settings/`：四组、组内字段、本地偏好控件、保存提示。
- 数据来源：`metaOptionsQuery`；最近 SSE 结果来自 `api/sse.ts` 的只读记录；日志状态链到 `/journal`。
- 深链：`#group-basic|group-model|group-data|group-about`；未知 hash 停在顶部，不报错；移动端分组列表进二级页，选组写 hash。
- 本地偏好：密度、刷新、导出、默认模型、默认并行分析师；修改即保存，`aria-live` 提示「已保存」。
- 只读：`app_version`、`contract_version`、`server_time`、`journal.entry_url`、模型列表；Base URL 与密钥只写说明。
- 安全：页面无 `type="password"`、无 `api_key`/`base_url` 输入、无密钥渲染；localStorage 只允许 `astock.prefs.v1` 与 `astock.theme`。

验收：SET-01 至 SET-08；四组深链刷新可恢复；已有任务详情仍显示创建时快照；DOM/localStorage 无密钥模式；移动端 360/390 无横向溢出。

回退：恢复占位页，删除 `features/settings/`；偏好模块可保留（P5-01 已用）或一并回退。

### P5-04 交易日志外壳 W09

- 重写 `frontend/src/pages/JournalPage.tsx` 与新增 `features/journal/`：`JournalFrame`、`JournalUnavailable`、`JournalStarting`、`useJournalThemeBridge`。
- 状态机：`available | starting | unavailable(reason)`；`starting` 每 2s 重取 meta，30s 超时；「重试」立即重取。
- 主题桥：`useEffect` 监听主题与 iframe load；按 origin 发送；校验 `origin`、`source`、`data.type`；卸载移除监听。
- 布局：可用时整页 iframe，桌面/移动都单滚动容器；不可用时说明页；`not_running` 显示 `run.bat`，`not_installed` 不显示命令，`probe_failed` 显示端口与代理检查。
- 新窗口按钮：`entry_url` 仅 `http/https`，`rel="noreferrer"`。
- 后端零改动；探活异常仍由 `meta.py` 降级。

验收：JRN-01 至 JRN-10；三原因文案不同；主题回执只接受同源同窗口；外来 origin 不回复；iframe 高度随视口；360/390 页面本身不滚动；日志不可用时市场/任务/报告仍正常。

回退：恢复占位页，删除 `features/journal/`；无后端改动可回退。

### P5-05 旧版入口与关于

- `shell/Sidebar.tsx` 次级导航后加外链 `旧版入口`，复用 `LEGACY_ENTRY_URL`，`target="_blank"`、`rel="noreferrer"`、`external` 图标。
- 设置「关于」组加入口、版本、许可与免责声明。
- 检查全站没有残留的过时阶段号；市场文案 C9 只写说明，不搬文件。

验收：LEG-01 至 LEG-03；桌面/移动两处 href 都是 8501；外链不被 React Router 拦截；axe 不因外链名称报错。

回退：移除桌面外链与关于入口。

### P5-06 键盘与焦点

- 路由监听：`useEffect` 在 `pathname` 变化时聚焦 `#main-content`，设置 `document.title`；首屏跳过。
- 审计并用 `button`/`a` 替换键盘不可达控件；补图标按钮可访问名称。
- 回归 `Dialog`/`Drawer`：Tab 循环、Escape、焦点归还；移动端「更多」抽屉同样。
- 新增 `e2e/keyboard_e2e.py`：只用 Tab/Shift+Tab/Enter/Space/Escape 走主流程；断言焦点顺序、可见焦点、对话框归还、无键盘陷阱。

验收：KB-01 至 KB-08；主流程无鼠标完成；焦点环始终可见；Escape 不误关页面。

回退：移除路由焦点/标题 effect 与 E2E；对话框实现未改。

### P5-07 读屏、对比度、减少动态

- 审计九个核心页的 landmark、标题层级、表格语义、图表可访问名称与描述；SVG 图表补 `role="img"` 与 `aria-label`，或提供文本摘要。
- 补实时区：刷新完成、偏好保存、日志状态变化使用 `role="status"`/`aria-live="polite"`；错误继续 `role="alert"`。
- 减少动态：全局规则已存在；检查所有 `animation`/`transition`/自动滚动；补遗漏的脉冲与骨架；确保开启后无持续动画。
- 对比度：用 axe 与手工抽检亮/暗两套关键文本与控件，正文 ≥4.5:1，大字 ≥3:1。

验收：SR-01 至 SR-06、RM-01 至 RM-03；读屏名称可枚举；减少动态下无动画；亮/暗对比度过线。

回退：移除新增 aria 与动画覆盖；不改数据与接口。

### P5-08 axe 与移动收尾

- 安装/固定 `axe-core`（D11），新增 `e2e/a11y_e2e.py`：九个核心页 × 1440/390，关键页加 360；输出规则、影响级别、节点数；critical/serious 为 0，否则非零退出。
- 移动量测：360/390 页面 `scrollWidth == clientWidth`；触控目标 ≥44px；设置与日志页专项（W09M、W10 移动二级页）；截图存 `ui_shots_p5/`，不入库。
- 修 P5-06/P5-07 遗留的 axe 问题；不通过全局禁用规则来过关。

验收：AX-01 至 AX-06、MOB-01 至 MOB-06；零 critical/serious；无页面级横向溢出；触控达标。

回退：移除 axe 依赖与 E2E；不改产品代码则无行为变化。

### P5-09 出口验收与回归

- 新增 `e2e/e2e_p5.py`：聚合构建、bundle、Python 分组与全量、P2/P3/P4 回归、P5 四套 E2E、axe、迁移头、旧版冒烟与预检；单行 JSON，失败非零退出。
- 新增 `docs/upgrade/reviews/2026-11-XX_P5出口评审.md` 与证据 JSON：四条判据逐条对应，记录 R1、C9、C4 等遗留。
- 不改产品行为；发现缺陷退回对应票修，不在本票夹带。

验收：第 5 节全部判据与门禁全绿；复跑命令可复制执行。

回退：删除聚合脚本与证据；产品代码不受影响。

## 4. 测试与证据口径

### 4.1 单元测试

| 组 | 编号 | 断言 |
| --- | --- | --- |
| 偏好 | PREF-01 至 PREF-04 | 默认值、非法值回退、存储异常不影响运行、订阅广播 |
| 密度 | DEN-01 至 DEN-03 | 令牌存在；根属性切换；移动端强制标准 |
| 刷新 | REF-01 至 REF-04 | 标准/省流/手动；隐藏 60s 下限；切换即时生效 |
| 导出 | EXP-01 至 EXP-03 | 两格式可达；偏好只改主次；URL 同源 |
| 设置 | SET-01 至 SET-08 | 四组、深链、只读字段、SSE 最近结果、无密钥、快照不变、保存提示、非法 hash |
| 日志 | JRN-01 至 JRN-10 | 三态、三原因、重试轮询、超时、来源校验、外来消息忽略、高度、滚动、新窗口、隔离声明 |
| 键盘 | KB-01 至 KB-08 | 路由焦点、标题、Tab 顺序、Escape、焦点归还、无陷阱 |
| 读屏/动态 | SR-01 至 SR-06、RM-01 至 RM-03 | 名称、landmark、标题层级、实时区、图表说明、减少动态 |

### 4.2 浏览器 E2E

- `e2e/settings_e2e.py`：桌面 1440（四组、深链、偏好持久化、无密钥、已有任务快照）与移动 390/360（分组列表、二级页、无横向溢出）。
- `e2e/journal_e2e.py`：用 `page.route` 模拟 `meta/options` 三原因与 available；第二个本地 HTTP 服务充当日志 iframe，记录收到的消息；同源回执与异源消息两条断言；市场/任务页在日志故障时仍渲染。
- `e2e/keyboard_e2e.py`：纯键盘主流程。
- `e2e/a11y_e2e.py`：axe 九页 × 两档宽度。
- 所有 E2E 用构建后的 `vite preview` 与本地 stub，不联网、不启动真实 8502、不读写 `~/.tradingagents`。

### 4.3 证据文件

```text
docs/upgrade/reviews/2026-11-XX_P5-01前端结果.json
docs/upgrade/reviews/2026-11-XX_P5-02前端结果.json
docs/upgrade/reviews/2026-11-XX_P5-03前端结果.json
docs/upgrade/reviews/2026-11-XX_P5-04前端结果.json
docs/upgrade/reviews/2026-11-XX_P5-06前端结果.json
docs/upgrade/reviews/2026-11-XX_P5-07可访问性结果.json
docs/upgrade/reviews/2026-11-XX_P5-08axe结果.json
docs/upgrade/reviews/2026-11-XX_P5出口评审.md
```

截图：`ui_shots_p5/P5-03/`、`P5-04/`、`P5-08/`，不入库。

## 5. P5 出口判据

P5 完成必须同时满足：

1. **日志故障不拖垮主站**：`not_running`、`not_installed`、`probe_failed` 与探活超时四种情况下，工作台、市场、股票、任务、报告仍能打开；日志页给出对应原因与下一步；后端探活单步不超过 300ms、总计不超过约 600ms，且不自动拉起进程；可用时单滚动容器，主题消息只发往目标 origin。
2. **设置不泄露密钥**：设置页没有密钥、Base URL、任意模型地址输入；DOM、localStorage、构建产物与所有 `/api/v1` 响应都不含 API Key、Authorization、密钥字段；配置修改只影响新任务，已有任务快照不变。
3. **核心页面无严重 axe 问题**：九个核心页（工作台、市场、股票、任务列表、任务详情、报告库、报告阅读器、交易日志不可用页、设置）在 1440 与 390（关键页加 360）的 axe critical/serious 为 0；亮暗两套正文与控件对比度过线。
4. **全键盘主流程通过**：只用键盘可完成导航、搜索、发起分析、查看任务、打开报告、切换设置分组与日志重试；焦点始终可见，对话框与抽屉可关闭并归还焦点。

门禁：

- 预检 10 PASS；Python 全量不低于 789 passed / 4 skipped。
- 前端 vitest、`tsc --noEmit`、`vite build` 全过。
- 入口 chunk gzip ≤202.45 kB；路由块全 lazy 且单块 ≤60 kB。
- R-10 至 R-16 0 failures；P2/P3/P4 E2E 全绿。
- 旧版 8501 冒烟 ok；`tradingagents/`、`web/`、`run_all.bat` 未改。
- 迁移头仍为 `0007`，无新增迁移。
- 无新增运行时依赖；`axe-core` 只在 devDependencies。

## 6. 与冻结契约的对应

| 实现面 | 契约 |
| --- | --- |
| `/journal` 返回工作台与刷新恢复、`/settings` 的 `#group-xxx` | `routes.md` 第 1、2 节 |
| 日志三态、设置四组、W09/W10 结构 | 计划 4.9、4.10；`core-wireframes.md` 第 9、10 节 |
| `journal.available` / `entry_url` / `reason` | `api-v1.md` 1.8 |
| 不返回密钥、环境变量、文件路径；不接受 Base URL | `api-v1.md` 4.2 |
| 不推断 Worker/状态 | `api-v1.md` 4.3 |
| 触控 44px、360 无横向溢出、日志无双层滚动 | `interaction-checklist.md` M03、M07、M08 |
| 冻结文件不变 | `FREEZE-v1.md` 第 1、4 节 |
| WCAG 2.2 AA、axe、减少动态 | 计划书 10.4 |

## 7. 留给后续

| 内容 | 阶段 | 说明 |
| --- | --- | --- |
| Worker 健康、数据目录只读信息 | 解冻票或 P6 | 需要新增只读字段，先改契约与 META-01 |
| 旧版日志桥与外部 `trade-journal` 的来源校验 | 外部仓库 + 旧版解冻 | P5 只保证新版严格 |
| 默认入口切换、双栈灰度、真实 Canary、回滚演练 | P6 | P5 不改默认写入口 |
| LCP/CLS/INP 全量性能门禁 | P6 | P5 只保证新增页面不拖慢首屏 |
| R1 百度 403 风控与负缓存 | 独立票 | P4 已记录，不塞进 P5 |
| C9 市场文案迁入语义词典 | 解冻后再议 | P5 只记书面例外 |
| 交易日志地址可编辑 | 解冻后再议 | 当前只读 `TA_JOURNAL_URL` |

## 8. 风险

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 自定义 `TA_JOURNAL_URL` 或代理导致 origin 解析失败 | iframe 无法嵌入或消息被拒 | 只接受 `http/https`；解析失败按不可用处理；说明页给检查步骤 |
| axe 对 SVG 图表误报 | 误伤验收 | 只对容器与交互元素断言；图表补名称与文本摘要；禁止全局禁用规则 |
| 密度改动引发列表回归 | 行高/对齐错位 | 令牌只作用于五类列表；360/390 截图对比；移动端强制标准 |
| 偏好即时生效让用户以为影响旧任务 | 误解 | 设置页写明「只影响新任务」；任务详情仍读服务端快照 |
| iframe 与页面双层滚动 | 移动端体验差 | 页面锁滚动，iframe 单容器，`overscroll-behavior: contain` |
| SSE 最近结果过期 | 设置页显示旧状态 | 文案限定「最近一次」；无连接时显示「未连接」，不冒充健康 |
| axe 安装受网络限制 | P5-08 阻塞 | 允许 vendored `axe.min.js`（带许可证），仍不联网 |
| 旧版入口被当成默认入口 | 用户误操作 | 标「旧版入口」并新窗口打开；默认入口切换留给 P6 |

## 9. 顺序与停点

```text
P5-00 文档
  → P5-01 偏好/密度
  → P5-02 刷新/导出
  → P5-03 设置页
  → P5-04 日志页
  → P5-05 旧版入口/关于
  → P5-06 键盘
  → P5-07 读屏/减少动态
  → P5-08 axe/移动
  → P5-09 出口
```

每个对话只做一票；每票完成即本地提交，代码与证据分开；不推送。P5-09 完成后写 `P6` 拆票，不提前进入灰度。
