# P3 任务拆票：报告库、阅读器与迁移

版本：v1（2026-11-06）
上游：`reviews/2026-11-05_P2出口评审.md` 结论为 Go。
依据：`AStock_Pro_专业投研工作台全面升级计划_2026-10-28.md` 第 4.6 至 4.8 节、第九节 P3 行、第 10.2 节；`contracts/api-v1.md` 第 2 节；`contracts/core-wireframes.md` 第 5、6 节；`contracts/routes.md`；`contracts/report-consistency-tests.md`；`contracts/interaction-checklist.md` 的 A11 至 A14、M04、M06、M07；`contracts/report-schema-v1.md`。
用途：把 P3 拆成 9 张可独立验收的票。每票单独提交、单独回退、单独跑测试。

P3 交付报告链路：报告库、报告阅读器、统一报告结构、旧报告导入、按需导出、兼容投影。完成后形成内部 MVP，但**不切换默认入口**；旧版 Streamlit 仍是默认写入口，市场、日志、设置留给 P4/P5。

## 0. 公共约束

- 技术栈不换：React 19 + TypeScript + Vite + TanStack Query；后端 FastAPI + SQLAlchemy + Alembic。前端不新增运行时依赖（`react-markdown` 10.1 已装）；PDF 用已锁定的 `fpdf2 2.8.9`。
- 只实现 `api-v1.md` 第 2 节已冻结的 6 个端点：报告列表、详情、Markdown、导出 PDF、导出状态、导出文件。不新增 HTTP 错误码、状态名、事件名、DTO 字段。
- 迁移只做新增式：`0005` 之后按 `0006`、`0007` 顺序。一票独占一号；若合并顺序变化，编号跟着实际合并顺序走，不允许两张迁移同号。
- 冻结契约不改：章节 id 与顺序、`content_hash` 算法、错误码、状态机、导出缓存键口径。发现缺口先走 `contracts/FREEZE-v1.md` 第 4 节解冻流程，不许先改代码再补契约。
- 不改 `tradingagents/`、`web/`、`run_all.bat` 与旧版 8501 入口。后端不得 `import web.*`（GF-06）。
- 报告 GET 零副作用：不生成 PDF、不请求行情、不写文件、不改报告行。PDF 只能由 `POST /reports/{id}/exports/pdf` 触发。
- 测试只用 `tests/fixtures/upgrade/` 与临时目录；不联网、不读 API Key、不写真实 `~/.tradingagents`。1 万条性能数据由脚本写临时库，不入库、不提交。
- 一票一本地提交，不推送。开工前与收工前预检必须 10 项 PASS。
- 断点仍为 767px；移动端主操作与触控项 ≥44px；页面级 `scrollWidth === clientWidth`，只允许正文表格在容器内横向滚动。
- 前端错误文案只来自 `ApiError.message` 或契约文案；不渲染响应体、堆栈、绝对路径。

## 1. 票内定稿（后续票不再临场决定）

### 1.1 六项决定

**D1 契约文件字节固定（P3-00 已完成）**

交接卡 §6.1 的假设需要更正：实测冻结清单的字节口径**不是全部 LF**。

| 文件类型 | 冻结值对应字节 | 实测 |
| --- | --- | --- |
| 13 份 `contracts/*.md` | CRLF | 工作区 `api-v1.md` 592 个 CRLF，sha256 等于冻结值 |
| 2 份 `contracts/*.json` | LF | `market-data-envelope-v1.json` 无 CRLF，sha256 等于冻结值 |

因此「全新检出误报」的实际形态是：`core.autocrlf=true` 的检出把 json 转成 CRLF，CT-08 在 `market-data-envelope-v1.json` 上失败（本机已复现）；md 反而因为被转成 CRLF 而恰好与冻结值一致。

处理（P3-00 同票提交 `.gitattributes`）：

```text
docs/upgrade/contracts/*.md text eol=crlf
docs/upgrade/contracts/*.json -text
```

- 固定检出字节，不重算冻结哈希，不改 CT-08 的 `read_bytes()` 口径。
- 证据：加规则后在干净检出的契约目录重新落盘，`pytest tests/test_upgrade_contract_consistency.py -q` 为 8 passed；不加规则时同一命令失败在 `market-data-envelope-v1.json`。
- 该规则只影响检出与提交时的行尾，不改历史提交与冻结值。回退：删除 `.gitattributes`。

**D2 导出记录与缓存持久化：新增 `0007_report_exports`（P3-03）**

