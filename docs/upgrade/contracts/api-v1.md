# 接口契约 v1：任务、报告与市场数据（api-v1）
版本：v1（2026-10-29 冻结）

日期：2026-10-29
状态：冻结候选（Day 4 交付）
配套文件：`market-data-envelope-v1.json`（数据信封 Schema）、`sse-events-v1.md`（事件流）、`error-codes-v1.md`（错误字典）、`job-state-machine.md`、`idempotency-conflicts.md`、`report-schema-v1.md`

目标：前端只依赖本契约就能画完所有页面，不读 LangGraph 原始对象、不解析 markdown 猜状态、不自己决定按钮能不能点。

---

## 0. 通则

| 项 | 规定 |
| --- | --- |
| 前缀 | 所有接口在 `/api/v1` 下，版本号进路径 |
| 编码 | 请求与响应均为 `application/json; charset=utf-8`，Markdown 与 PDF 接口除外 |
| 字段命名 | `snake_case`，沿用 `report-schema-v1`，不做 camelCase 转换 |
| 时间 | 时间点用 ISO8601 带时区，如 `2026-10-29T09:31:05+08:00`；日期用 `YYYY-MM-DD` |
| 请求 ID | 每个响应带 `X-Request-Id`；客户端可自带，服务端生成时优先用自带的 |
| 未知字段 | 响应新增字段客户端必须忽略；请求含白名单外字段一律 422，不静默丢弃 |
| 分页 | `limit` 默认 20、最大 100；`cursor` 为不透明字符串；响应 `{items, next_cursor}`，`next_cursor` 为 null 表示到底 |
| 金额与百分比 | 价格单位元；`change_pct` 为百分数原值（`2.35` 表示 +2.35%）；`amount_wan` 单位万元；资金流各项单位元 |
| 鉴权 | P0 为本机单用户，不做鉴权；契约保留 `unauthorized` 错误码，未来加鉴权不改路径 |
| 未实现接口 | P0 只冻结市场接口结构、不实现；调用返回 501 `not_implemented`，不用 404 冒充 |

数据类接口（第 3 章）统一使用 `market-data-envelope-v1` 信封；任务与报告接口不使用信封，直接用错误体。

数据源失败与接口失败的分工：

- 数据源取不到数据：HTTP 200，信封 `status = error` 或该区块 `error`，`error_code` 用 `upstream_timeout` 等数据源码。
- 请求本身不合法、对象不存在、状态冲突：HTTP 4xx/5xx，错误体见 `error-codes-v1.md`。

前端据此区分「接口坏了」与「这只票今天没数据」，两种情况显示不同文案。

---

## 1. 任务接口

### 1.1 两个任务形态

`JobSummary` 用于列表，`JobDetail` 用于详情与 SSE 首帧。两者字段一致，只有 `stages` 一处差别：列表不带 12 个阶段的明细。

| 字段 | 类型 | 必需 | 说明 |
| --- | --- | --- | --- |
| `job_id` | string(uuid) | 是 | 创建时生成，永不复用 |
| `status` | enum | 是 | 九个状态之一，见 `job-state-machine.md`；文案映射用 `semantic-dictionary.md` 的表，不用状态字符串拼中文 |
| `pending_action` | enum: pause, cancel, null | 是 | 已受理但未生效的控制请求；与 `pause_requested / cancel_requested` 状态一一对应 |
| `ticker_code` | string(6) | 是 | 已归一化，如 `000629` |
| `ticker_name` | string 或 null | 否 | 解析不到名称时为 null，前端回退显示代码，不编造 |
| `analysis_date` | string(YYYY-MM-DD) | 是 | 分析标的日期 |
| `created_at` | ISO8601 | 是 | |
| `updated_at` | ISO8601 | 是 | 任何字段变化都更新 |
| `started_at` | ISO8601 或 null | 是 | 首次进入 running 的时间 |
| `finished_at` | ISO8601 或 null | 是 | 进入任一终态的时间 |
| `current_stage` | object 或 null | 是 | `{id, name, index, total, status}`；queued 与终态为 null |
| `stages` | array | 仅详情 | 固定 12 项，顺序固定，见 1.2 |
| `stats` | object | 是 | `{model_calls, tokens_in, tokens_out, elapsed_ms}`；未开始全为 0 |
| `report_id` | string(uuid) 或 null | 是 | 仅 succeeded 且报告已提交时非空 |
| `error` | object 或 null | 是 | `{code, message}`，只放安全文案，不使用堆栈 |
| `config_digest` | string | 是 | 配置指纹，续跑时用于匹配 |
| `graph_version` | string | 是 | 图版本，续跑时用于匹配 |
| `retry_of_job_id` | string 或 null | 是 | 重试来源 |
| `resume_of_job_id` | string 或 null | 是 | 续跑来源 |
| `resume_from_stage` | string 或 null | 是 | 续跑起始阶段 id |
| `allowed_actions` | array<enum> | 是 | 见 1.6；前端按钮只按它渲染，不自己推状态表 |
| `links` | object | 是 | `{self, events, report}`，report 为 null 当无报告 |
| `reconcile_notes` | array | 仅详情 | 启动对账发现的未登记产物或报告，元素为 `{code, message, at}`；只入库不广播，不占 SSE 序号；无则为空数组 |

