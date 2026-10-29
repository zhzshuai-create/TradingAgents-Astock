# SSE 事件流契约 v1（sse-events-v1）

日期：2026-10-29
状态：冻结候选（Day 4 交付）
配套：`api-v1.md`（JobDetail 字段）、`job-state-machine.md`（状态与转换）、`crash-boundaries.md`（B5 补发事件）、`error-codes-v1.md`

目标：任务页的进度、阶段、统计和完成通知只走一条只读事件流；断线重连只补历史，绝不产生新任务。

---

## 1. 端点与握手

```text
GET /api/v1/jobs/{jobId}/events
Accept: text/event-stream
Last-Event-ID: 128        （可选，重连时带）
```

| 情况 | 响应 |
| --- | --- |
| 正常订阅 | 200，`Content-Type: text/event-stream; charset=utf-8`，`Cache-Control: no-cache`，`X-Accel-Buffering: no` |
| `jobId` 不存在 | 404 `job_not_found` |
| 用 POST 或其他方法 | 405 `method_not_allowed` |
| `Accept` 不是事件流 | 400 `invalid_request` |
| `Last-Event-ID` 非整数 | 400 `invalid_request` |
| 游标超出保留窗口 | 410 `sse_cursor_expired`（见第 4 节） |

一次连接只订阅一个任务，不做多任务复用。P0 无鉴权，跨域默认不开。

---

## 2. 帧格式

标准 SSE 帧，`data` 为单行 JSON：

```text
retry: 3000

id: 128
event: status_changed
data: {"seq":128,"job_id":"5b1c...","type":"status_changed","at":"2026-10-29T10:31:07+08:00","payload":{"from":"running","to":"succeeded","reason":"worker","detail":null,"pending_action":null,"error":null}}

: ping
```

规则：

- 每条事件帧的 `event` 行与 `data.type` 必须相同；客户端用哪个都行，二者不等即为服务端缺陷。
- 除心跳外，每条事件的 `data` 都含五个字段：`seq`、`job_id`、`type`、`at`、`payload`。
- `seq` 在同一个 job 内从 1 开始严格递增且连续，不跳号、不复用。
- 心跳是一行注释 `: ping`，不占 `seq`，不影响 `Last-Event-ID`。
- 服务端在流开始时先发 `retry: 3000`（毫秒），客户端按此间隔自动重连。

---

## 3. 六类事件

| type | 何时发 | 载荷 |
| --- | --- | --- |
| `snapshot` | 连接建立、或重连后需要重建视图时，作为首帧 | `{job: JobDetail, last_seq: int}` |
| `stage_changed` | 阶段开始、结束、失败、跳过 | 见 3.1 |
| `stats` | 统计值变化且满足限频；终态前必发一条 | 见 3.2 |
| `status_changed` | 任何状态转换（T01–T19、对账改判） | 见 3.3 |
| `report_ready` | 报告提交成功，紧跟在 succeeded 的 `status_changed` 之后 | 见 3.4 |
| `error` | 传输层或服务端内部错误，不改变任务状态 | 见 3.5 |

### 3.1 stage_changed

```json
{
  "stage_id": "news",
  "stage_name": "新闻舆情",
  "stage_status": "done",
  "index": 3,
  "total": 12,
  "started_at": "2026-10-29T10:02:11+08:00",
  "finished_at": "2026-10-29T10:06:48+08:00",
  "duration_ms": 277000
}
```

`stage_status` 枚举：`started | done | failed | skipped`。`skipped` 只来自阶段开关关闭，界面显示「已跳过」，不算失败。

### 3.2 stats

```json
{"model_calls": 14, "tokens_in": 182430, "tokens_out": 41208, "elapsed_ms": 612000}
```

### 3.3 status_changed

```json
{
  "from": "running",
  "to": "pause_requested",
  "reason": "user",
  "detail": "pause",
  "pending_action": "pause",
  "error": null
}
```

| 字段 | 说明 |
| --- | --- |
| `reason` | `user`（用户动作）、`worker`（执行推进）、`reconcile`（启动对账改判） |
| `detail` | 补充说明，如 `lease_expired`、`checkpoint_missing`、`pause`、`cancel`；无则 null |
| `pending_action` | 新状态对应的未决控制请求，没有则 null |
| `error` | 仅 `to = failed` 时非空：`{code, message}`，安全文案 |

### 3.4 report_ready

```json
{"report_id": "7f2a...", "content_hash": "sha256:9c1e...", "rating": "Overweight", "signal": "Buy", "url": "/api/v1/reports/7f2a..."}
```

`rating` 与 `signal` 取自 ReportDTO 的 `meta`，前端不解析正文。

### 3.5 error