- 字段：`export_id`（主键）、`report_id`、`content_hash`、`exporter_version`、`template`、`status`、`file_path`（相对 `TA_EXPORTS_DIR`）、`error_code`、`error_message`、`created_at`、`ready_at`。
- 唯一索引 `(report_id, content_hash, exporter_version, template)`；缓存命中 = 同键已有一行。
- `TA_EXPORTS_DIR` 为新环境变量，默认 `~/.tradingagents/exports`；库里只存相对路径，响应只给 `/api/v1/exports/{id}/file`。
- 状态机 `queued → rendering → ready | failed`。执行器是 API 进程内单线程；进程启动时把残留的 `queued`/`rendering` 行标为 `failed`，`error_code = render_failed`，文案「导出中断，请重试」。
- 状态对象的 `error.code` 本阶段只用 `render_failed` 一个值；它不是 HTTP 错误码表的一部分，HTTP 层仍只用冻结错误码。
- 模板白名单当前只有 `default`；`template` 进唯一键，不改变对外语义（`X-Export-Cached: 1` 仍只在同键命中时出现）。
- 理由：内存字典不能跨重启；`reports` 表是不可变报告行，不承担临时渲染状态；表加文件的模式与 `reports` 一致。

**D3 旧报告导入幂等：新增 `0006_legacy_imports`（P3-02）**

- 主键 `(source_path, content_hash)`，另存 `report_id`、`imported_at`。报告行保持 DTO 原样，`payload` 与 `meta` 都不塞来源路径。
- 扫描脚本 `scripts/import_legacy_reports.py`，默认 `--dry-run`，只有显式 `--apply` 才写库。
- 路径推导与旧版一致：`~/.tradingagents/logs/<ticker>/TradingAgentsStrategy_logs/full_states_log_<YYYY-MM-DD>.json`，ticker 取 `log_file.parent.parent.name`。
- 四个强制值：`generated_at = null`、`generated_at_source = unknown`、`data_quality_status = absent`、`chart_snapshot_status = none`；`origin = legacy_import`、`job_id = null`；不建 job、不追加事件。
- 幂等口径：同路径同内容重复扫描零新增；同路径改内容新增一条；并发写用唯一主键冲突忽略，不抛 500。
- 理由：`report-schema-v1` 是 `additionalProperties: false`，没有位置放来源路径；`uq_reports_job_id` 对多个 NULL 允许，旧报告可以多行并存。

**D4 PDF 渲染器：新建后端模块（P3-03）**

- 新增 `backend/app/services/pdf_renderer.py` 与 `export_service.py`，从 ReportDTO 渲染；`exporter_version = "pdf-v1"` 为模块常量，参与缓存键。
- 字体：按 Windows `msyh.ttc` / `simhei.ttf`、Linux wqy/noto 的顺序发现，允许 `TA_PDF_FONT` 覆盖；字体缺失时导出 `failed` 并给安全文案，正文与 Markdown 不受影响。
- **禁止 import `web.pdf_export`**：GF-06 边界会失败，旧渲染器还带 Streamlit 时代依赖。
- 章节顺序、标题、正文都取 `report_render.ordered_sections()`，与网页、Markdown 共用同一序列。

**D5 阅读器正文来源（P3-05）**

- 网页直接渲染 DTO 的 `sections`；`GET /reports/{id}/markdown` 只用于下载与三端一致性对照；PDF 从同一 DTO 生成。
- 不从前端 Markdown 反推 `sec-xxx`，避免第二套解析器。
- 深链 `#sec-xxx` 只操作 DOM 与 URL，不产生额外请求；章节不存在或为空时停在顶部，不报错、不 404。

**D6 兼容投影的警告面（P3-08）**

- P3 只做「投影失败写服务端日志 + 验收记录」，不做 UI 警告。
- 冻结的 API 与 ReportDTO 都没有这个字段；不得为了满足一句计划文案偷偷扩契约。
- 若必须 UI 显示，走 `FREEZE-v1.md` 第 4 节解冻，或留到 P6 双栈阶段。P3-09 在评审里如实写「未实现 UI 警告」。

### 1.2 三处契约口径冲突