### 1.2 阶段 id（固定 12 个）

来源 `web/progress.py::PIPELINE_STAGES`。顺序即执行顺序，`index` 从 1 开始。

| 序号 | id | 名称 |
| --- | --- | --- |
| 1 | market | 技术分析 |
| 2 | social | 情绪分析 |
| 3 | news | 新闻舆情 |
| 4 | fundamentals | 基本面 |
| 5 | policy | 政策分析 |
| 6 | hot_money | 游资追踪 |
| 7 | lockup | 解禁监控 |
| 8 | quality_gate | 质量门控 |
| 9 | debate | 多空辩论 |
| 10 | trader | 交易决策 |
| 11 | risk | 风控评估 |
| 12 | pm | 最终决策 |

阶段状态枚举：`pending | active | done | failed | skipped`。`skipped` 只由阶段开关关闭导致，前端显示「已跳过」，不显示为失败。

### 1.3 创建任务

```text
POST /api/v1/jobs
Idempotency-Key: <uuid>        （必需）
```

请求体：

```json
{
  "ticker": "000629",
  "analysis_date": "2026-10-29",
  "config": {
    "llm_profile": "deepseek-default",
    "parallel_analysts": true,
    "stage_toggles": {"policy": true, "hot_money": true, "lockup": true}
  }
}
```

| 字段 | 必需 | 说明 |
| --- | --- | --- |
| `ticker` | 是 | 6 位代码或中文名；服务端按 `resolve_ticker` 归一化后回填 `ticker_code`。中文名模糊匹配到多只时报 422 `ticker_ambiguous`，`details.candidates` 最多 5 个 |
| `analysis_date` | 是 | 不接受未来日期，报 422 `invalid_date` |
| `config` | 是 | 只允许白名单键：`llm_profile`、`parallel_analysts`、`stage_toggles`。多一个键报 422 `config_unknown_key` |
| `config.llm_profile` | 是 | 服务端预置配置的 id，如 `deepseek-default`；非法值报 422 `config_invalid_value` 并返回允许值 |
| `config.parallel_analysts` | 否 | 缺省取服务端默认值 |
| `config.stage_toggles` | 否 | 缺省全部开启；关掉的阶段在 `stages` 里显示 `skipped` |

客户端不能提交 `backend_url`、`api_key`、模型名以外的服务端配置——这三类一律按 `config_unknown_key` 拒绝。

响应按 `idempotency-conflicts.md` 第 1 节的五步判定：

| 情况 | 状态码 | 说明 |
| --- | --- | --- |
| 新建成功 | 201 | 返回 `JobDetail`，`status = queued` |
| 同键同体重放 | 200 | 返回原 job，`Idempotency-Replayed: 1` 响应头 |
| 同键不同体 | 409 `idempotency_mismatch` | |
| 无键但同活动指纹 | 200 | 返回该 job，响应头 `X-Existing-Job: <job_id>` |
| 同票同日不同配置且已有活动任务 | 409 `active_conflict` | `details.active_job_id` 给出当前活动任务，由用户决定等待或取消 |
| 没带 `Idempotency-Key` | 400 `idempotency_key_required` | |

`Idempotency-Key` 作用域为创建接口，保留 24 小时；24 小时内重放返回当时的响应体与状态码。

### 1.4 任务列表

