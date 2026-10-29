# 幂等与冲突决策表（P0 Day 2）

目标：同一个意图重复提交，永远只产生一个会花钱的执行。

三个键的定义：

- 幂等键 `Idempotency-Key`：客户端生成的 UUID，随创建请求提交，服务端按它去重。
- 活动配置指纹：`ticker + trade_date + config_hash`。`config_hash` 是模型配置、阶段开关、图版本的规范化哈希。
- 活动任务：状态属于 `queued / running / pause_requested / paused / cancel_requested` 的任务。

## 1. 创建请求的判定顺序

创建接口按下面顺序判定，命中即返回，不再往下走：

| 步 | 条件 | 响应 | 说明 |
|---|---|---|---|
| 1 | 幂等键已存在且请求体哈希相同 | 200 + 原 job | 重复提交，返回原任务 |
| 2 | 幂等键已存在但请求体哈希不同 | 409 `idempotency_mismatch` | 同一个键提交了两种意图，属客户端 bug，必须报错而不是猜 |
| 3 | 幂等键未命中（未携带或首次出现），但存在同活动配置指纹的活动任务 | 200 + 该 job，响应头 `X-Existing-Job: <id>` | 用户连点「开始分析」的典型场景 |
| 4 | 同 ticker + 同 trade_date，配置不同，且存在活动任务 | 409 `active_conflict`，body 带现有 job id | 让用户自己决定：等它跑完，还是先取消 |
| 5 | 以上都不命中 | 201 + 新 job | 正常创建 |

第 3 步与第 4 步的区别：配置完全相同就是同一个意图，直接复用；配置不同是另一个意图，不能替用户做主。

第 3 步必须覆盖「首次出现的新键」这种情况。若只认「未携带键」，二十个各带不同键的相同请求会全部落到第 5 步，与第 4 节的并发裁决矛盾。Day 6 的假账本按这个口径实现，见 `tests/fake_analysis_graph.py::FakeJobLedger.create`。

## 2. 只读操作清单

以下操作在任何情况下都不创建任务、不修改任务、不触发模型或 PDF 生成。测试逐条断言「调用前后 job 表与事件表行数不变」。

| 操作 | 说明 |
|---|---|
| 打开任务 URL | 只 GET 任务详情；URL 里的 job id 不存在时返回 404，不自动创建 |
| 浏览器刷新 | 前端只发 GET 与 SSE 订阅 |
| SSE 重连 | 带 `Last-Event-ID` 续传；服务端只读事件表 |
| 查看历史报告 | GET 报告；零副作用 |
| 导出 PDF | 显式 POST，缓存键为 `report_id + content_hash + exporter_version`；命中缓存不重新渲染 |
| 查看任务列表 | GET 列表 |

## 3. 不自动重放清单

以下场景服务端永不自动创建新执行，只能由用户显式触发：

| 场景 | 服务端行为 |
|---|---|
| 服务重启后发现 `running / pause_requested / cancel_requested` | 改判 `interrupted`，写一条事件，结束 |
| Worker 租约过期 | 同上 |
| `failed` 任务 | 保持 failed；界面给「使用相同参数重试」按钮，点击才新建 |
| `cancelled` 任务 | 保持 cancelled；不给任何自动动作 |
| 检查点缺失的 `paused` | 改判 `interrupted`，原因 `checkpoint_missing` |
| 续跑时配置指纹或图版本不匹配 | 拒绝续跑，界面只给「重新分析」 |

## 4. 并发创建的裁决

二十个并发创建请求带同一个活动配置指纹时，最终必须恰好一个 job 处于活动状态，其余十九个拿到 200 + 同一个 job id。实现上靠数据库唯一约束（`uniq_active_fingerprint` 部分唯一索引：仅对活动状态生效）兜底，不靠应用层先查后插。

## 5. 与旧版行为的差异

| 场景 | 旧版 | 契约 |
|---|---|---|
| 打开带随机 job id 的 URL | `get_or_create_job` 会创建一个空 tracker | 404，不创建 |
| 连点开始分析 | 靠前端禁用按钮兜底，后端无防线 | 第 3 步返回原 job |
| 刷新页面 | 重跑整个 Streamlit 脚本 | 只读 GET |
| 进程重启 | 任务消失 | `interrupted` + 人工选项 |