| 编号 | 冲突 | 定稿口径 |
| --- | --- | --- |
| C1 | 计划 4.6 写「分析日期和生成日期筛选」，冻结的 `GET /reports` 只有 `date_from` / `date_to` 且按 `analysis_date` 过滤 | P3 只做分析日期筛选；生成日期筛选留 P4，或走解冻流程新增参数。backlog 与 P3-04 交接卡都写明这是计划与冻结接口的差异 |
| C2 | 计划 4.6 写「信号筛选」，冻结接口与 W05 实际是 `rating` 多选（五档 + unknown） | 按 `rating` 执行；不新增 `signal` 参数，前端也不另做三档筛选 |
| C3 | T17 要求 `legacy_import` 导出后 `chart_snapshot_status = refetch_needed`，但 schema 强制旧报告为 `none` | 报告行永远保持 `none`；「补数」只标在导出产物上（含补数时间与「导出时补充数据」字样），不伪装成原分析快照。P3-03 实现，P3-09 按此解释验收并在评审里单列 |

### 1.3 其它锁定项

- 列表排序：`generated_at` 倒序，null 排最后；同一时间按 `report_id` 升序，保证翻页稳定。
- 列表 `limit` 默认 20、上限 100，超限截断；游标是不透明 base64url，客户端只回传，不解析。
- `ReportSummary` = ReportDTO 去掉 `sections`，附加 `summary_available: true`；不新增其它字段。
- Markdown：按冻结顺序输出「存在且非空」的 13 章；标题层级从 `#` 起；`ETag` 为带引号的 `content_hash`；`If-None-Match` 命中返回 304 且无正文。
- 报告页首屏只发 `GET /reports/{id}`；不预取 Markdown、不预取导出。
- 性能统一口径：先 3 次预热，再取 30 次样本；p95 用 nearest-rank（第 29 个最小值）；记录机器、Python、浏览器版本与数据集规模。
- 前端 `fetch` 与 `/api/v1` 字面量仍只许出现在 `frontend/src/api/`；新增 `api/reports.ts`、`api/exports.ts` 走同一 `client.ts`。
- 占位页 `ReportsPage` / `ReportDetailPage` 文案里的「P5」是错的，P3-04/P3-05 替换时写 P3，不沿用阶段号。

## 2. 任务总表

| 编号 | 任务 | 依赖 | 主要验收 | 独立回退方式 |
| --- | --- | --- | --- | --- |
| P3-01 | 报告只读接口：列表、详情、Markdown | 无 | RPT-01 至 RPT-08；T4、T14 至 T16 | 下线 `/reports` 三个 GET，前端仍回占位 |
| P3-02 | 旧报告导入与幂等台账 | P3-01 | IMP-01 至 IMP-06；T3、T6、T8 | 删除导入脚本与 `0006`，已导入报告可读 |
| P3-03 | 导出服务：PDF 队列、缓存、状态与文件 | P3-01 | EXP-01 至 EXP-08；T9、T12、T13、T17 | 下线导出路由与 `0007`，删 `TA_EXPORTS_DIR` 内容 |
| P3-04 | 报告库 W05 | P3-01 | LIB-01 至 LIB-06；A14、M06 | 报告库路由回占位，后端保留 |
| P3-05 | 阅读器 W06 桌面 | P3-04 | RDR-01 至 RDR-08；A11、A12、T9、T11 至 T13 | 阅读器路由回占位 |
| P3-06 | 阅读器 W06 移动 | P3-05 | RDR-09 至 RDR-12；M04、M06、M07 | 移动样式回桌面单栏，保留深链 |
| P3-07 | 报告动作与重新分析 | P3-03、P3-05 | ACT-01 至 ACT-04；A13 | 隐藏导出与重分析按钮 |
| P3-08 | 兼容投影与旧版打开 | P3-02、P3-03 | CMP-01 至 CMP-05 | 关闭投影开关，删除投影文件 |
| P3-09 | P3 出口验收 | 全部 | 四条出口判据、R-01 至 R-09、性能 | 只增测试与记录 |

新编号说明：RPT、IMP、EXP、LIB、RDR、ACT、CMP 是后端与组件测试编号；R-01 至 R-09 是报告链路的端到端编号；T1 至 T17 沿用冻结清单，A11 至 A14 与 M04、M06、M07 沿用交互走查编号。不得占用契约编号。

## 3. 依赖顺序

```text
P3-01 只读接口
  ├─ P3-02 导入（0006）
  │    └─ P3-08 兼容投影（还需要 P3-03）
  ├─ P3-03 导出（0007）
  │    └─ P3-08
  └─ P3-04 报告库 W05
       └─ P3-05 阅读器桌面
            ├─ P3-06 阅读器移动
            └─ P3-07 动作与重分析（还需要 P3-03）
                 └─ P3-09 出口验收
```