```text
GET /api/v1/jobs?status=running,failed&ticker=000629&date_from=2026-09-01&date_to=2026-10-29&active=true&limit=20&cursor=...
```

- `status` 可逗号分隔多值；`ticker` 精确匹配代码。
- `date_from` / `date_to` 按 `analysis_date` 闭区间过滤；格式错误或晚于今天报 422 `invalid_date`。
- `active=true` 只返回非终态任务（queued、running、pause_requested、paused、cancel_requested），供活动任务条使用。它与 `status` 互斥，同时出现报 400 `invalid_request`，`details.field = "active"`。
- 排序固定 `created_at` 倒序；同秒内按 `job_id` 升序，保证分页稳定。
- 返回 `{items: JobSummary[], next_cursor}`。
- 该接口零副作用，不改变任何 job 状态。

### 1.5 任务详情

```text
GET /api/v1/jobs/{jobId}
```

- 返回 `JobDetail`。
- `jobId` 不存在返回 404 `job_not_found`；**不自动创建任务**（旧版 `get_or_create_job` 的行为在本契约中废止）。
- 零副作用：不触发对账、不改状态、不发事件。

### 1.6 控制接口：受理不等于生效

```text
POST /api/v1/jobs/{jobId}/actions
```

请求体：

```json
{"action": "pause"}
```

`action` 枚举：`pause | resume | cancel`。

语义：这三个动作都是异步请求。服务端只写请求标记，真正生效落在阶段边界（暂停、取消）或 Worker 空闲时（继续）。

| 结果 | 状态码 | 响应 |
| --- | --- | --- |
| 已受理 | 202 | `{job_id, accepted: true, action, accepted_at, expected_effect: "at_stage_boundary", status}` |
| 重复提交同一动作 | 200 | `{job_id, accepted: false, reason: "already_pending", status}`，不写第二条请求 |
| 状态不允许该动作 | 409 `illegal_transition` | `details.from / details.action / details.rule` 指向非法转换编号（I01–I11） |

按钮可用性完全由 `allowed_actions` 决定：

| 状态 | allowed_actions |
| --- | --- |
| queued | cancel |
| running | pause, cancel |
| pause_requested | cancel |
| paused | resume, cancel |
| cancel_requested | 空数组 |
| cancelled | reanalyze |
| succeeded | retry, reanalyze |
| failed | retry, reanalyze |
| interrupted | resume_from_checkpoint, retry, reanalyze |

六个动作对应的真实调用：

| allowed_actions 项 | 调用 |
| --- | --- |
| pause / resume / cancel | `POST /jobs/{id}/actions` |
| retry | `POST /jobs/{id}/retry`，`mode = same_config` |
| resume_from_checkpoint | `POST /jobs/{id}/retry`，`mode = resume_from_checkpoint` |
| reanalyze | `POST /jobs`，用当前界面配置，全新幂等键 |

### 1.7 重试与续跑：创建新任务

```text
POST /api/v1/jobs/{jobId}/retry
Idempotency-Key: <uuid>        （必需）
```

请求体：

```json
{"mode": "same_config"}
```

| `mode` | 适用状态 | 新 job 字段 | 原 job |
| --- | --- | --- | --- |
| `same_config` | failed, interrupted, succeeded | `retry_of_job_id = 原 id`，配置取原 job 深拷贝 | 保持原终态 |
| `resume_from_checkpoint` | interrupted | `resume_of_job_id = 原 id`，`resume_from_stage` = 首个未完成阶段 | 保持 `interrupted` |

`paused` 的「继续」不走本接口，走 1.6 的 `resume` 动作：同一个 job、同一个 id，这是暂停与中断的关键区别。暂停状态下检查点缺失时，对账已把它改判 `interrupted`，届时才用 `resume_from_checkpoint`。

- 该接口会产生新的模型费用，因此必须带 `Idempotency-Key`，判定顺序与 1.3 相同。
- 报告页的「重新分析」不另设接口：`report.job_id` 非空时调用本接口 `mode = same_config`，配置来源即原任务；历史导入报告 `job_id` 为 null，改为打开启动器并预填股票与分析日期。
- `resume_from_checkpoint` 时 `config_digest` 或 `graph_version` 不匹配，返回 409 `resume_fingerprint_mismatch`，界面只给「重新分析」。
- 成功返回 201 + 新 `JobDetail`；原 job 任何字段不变。

### 1.8 元信息与配置选项