```json
{"code": "internal_error", "message": "事件流暂时不可用", "request_id": "req_01J...", "fatal": true}
```

`fatal = true` 时服务端发完即关闭连接，客户端应 GET 一次任务详情重建视图；`fatal = false` 表示流仍可用，客户端不必重连。

任务执行失败不走这里：那是 `status_changed` 到 `failed`，`payload.error` 带错误码。两者混用会让「任务失败」和「网络断了」在界面上分不清。

---

## 4. 首帧、续传与保留窗口

### 4.1 首帧快照

不带 `Last-Event-ID` 连接时，服务端先发一条 `snapshot`：

- `payload.job` 是完整的 JobDetail（含 12 个阶段），前端据此直接画出进度条与按钮。
- `payload.last_seq` 是当前事件表的最大序号，没有事件时为 0。
- `snapshot` 的 `seq` 等于 `last_seq`，不写入事件表、不推进序号。

### 4.2 断线续传

带 `Last-Event-ID: N` 重连：

1. 服务端从事件表补发 `seq > N` 的所有事件，顺序按 `seq`。
2. 补发完毕再进入实时推送。
3. 若 `N` 小于保留窗口内最小序号减一，返回 410 `sse_cursor_expired`，客户端改用 `GET /api/v1/jobs/{jobId}` 重建视图。

### 4.3 保留窗口

- 每个 job 的事件保留 24 小时，或最近 2000 条，先到者为准。
- 窗口外的 `Last-Event-ID` 一律 410，不猜、不跳过、不静默丢事件。
- 对账补发的事件（如 B5 的 `report_ready`）在启动时分配新序号追加到尾部，不插入历史位置，因此序号始终连续。

### 4.4 终态任务的订阅

任务已到终态后再连接：服务端发一条 `snapshot` 后立即关闭。这是正常结束，不算错误。

---

## 5. 心跳与限频

| 项 | 规则 |
| --- | --- |
| 心跳 | 无数据 15 秒发一次 `: ping`；有心跳不代表任务在推进，只代表连接活着 |
| `stats` 限频 | 同一 job 每 2 秒最多一条；期间多次变化合并为最后一条；值没变不发 |
| 终态前的 stats | 必须发一条最终值，不受限频约束 |
| 其他事件 | 不合并、不丢弃；`status_changed` 与 `stage_changed` 必须逐条送达 |

前端展示「上次更新 x 秒前」用 `stats` 或心跳时间都行，但不得把心跳当进度。

---

## 6. 终态关闭

进入任一终态后，服务端按固定顺序发完再关闭连接：

1. `stats`（最终值）
2. `status_changed`（到终态）
3. `report_ready`（仅 succeeded 且报告已提交）
4. 关闭连接，不再发心跳

前端收到 EOF 后做一次 `GET /api/v1/jobs/{jobId}` 校验终态与 `report_id`，然后停止重连。若 EOF 后连不上，按普通断线处理，重连带 `Last-Event-ID`。

`cancelled / failed / interrupted` 不发 `report_ready`；阶段报告是否可读看 `report_id` 与报告列表，不在事件流里广播。

---

## 7. 重连不得创建任务（硬规则）

以下四条是验收项「SSE 重连没有创建任务语义」的落地条款：

1. 本端点只有 GET；POST 一律 405。
2. 订阅与续传只读事件表与 job 表，不写任何行（`idempotency-conflicts.md` 第 2 节）。
3. `Last-Event-ID` 只用于定位事件，不参与任何创建判定。
4. 410 `sse_cursor_expired` 的客户端动作固定为：读任务详情，不创建、不重试、不续跑。

实现与测试按「订阅前后 job 表、事件表、报告表行数不变」断言。

---

## 8. 与状态机、崩溃边界的对应

| 场景 | 事件表现 |
| --- | --- |
| 用户点暂停 | `status_changed` 到 `pause_requested`，`pending_action = pause`；阶段边界后 `status_changed` 到 `paused` |
| 用户点取消，收尾期间图完成（T14） | `status_changed` 到 `succeeded`，`detail = cancel_noop`，界面提示「任务在取消请求到达前已完成」 |
| 服务重启对账（T16–T18） | 重连首帧 `snapshot` 即为 `interrupted`；随后 `status_changed` 的 `reason = reconcile` |
| B3 发现未登记阶段产物 | `status_changed` 到 `interrupted` 之后补一条 `error`，`code` 用 `reconcile_note`，`fatal = false` |
| B5 报告已提交、完成事件未发 | 启动时补发 `report_ready`（新序号），重连客户端从 `Last-Event-ID` 之后拿到 |
| 任务已终态再订阅 | `snapshot` 后立即关闭 |