- P3-01 必须先完成。P3-02、P3-03、P3-04 在其后可并行，但迁移是串行资源：建议 P3-02 先合并占 `0006`，P3-03 再合并占 `0007`。
- 每票只动自己那一层：P3-01 不建导出表，P3-02 不渲染页面，P3-03 不改列表，P3-04 不做阅读器，P3-08 不改旧版代码。
- 前端先做库（P3-04）再做阅读器（P3-05），因为阅读器的返回路径依赖库的筛选恢复。

## 4. 逐任务说明

### P3-01 报告只读接口

目标：把已经在 `reports` 表里的报告读出来，且 GET 全程零副作用。

依赖：无。

涉及文件：

- 新增 `backend/app/api/v1/reports.py`：三个 GET 的路由、参数校验、错误映射、ETag 与 304、游标。
- 新增 `backend/app/services/report_query.py`：只读查询与摘要投影；不订阅、不触发对账。
- 新增 `backend/app/services/report_render.py`：`ordered_sections(payload)` 与 `render_markdown(payload)`；后续导出复用同一序列。
- 新增 `scripts/p3_reports_perf.py`：生成 1 万条临时数据并测 p95；P3-09 复跑同一脚本。
- 新增 `tests/backend/test_reports_api.py`、`tests/backend/test_report_markdown.py`。
- 修改 `backend/app/main.py`：挂载 `reports_router`。
- 补 `tests/backend/test_legacy_golden.py` 的 T4：黄金样本正则扫描零命中。

要求：

- `GET /api/v1/reports`：`ticker`（六位）、`date_from` / `date_to`（按 `analysis_date` 闭区间）、`rating`（逗号多值，非法值 400 `invalid_request`，`details.field = "rating"` 且给 `allowed_values`）、`limit`、`cursor`。
- `GET /api/v1/reports/{reportId}`：返回完整 DTO；不存在 404 `report_not_found`。
- `GET /api/v1/reports/{reportId}/markdown`：`text/markdown; charset=utf-8`；`ETag: "<content_hash>"`；`If-None-Match` 命中 304。
- 读取路径不写库、不写文件、不发网络；`summary_available` 固定 `true`。
- 游标解析失败 400 `invalid_request`，`details.field = "cursor"`；格式正确但已无后续行返回空页，不报错。

测试：

- RPT-01：默认 20 条、排序与 null 最后、同秒按 `report_id` 升序。
- RPT-02：股票、日期闭区间、rating 多选三组筛选各自生效；非法 rating 的 400 与 `allowed_values`。
- RPT-03：多页翻页不重不漏；非法游标 400；末页 `next_cursor` 为 null。
- RPT-04：详情字段与库内 `payload` 完全一致；404 分支。
- RPT-05：Markdown 章节顺序 = `ordered_sections`；ETag 等于 `content_hash`；304 无正文。
- RPT-06（T16）：调用前后 `reports`、`jobs`、`job_events` 行数不变，报告文件 mtime 不变，网络计数为 0。
- RPT-07：1 万条元数据下 50 条分页 + 基础筛选 p95 ≤ 500 ms。
- RPT-08：详情 GET p95 ≤ 500 ms（30 样本），外部网络调用 0。
- T4：四份 DTO 样本与旧样本正则扫描 `sk-`、`api_key`、`Bearer`、手机号、邮箱零命中。
- T14/T15：同一 `ticker + analysis_date` 两次成功分析产生两个 `report_id`，旧报告仍可读，列表两条都在且倒序。

回退：删除 `reports.py`、`report_query.py`、`report_render.py` 与两个测试文件，去掉 `main.py` 的挂载；不涉及迁移，已写入的报告行保留。

验收：预检 10 PASS；`pytest tests/backend/test_reports_api.py tests/backend/test_report_markdown.py -q` 全过；旧版健康检查 ok。

### P3-02 旧报告导入与幂等台账

目标：把旧 `full_states_log_*.json` 幂等导入 `reports`，不伪造任务与时间。

依赖：P3-01。

涉及文件：

- 新增 `backend/alembic/versions/0006_legacy_imports.py`。
- 新增 `backend/app/models/legacy_import.py`。
- 新增 `backend/app/services/legacy_import_service.py`：扫描、转换（复用 `report_schema.build_legacy_report`）、入库。
- 新增 `scripts/import_legacy_reports.py`：`--dry-run` 默认，`--apply` 才写；`--root` 可指向临时目录。
- 新增 `tests/backend/test_legacy_import.py`。