```text
GET /api/v1/meta/options
```

返回前端表单与设置页需要的枚举和只读状态，避免前端硬编码服务端配置：

```json
{
  "app_version": "0.9.0",
  "server_time": "2026-10-29T15:04:05+08:00",
  "default_analysis_date": "2026-10-29",
  "llm_profiles": [{"id": "deepseek-default", "label": "DeepSeek 默认"}],
  "stage_toggles": [{"id": "policy", "label": "政策分析", "default": true}],
  "limits": {"max_active_jobs": 1, "max_date_ahead_days": 0},
  "journal": {"available": false, "entry_url": "http://127.0.0.1:8502", "reason": "not_running"},
  "write_mode": "legacy",
  "contract_version": "api-v1"
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `app_version` | string | 应用版本，设置页「关于」显示 |
| `server_time` | ISO8601 | 带 `+08:00` 的服务器时间 |
| `default_analysis_date` | string(YYYY-MM-DD) | 启动器默认分析日期，按北京时间取当天；前端不得用本地时区自行推导 |
| `journal.available` | bool | 交易日志服务是否可用，依据 TCP 连通加健康端点身份校验 |
| `journal.entry_url` | string | 日志应用入口地址，不可用时也返回，用于手动打开 |
| `journal.reason` | enum 或 null | `not_running`、`not_installed`、`probe_failed`；可用时为 null |
| `write_mode` | string enum | 当前唯一分析写入者，可选，`legacy` 或 `next`；缺省按 `legacy` 理解；旧客户端忽略后行为不变 |

`journal` 只做探活，**不自动拉起日志服务**；启动必须由用户在日志页手动执行。

零副作用。本契约在计划清单之外补充的接口有 2.5 导出状态、1.8 元信息、1.10 阶段报告，理由都写在评审记录里。

### 1.9 任务事件流

```text
GET /api/v1/jobs/{jobId}/events
```

只读事件流，只接受 GET，`Accept: text/event-stream`，重连带 `Last-Event-ID`。订阅与续传不写任何表、不创建任务。事件类型、首帧快照、断线续传、心跳、限频与终态关闭全部见 `sse-events-v1.md`。

### 1.10 阶段报告

```text
GET /api/v1/jobs/{jobId}/stages/{stageId}
```

任务详情页展开某个阶段时读取该阶段的产出。只读，零副作用：不触发对账、不改状态、不发事件、不补跑阶段。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `job_id` | string(uuid) | |
| `stage_id` | string | 1.2 的固定 12 个之一 |
| `stage_name` | string | 中文名 |
| `index` | int | 1–12 |
| `status` | enum | 与 `JobDetail.stages` 中该项一致 |
| `markdown` | string 或 null | 阶段产出原文；未产出时为 null |
| `truncated` | bool | 超过 128 KiB 时服务端截断，保留前 128 KiB |
| `full_length` | int | 原文总字符数；未产出为 0 |
| `updated_at` | ISO8601 或 null | 该阶段产出写入时间 |

- `pending`、`active`、`skipped` 阶段返回 200，`markdown = null`，不是错误。
- `jobId` 不存在返回 404 `job_not_found`；`stageId` 不在固定 12 个之内返回 404 `stage_not_found`。
- 阶段报告与最终报告无关：即使任务失败或中断，已完成阶段的报告仍可读取。

---

## 2. 报告接口

报告结构一律用 `report-schema-v1` 的 ReportDTO，本契约不再重复字段。

### 2.1 报告列表

```text
GET /api/v1/reports?ticker=000629&date_from=2026-09-01&date_to=2026-10-29&rating=Buy,Sell&limit=20&cursor=...
```

- `date_from` / `date_to` 按 `analysis_date` 闭区间过滤；`generated_at` 为 null 的历史报告同样按分析日期参与筛选。
- `rating` 可逗号分隔多值，取值 `Buy | Overweight | Hold | Underweight | Sell | unknown`；非法值报 400 `invalid_request`，`details.field = "rating"` 并给 `allowed_values`。
- 返回 `{items: ReportSummary[], next_cursor}`，`ReportSummary` 是 ReportDTO 去掉 `sections` 的部分，附加 `summary_available: true`。

排序：`generated_at` 倒序，`generated_at` 为 null 的历史报告排最后（与 `report-schema-v1` 第 4.2 条一致）。

### 2.2 报告详情

```text
GET /api/v1/reports/{reportId}
```

- 返回完整 ReportDTO。
- 零副作用：不拉行情、不生成 PDF、不写文件、不改 `chart_snapshot_status`。
- `reportId` 不存在返回 404 `report_not_found`。

### 2.3 报告 Markdown

```text
GET /api/v1/reports/{reportId}/markdown
```

- 返回 `text/markdown; charset=utf-8`，内容由同一份 ReportDTO 生成。
- 响应头 `ETag: "<content_hash>"`；带 `If-None-Match` 且命中时返回 304，无正文。
- 零副作用。

### 2.4 导出 PDF

```text
POST /api/v1/reports/{reportId}/exports/pdf
```

请求体（可选）：

```json
{"template": "default"}
```

`template` 只允许服务端白名单值。响应：

| 情况 | 状态码 | 正文 |
| --- | --- | --- |
| 首次导出 | 202 | `{export_id, status: "queued", poll_url}`，`Location` 指向 2.5 |
| 命中缓存 | 200 | 同结构，`status` 可能已是 `ready`，响应头 `X-Export-Cached: 1` |

缓存键固定为 `report_id + content_hash + exporter_version`，命中不重新渲染。这是唯一允许写文件的报告接口，且必须由用户显式触发。

### 2.5 导出状态与文件（补充接口）

```text
GET /api/v1/exports/{exportId}
GET /api/v1/exports/{exportId}/file
```

状态对象：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `export_id` | string(uuid) | |
| `report_id` | string(uuid) | |
| `status` | enum: queued, rendering, ready, failed | |
| `download_url` | string 或 null | 仅 ready 时非空，形如 `/api/v1/exports/{id}/file`，**不是**服务器文件系统路径 |
| `error` | object 或 null | `{code, message}` |
| `created_at` | ISO8601 | |
| `ready_at` | ISO8601 或 null | |
| `exporter_version` | string | 参与缓存键 |

`/file` 仅在 ready 时返回 `application/pdf`，其余状态 409 `export_not_ready`。

### 2.6 报告接口零副作用清单

以下行为在契约中禁止，实现与测试都按「调用前后报告表、job 表、事件表、文件系统 mtime 均不变」断言：

- 打开报告详情或列表时请求行情、生成图表快照。
- 打开报告时生成或续跑 PDF。
- Markdown 接口写临时文件。
- 任何 GET 改变 `chart_snapshot_status`、`generated_at`、`content_hash`。

---

## 3. 市场与股票接口

P0 不实现本章接口，只冻结结构与错误语义。所有响应使用 `market-data-envelope-v1` 信封，五份样本在 `tests/fixtures/upgrade/`：`market_ok.json`、`market_empty.json`、`market_error.json`、`market_stale.json`、`market_partial.json`。

### 3.0 信封与陈旧判定

信封最小字段：`status`（`ok | empty | error | stale`）、`source`、`as_of`、`fetched_at`、`is_stale`、`error_code`、`data`。完整定义见 Schema。

三条不可混淆的规则：

1. `status = empty`：数据源正常响应但今天没有数据（非交易日、板块无成分股、新闻为空）。`data = null`，`error_code = null`，`as_of = null`。
2. `status = error`：数据源失败且无法给出可用数据。`data = null`，`error_code` 必填（数据源码），`as_of = null`。
3. `status = stale`：有数据但不可信或过期。`data` 非空，`as_of` 非空，`is_stale = true`，`stale_reason` 必填。

`is_stale` 恒等于 `status == "stale"`；保留该布尔字段是为了客户端不必做字符串比较。

`as_of` 的取值：单区块接口取该块的数据时间；多区块接口取主区块的时间（快照为 `quote`，市场概览为 `indices`），主区块不可用时取第一个可用区块。逐块时间始终在 `blocks` 里，顶层只是给列表和标题用。

多区块接口（快照、市场概览）必须给 `blocks`，每块独立状态；部分成功用 `partial = true` 加 `failed_blocks` 表达，不能用总状态掩盖某一块的失败。合并规则：

| 各区块状态 | 顶层 status | partial |
| --- | --- | --- |
| 全部 ok | ok | false |
| 全部 empty | empty | false |
| 全部 error | error | false |
| 至少一个可用（ok/stale），其余 empty 或 error | 按可用区块：有 stale 则 stale，否则 ok | 有 empty/error 区块时为 true |
| 可用区块里 ok 与 stale 混合 | stale | 按需 |

`stale_reason` 枚举：`ttl_exceeded`（超过该接口的新鲜度阈值）、`trading_day_mismatch`（数据日期早于最近交易日）、`upstream_fallback`（用了备用数据源）。

各接口的新鲜度阈值（超过即 stale，仍然返回数据）：

| 接口 | stale_after |
| --- | --- |
| 股票搜索 | 24 小时（名称表每日重建） |
| 快照·行情块 | 60 秒 |
| 快照·估值块 | 4 小时 |
| 快照·板块块 | 24 小时 |
| 日/周/月 K 线 | 5 分钟 |
| 分时（当日） | 30 秒 |
| 分时（历史日期） | 1 小时 |
| 个股新闻 | 5 分钟 |
| 市场概览·指数块 | 10 秒 |
| 市场概览·北向块 | 30 秒 |
| 行业排名 | 5 分钟 |
| 行业成分股 | 2 分钟 |
| 强势股 | 1 小时 |
| 资金流 | 60 秒 |
| 快讯 | 2 分钟 |

### 3.1 股票搜索

```text
GET /api/v1/market/search?q=宁德&limit=10
```

`data`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items` | array | `{ticker_code, ticker_name, market}`，market ∈ sh, sz, bj |
| `truncated` | bool | 命中数超过 limit 时为 true |

搜索不做消歧报错：多只命中时如实列出。消歧报错只发生在创建任务（1.3 的 `ticker_ambiguous`）。`q` 为空返回 `empty`，不报错。

### 3.2 个股快照

```text
GET /api/v1/stocks/{ticker}/snapshot
```

三块：`quote`（腾讯实时）、`valuation`（一致预期 EPS、动态 PE、PEG、消化估值年数）、`sector_blocks`（百度行业/概念/地域）。

`data.quote` 字段沿用旧代码 `tencent_quote` 的键：`name, price, last_close, open, high, low, change_pct, change_amt, amount_wan, turnover_pct, pe_ttm, pb, amplitude_pct, float_mcap_yi, mcap_yi, limit_up`。

`data.valuation`：`eps_forecast`、`pe_forward`、`peg`、`pe_digestion_years`，任一无法计算时为 null，不用 0 或空字符串冒充。

`data.sector_blocks`：`{industry: [], concept: [], region: []}`，每项 `{name, change_pct, desc}`。

`data.units`：`{price: "元", amount: "万元", mcap: "亿元"}`。

三块可分别 stale 或 error；例如行情块 ok、板块块超时，则顶层 `status = ok`、`partial = true`、`failed_blocks = ["sector_blocks"]`。

### 3.3 K 线与分时