要求：见 D3。扫描不读本机真实目录；测试把五份黄金旧样本复制到临时根再跑。

测试：

- IMP-01：同路径同内容扫描两次，`reports` 与 `legacy_imports` 行数都不变。
- IMP-02：同路径改内容后新增一条报告与一条台账。
- IMP-03：导入行四个强制值正确、`job_id` 为 null、`jobs` 与 `job_events` 行数不变。
- IMP-04：ticker 取 `parent.parent.name`，分析日期取文件名；路径层级与 `web/history.py` 一致。
- IMP-05：并发或重复 `--apply` 触发唯一键冲突时忽略并继续，不抛 500。
- IMP-06：`--dry-run` 不建库、不写文件，只打印将导入与将跳过的清单。
- T3、T6、T8 已由 P1-12 覆盖，本票只做回归，不重写。

回退：`alembic downgrade 0005`，删除脚本、服务、模型与测试；已导入的 `reports` 行保留可读，`legacy_imports` 表删除后重复导入会重新建行，需在回退说明里写明。

回退说明：

- `alembic downgrade 0005` 只删 `legacy_imports` 表；已导入的 `reports` 行原样保留，P3-01 的列表、详情与 Markdown 仍可读。
- 回退后再次 `--apply` 会给同一旧文件生成新的 `report_id` 并新增报告行，旧行不会被覆盖或复用；列表里会出现同股票同日期的多个版本。
- 删除 `scripts/import_legacy_reports.py`、`legacy_import_service.py`、`legacy_import.py` 与 `test_legacy_import.py` 后导入能力完全移除，报告接口不受影响。

验收：临时根下导入五份样本，第二次扫描零新增；旧版健康检查 ok。

### P3-03 导出服务

目标：PDF 只在点击后生成，缓存键固定，失败不伤正文。

依赖：P3-01。

涉及文件：

- 新增 `backend/alembic/versions/0007_report_exports.py`、`backend/app/models/report_export.py`。
- 新增 `backend/app/services/export_service.py`（排队、状态机、启动清扫、缓存命中）与 `pdf_renderer.py`（fpdf2 渲染）。
- 新增 `backend/app/api/v1/exports.py`：`POST /reports/{id}/exports/pdf`、`GET /exports/{id}`、`GET /exports/{id}/file`。
- 新增 `tests/backend/test_exports.py`、`tests/backend/test_pdf_renderer.py`。

要求：见 D2、D4、C3。首次 202 + `{export_id, status, poll_url}` + `Location`；命中 200 + `X-Export-Cached: 1`；文件接口未 ready 返回 409 `export_not_ready`。

测试：

- EXP-01：202 → 轮询到 ready → 下载 `application/pdf`。
- EXP-02：同键第二次 200 + `X-Export-Cached: 1`，渲染次数不增加。
- EXP-03：queued/rendering 取文件 409；不存在的 export 404 `export_not_found`。
- EXP-04：渲染失败 → `failed` + `render_failed` + 安全文案；正文 GET 与 Markdown 仍 200。
- EXP-05：模拟残留 `rendering` 行，启动清扫后变 `failed`。
- EXP-06：`long_report` 首次 PDF p95 ≤ 15 s（30 样本）。
- EXP-07：缓存命中下载准备 ≤ 500 ms。
- EXP-08（T17）：`legacy_import` 报告导出物含「导出时补充数据」与补数时间，报告行 `chart_snapshot_status` 仍为 `none`。
- T9/T12/T13：PDF 书签序列 = `ordered_sections`；长报告正文不丢字符；`unsafe_text_report` 不产生可执行内容。

回退：下线三个导出路由，`alembic downgrade 0006`，删除 `TA_EXPORTS_DIR` 下产物；报告行与报告库/阅读器不受影响。

验收：缓存命中不重渲染；失败不伤正文；`pytest tests/backend/test_exports.py -q` 全过。

### P3-04 报告库 W05

目标：筛选、分页、多版本与返回恢复。

依赖：P3-01。

涉及文件：

- 新增 `frontend/src/api/reports.ts`、`frontend/src/features/reports/`（页面、筛选、桌面表格、移动卡片、URL 参数转换）。
- 修改 `frontend/src/lib/query.ts`：新增报告列表查询键。
- 替换 `frontend/src/pages/ReportsPage.tsx` 的占位内容（去掉「P5」）。
- 新增组件测试与 `e2e/reports_e2e.py`。