```text
GET /api/v1/stocks/{ticker}/kline?period=day&limit=120
GET /api/v1/stocks/{ticker}/intraday?date=2026-10-29
```

K 线参数：`period ∈ day | week | month`，`limit` 1–5000，默认 120。

K 线 `data`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `adjust` | string | 固定 `none`（不复权）；未来加复权必须新字段 `adjust_mode` |
| `bars` | array | `{date, open, high, low, close, volume, amount}`，`date` 为 YYYY-MM-DD，按时间升序；`amount` 取不到时为 null |
| `units` | object | `{price: "元", volume: "手", amount: "元"}` |

分时 `date` 省略时取最近交易日。`data`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `date` | string | 实际交易日，可能不同于请求日期（非交易日回退） |
| `points` | array | `{time: "HH:MM", price, volume, avg_price}`, `avg_price` 可为 null |
| `session_gaps` | array | 固定 `[["11:30", "13:00"]]`，前端据此断开午休 |
| `units` | object | 同上 |

历史分时超出数据源保留期时返回 `empty`，不是 `error`。

### 3.4 个股新闻与股票报告

```text
GET /api/v1/stocks/{ticker}/news?limit=20
GET /api/v1/stocks/{ticker}/reports?limit=20&cursor=...
```

新闻 `data.items`：`{title, content, published_at, source, url}`，`data.untrusted = true`。字段内容一律视为不可信文本：前端只做纯文本渲染，不执行 HTML、不解析其中的 URL 协议以外的内容。

股票报告与 `GET /api/v1/reports?ticker=` 同构，只是把 ticker 放进了路径。