要求：筛选只在 URL query；行显示评级徽标、名称+代码、分析日期、来源角标、生成时间（未知显示「生成时间未知」）、信号、摘要有无；桌面表格、移动卡片，断点只由 CSS 控制；滚动与已加载页恢复沿用 `JobListPage` 的 `sessionStorage` 方案。

测试：

- LIB-01：默认请求、深链重建、筛选子集与重置。
- LIB-02：翻页不重不漏；进详情后返回恢复 URL、已加载页与滚动位置（A14）。
- LIB-03：`legacy_import` 角标与「生成时间未知」；同股票同日期两版本并列倒序。
- LIB-04：空库、筛选为空、首屏失败、加载更多失败四态。
- LIB-05：移动端不出表格，筛选全屏，44px（M06）。
- LIB-06：打开页面零 `POST`、零行情请求。

回退：报告库路由回占位，删除 `features/reports/` 与 `api/reports.ts`；后端保留。

验收：桌面与移动都能从筛选进列表再进阅读器再返回，筛选与位置不丢。

### P3-05 阅读器 W06 桌面

目标：目录、高亮、深链、决策卡、元信息、安全渲染。

依赖：P3-04。

涉及文件：

- 新增 `frontend/src/features/reports/ReportReaderPage.tsx`、`ReportToc.tsx`、`DecisionCard.tsx`、`ReportMeta.tsx`、markdown 渲染组件。
- 替换 `frontend/src/pages/ReportDetailPage.tsx` 的占位内容。
- 新增组件测试与 E2E 补充。

要求：见 D5。首屏只 `GET /reports/{id}`；目录只列存在且非空的章节；粘性目录与 `IntersectionObserver` 高亮；`#sec-xxx` 深链；决策卡缺失显示「—」；元信息显示生成时间、来源、数据质量、任务链接；Markdown 用 `react-markdown` + `skipHtml`；外链新窗口 + `rel="noopener noreferrer"`。

测试：

- RDR-01：目录顺序 = `ordered_sections`（T9 网页端）。
- RDR-02：滚动高亮与点击跳转；URL hash 同步。
- RDR-03：直接打开 `#sec-debate` 与刷新；`#sec-missing` 停在顶部不报错。
- RDR-04：`missing_fields_report` 决策卡显示「—」，目录不含缺失章节（T11）。
- RDR-05：元信息字段与 DTO 一致；任务链接只在 `job_id` 非空时出现。
- RDR-06：`unsafe_text_report` DOM 无可执行 script/onerror/`javascript:`（T13 网页端）。
- RDR-07：`long_report` 正文不截断（T12 网页端）。
- RDR-08：打开阅读器只发一次详情 GET，零 `POST /exports`、零行情（R-05）。

回退：阅读器路由回占位，删除新增组件；报告库与后端保留。

验收：A11/A12 全过；桌面 1440 下目录粘性且不遮挡正文。

### P3-06 阅读器 W06 移动

目标：抽屉目录、吸底条、44px、不出表格、无页面级横向溢出。

依赖：P3-05。

涉及文件：移动样式与目录抽屉组件；组件测试补齐；E2E 三档视口。

要求：目录是抽屉不是桌面表格；决策卡在正文上方默认收起一行；底部吸底条含导出与重分析（按钮可用性由 P3-07 决定）；跳章后抽屉关闭；页面级 `scrollWidth === clientWidth`。

测试：

- RDR-09：390×844 与 360×800 目录抽屉开合、跳章后关闭（M04）。
- RDR-10：吸底条位于底部导航之上，按钮完整可见（M02）。
- RDR-11：所有触控项 ≥44px（M03）。
- RDR-12：不渲染 `<table>`，页面无横向溢出（M06、M07）。

回退：移动样式回桌面单栏，保留深链与目录。

验收：两档视口实测无溢出、无控制台错误。

### P3-07 报告动作与重新分析

目标：导出四态与重新分析的两种来源。

依赖：P3-03、P3-05。

涉及文件：阅读器动作区、导出轮询 hook、重分析入口；组件测试与 E2E 补充。

要求：导出按钮点击后才 `POST`，四态（排队/渲染/完成/失败）；失败给重试与安全文案；`job_id` 有值走 `retry / same_config`，无值打开启动器并预填股票与分析日期；任务链接只在 `job_id` 非空时出现。

测试：

- ACT-01：未点击前零导出请求；点击一次只发一次 `POST`。
- ACT-02：四态文案与下载按钮；失败重试。
- ACT-03：`job_id` 有值 → 新任务带 `retry_of_job_id`，旧任务不变。
- ACT-04：`job_id` 为 null → 启动器预填，提交后跳新任务。

回退：隐藏导出与重分析按钮，阅读器只读。

验收：A13 全过；导出失败时正文仍可读。

### P3-08 兼容投影与旧版打开

目标：把同股票同日期最新成功报告投影到旧版文件，旧版仍能打开。

依赖：P3-02、P3-03。

涉及文件：

- 新增 `backend/app/services/legacy_projection.py`。
- 新增开关 `TA_LEGACY_PROJECTION`（默认开启，`0` 关闭）。
- 新增 `tests/backend/test_legacy_projection.py`、`e2e/legacy_projection_e2e.py`。

要求：投影路径与 `web/history.py` 完全一致；只投影同键最新报告；先备份再 `os.replace` 原子替换；投影失败只写日志，不改新版报告状态；投影内容从 DTO 回填旧键，无法还原的子结构（辩论/风控 parts）按拼接文本写回，差异记入评审；不修改旧版代码。

测试：

- CMP-01：同键多版本只投影 `generated_at` 最新一条。
- CMP-02：备份文件存在，替换是原子替换；中途失败保留原文件。
- CMP-03：投影失败时报告状态仍 succeeded，正文可读。
- CMP-04：临时 HOME 下启动旧版，能打开投影后的报告并看到同一评级与正文。
- CMP-05：`TA_LEGACY_PROJECTION=0` 时不写任何文件。

回退：关闭开关并删除投影文件；旧版代码不变。

验收：R-08 通过；投影目录层级少一层就判失败。

### P3-09 P3 出口验收

目标：四条出口判据逐条取证。

依赖：全部。

交付：`e2e/e2e_p3.py`（统一脚本，复用 P2 的临时根、dev 后端、preview 三件套）、复跑 P3-01 的 `scripts/p3_reports_perf.py`、`docs/upgrade/reviews/2026-11-XX_P3出口评审.md` 与性能 JSON。

要求：只增测试与记录，不改产品行为；发现缺陷退回对应票修，不在验收票里顺手改。

验收：见第 6 节。

## 5. 测试与证据口径

### 5.1 冻结清单 T1 至 T17 的归属

| 用例 | 现状 | P3 归属 |
| --- | --- | --- |
| T1、T2 | P1-12 已实现 | 预检回归 |
| T3 | P1-12 已实现 | P3-02 回归 |
| T4 | **缺口** | P3-01 补：黄金样本正则扫描零命中 |
| T5 至 T8 | P1-12 已实现 | P3-02 回归，不重写 |
| T9 | 未实现 | P3-03（PDF 书签）+ P3-05（网页目录）+ P3-01（Markdown 标题）三方对照 |
| T10 | P1-12 已实现 | P3-01 用作 ETag 与缓存键，不改算法 |
| T11 | P1-12 已实现 | P3-05 网页端补齐 |
| T12 | 未实现 | P3-05 网页 + P3-03 PDF |
| T13 | 未实现 | P3-05 网页 + P3-01 Markdown + P3-03 PDF 三端都验 |
| T14、T15 | 未实现 | P3-01（新 report_id、旧报告可读、列表两条） |
| T16 | 未实现 | P3-01（GET 前后行数、mtime、网络计数） |
| T17 | 未实现 | P3-03 按 C3 口径实现，P3-09 单列解释 |

### 5.2 端到端编号

| 编号 | 场景 | 归属 |
| --- | --- | --- |
| R-01 | 报告库筛选、翻页、进阅读器后返回：URL、控件、已加载页数、滚动位置 | P3-04 |
| R-02 | 目录跳转、`#sec-xxx` 深链、缺失章节停顶部 | P3-05/P3-06 |
| R-03 | 同股票同日期多版本并列，生成时间倒序，null 最后 | P3-04 |
| R-04 | PDF 四态与缓存命中标记 | P3-07 |
| R-05 | 打开报告全程零 `POST /exports`、零行情、零 PDF 文件新增 | P3-05 |
| R-06 | 390×844 与 360×800：目录抽屉、吸底条、44px、无表格、无横向溢出 | P3-06 |
| R-07 | 旧报告重复导入两次记录数不变，改内容后新增一条 | P3-02 |
| R-08 | 临时 HOME 下旧版能打开投影后的同键最新报告 | P3-08 |
| R-09 | 前端 bundle 变化记录；gzip 比 P2 的 177.92 kB 再增 30 kB 或首屏恶化，按路由拆 `react-markdown` | P3-04/P3-09 |