### 3.5 市场概览

```text
GET /api/v1/market/overview
```

`data`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `market_session` | enum: pre_open, trading, lunch_break, closed | 服务端按北京时间判定，前端不自己算 |
| `indices` | array | `{code, name, price, change_pct, change_amt}`，固定三大指数 |
| `northbound` | object 或 null | `{points: [{time, hgt_yi, sgt_yi}], latest: {hgt_yi, sgt_yi} 或 null}` |

两块独立状态：指数正常、北向源失败时，顶层 ok + partial + `failed_blocks = ["northbound"]`。

### 3.6 行业、强势股、资金流、快讯

```text
GET /api/v1/market/industries?top=20
GET /api/v1/market/industries/{boardCode}/stocks?limit=10
GET /api/v1/market/strong-stocks?date=2026-10-29
GET /api/v1/stocks/{ticker}/fund-flow
GET /api/v1/market/newsflash?limit=30
```

行业 `data`：`{top: [], bottom: [], total}`，行结构 `{rank, name, code, change_pct, up_count, down_count, leader, leader_change}`。`bottom` 为涨幅末位，按与 `top` 相同的排序规则反向取。

行业成分股 `data.items`：`{code, name, price, change_pct}`，停牌等取不到价格时为 null。

强势股 `data.items`：`{ticker_code, name, reason, market, change_pct, change_amt, close, turnover_pct}`。非交易日返回 `empty` 并附 `data = null`，界面文案「非交易日或盘后未更新」，不显示成加载失败。

资金流 `data.items`：`{time, main_net, small_net, mid_net, large_net, super_net}`，单位元，按时间升序。

快讯 `data.items`：`{title, content, published_at}`，`untrusted = true`。

---

## 4. 错误与安全边界

### 4.1 错误体

非 2xx 响应统一：

```json
{
  "error": {
    "code": "active_conflict",
    "message": "该股票今日已有进行中的分析",
    "request_id": "req_01J...",
    "details": {"active_job_id": "..."}
  }
}
```

`message` 是可直接展示给用户的安全文案；`details` 只放白名单字段（任务 id、字段名、允许值），不放内部异常文本。

### 4.2 安全规则（实现与测试都按此断言）

1. 不返回服务端堆栈、异常类名、代码行号。
2. 不返回任何 API Key、环境变量、内部主机名。
3. 不返回文件系统路径；下载一律给 `/api/v1/...` 形式的 URL。
4. 不接受前端提交 `backend_url`、`api_key`、任意模型接口地址；模型与 Base URL 由服务端 `llm_profile` 白名单决定。
5. 报告正文与外部文本默认不可信：报告正文按清洗后的 markdown 传递，前端渲染必须禁用原始 HTML；新闻、快讯、题材归因标 `data.untrusted = true`，按纯文本渲染，不执行脚本、不自动加载外部图片。
6. 错误响应也带 `X-Request-Id`，与日志可对账。

### 4.3 前端不得推断的事项

- 不解析 `sections` 文本猜评级、目标价、止损：只用 `meta.rating / price_target / stop_reference / time_horizon`。
- 不用 `status` 自己推按钮：只用 `allowed_actions`。
- 不把 `empty` 当 `error`，不把 `stale` 当 `ok`：三者在信封里是三个值，文案见 `semantic-dictionary.md`。
- 不在 SSE 断线时调用创建接口：重连只带 `Last-Event-ID`（见 `sse-events-v1.md`）。

---

## 5. 验收映射

| Day 4 验收项 | 本契约对应条款 |
| --- | --- |
| 前端不读 LangGraph 原始对象即可做页面设计 | 1.1 的 `stages` 与 `allowed_actions`、2.2 的 ReportDTO、3.x 的固定 `data` 结构 |
| 所有付费动作有幂等规则 | 1.3、1.7 强制 `Idempotency-Key`；判定顺序引用 `idempotency-conflicts.md` |
| 报告读取接口明确无副作用 | 2.2、2.3、2.6 |
| 空、错误、陈旧不可混淆 | 3.0 三条规则 + `market-data-envelope-v1.json` 的条件约束 + 五份样本 |
| SSE 重连没有创建任务语义 | `sse-events-v1.md` 第 4 节；本契约 2.6 与 `idempotency-conflicts.md` 第 2 节 |