### 5.3 数据与证据

- 报告与导出测试用临时 `TA_JOBS_DB`、`TA_JOB_REPORTS_DIR`、`TA_EXPORTS_DIR` 与临时 HOME/USERPROFILE。
- 报告列表测试直接插行（照 `test_jobs_list.py` 的做法），写入路径只用于 T14/T15/EXP 的少量行。
- 旧报告导入只用五份黄金样本复制到临时根；不读本机真实报告（当前 22 份，P0 审计时 21 份，数量不是契约）。
- 1 万条性能数据由脚本生成到临时库，样本脚本与结果 JSON 留存，不入库、不提交数据文件。
- 每条证据写测试编号、命令、输出摘要、提交号；没有证据写「未通过」，不写「基本通过」。
- 截图放 `ui_shots_p3/<票号>/`，不入库。

### 5.4 性能

| 指标 | 硬线 | 测法 |
| --- | --- | --- |
| 报告元数据与正文 GET p95 | ≤ 500 ms | 30 样本，1 万条元数据，进程内 TestClient |
| 50 条分页 + 基础筛选 p95 | ≤ 500 ms | 同上，含 ticker 与日期筛选 |
| PDF 缓存命中下载准备 | ≤ 500 ms | 从 `GET /exports/{id}` 到 ready 判定 |
| 固定大报告首次 PDF p95 | ≤ 15 s | `long_report` 样本，30 样本 |
| 外部网络调用 | 0 | 打桩计数 |

## 6. P3 出口判据

P3 完成必须同时满足：

1. 同一份模拟报告，新旧版本的章节集合、顺序与正文一致；网页、Markdown、PDF 三端章节标题序列相同。
2. 打开报告零副作用：不生成 PDF、不请求外部行情、不写文件、不改报告行；GET 前后表行数、文件与网络计数不变。
3. 同股票同日期可以多版本并存：每次成功分析产生独立 `report_id`，重跑不覆盖旧报告，列表按 `generated_at` 倒序且 null 排最后。
4. 重复导出 PDF 命中缓存：同一 `report_id + content_hash + exporter_version` 第二次返回 200 与 `X-Export-Cached: 1`，不重新渲染。

性能线见 5.4；四条判据之外，A11 至 A14、M04、M06、M07 必须全过，预检 10 PASS，旧版冒烟 ok。

## 7. 与冻结契约的对应

| 实现面 | 契约 |
| --- | --- |
| 列表、详情、Markdown、导出、导出状态与文件 | `api-v1.md` 2.1 至 2.6 |
| 零副作用清单 | `api-v1.md` 2.6 |
| DTO 字段与 13 章顺序 | `report-schema-v1.md` 第 2、3 节；`report-schema-v1.json` |
| 旧报告导入的四个强制值 | `report-schema-v1.md` 4.6 |
| 报告库与阅读器结构 | `core-wireframes.md` 第 5、6 节 |
| 路由、返回、深链、刷新 | `routes.md` 第 2 节第 2、3、8 条 |
| 一致性用例 | `report-consistency-tests.md` T1 至 T17 |
| 走查 | `interaction-checklist.md` A11 至 A14、M04、M06、M07 |
| 错误码 | `error-codes-v1.md`：`invalid_request`、`report_not_found`、`export_not_found`、`export_not_ready` |
| 冻结与解冻 | `FREEZE-v1.md` 第 4 节 |

## 8. 留给后续阶段

| 内容 | 阶段 | P3 的处理 |
| --- | --- | --- |
| 生成日期筛选、`signal` 筛选 | P4 或解冻 | 见 C1、C2；P3 不做 |
| 投影失败的 UI 警告 | P6 或解冻 | 见 D6；P3 只写日志 |
| 导出产物清理与保留策略 | P6 | P3 只做按需生成与缓存，不做 GC |
| 市场、股票工作区 | P4 | 占位页 |
| 日志、设置、主题与可访问性收尾 | P5 | 占位页 |
| 默认入口切换、双栈灰度 | P6 | 旧版仍是默认写入口 |
| 报告导出图表快照 | P4/P6 | P3 只做正文 PDF 与补数标注，不生成图表 |
