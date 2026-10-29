# P1 任务拆票：持久化任务内核

版本：v1（2026-10-29）
上游：`p0-exit-review.md` 结论为 Go。
用途：把 P1 拆成可以独立验收的 13 个任务。每个任务单独提交、单独回退、单独跑测试。

公共约束：

- 全部测试使用 Day 6 的确定性假图，不调用真实模型，不访问行情网络。
- 只新增 `backend/`、`tests/backend/` 与迁移文件，不动 `tradingagents/` 核心图与 `web/` 旧版。
- 旧版 Streamlit 在每个任务完成后都要能启动，健康检查返回 ok。
- 提交只留本地，不推送远端。

## 1. 任务总表

| 编号 | 任务 | 依赖 | 主要验收编号 | 独立回退方式 |
| --- | --- | --- | --- | --- |
| P1-01 | SQLite 连接与迁移基础 | 无 | DB-01 至 DB-04 | 删除 `backend/` 与 `alembic.ini` |
| P1-02 | 任务、阶段与事件表 | P1-01 | SM-01、DB-05 至 DB-08 | 迁移 downgrade 到空库 |
| P1-03 | 配置快照与配置哈希 | P1-02 | CFG-01 至 CFG-04 | 快照列可清空，原请求体保留 |
| P1-04 | 创建任务与幂等 | P1-03 | ID-01 至 ID-06、SM-01 | 下线 `POST /jobs` 路由 |
| P1-05 | Worker 单行租约 | P1-04 | SM-02、CB-01、WK-01 至 WK-03 | 停 Worker 进程 |
| P1-06 | 假图执行适配 | P1-05 | GF-05、GF-06、S00 | 切换执行器工厂回空实现 |
| P1-07 | 阶段保存与统计事件 | P1-06 | GF-03、GF-13、SM-03 | 删除阶段行，事件表只追加 |
| P1-08 | 暂停、恢复与取消 | P1-07 | SM-05 至 SM-12、SM-14 | 关闭 actions 路由 |
| P1-09 | 终态与重试 | P1-08 | SM-03、SM-04、SM-07、SM-10、SM-12、ID-09 | 下线 retry 路由 |
| P1-10 | 崩溃检测与 interrupted | P1-05、P1-09 | SM-13、SM-I04、CB-01 至 CB-06 | 关闭启动对账开关 |
| P1-11 | SSE 快照、事件与重连 | P1-09、P1-10 | GF-19、GF-20、CB-05、SSE-01 至 SSE-06 | 关闭 events 路由 |
| P1-12 | 旧新 Runner 黄金样本对照 | P1-07 | T1 至 T13、RC-01 至 RC-03 | 对照工具只在测试内，可整体删除 |
| P1-13 | 任务内核性能与故障测试 | P1-11、P1-12 | P05、FT-01 至 FT-06 | 只增测试，不改产品行为 |

表里的 SM、ID、CB、GF、T 编号来自冻结契约与 Day 6 测试矩阵。DB、CFG、WK、AD、ST、RT、SSE、FT 是本票新增的测试编号，不占用契约编号。

## 2. 依赖顺序

```text
P1-01 SQLite 与迁移
  └─ P1-02 三张表
       └─ P1-03 配置快照与哈希
            └─ P1-04 创建任务与幂等
                 └─ P1-05 Worker 租约
                      └─ P1-06 假图适配
                           └─ P1-07 阶段保存与统计
                                ├─ P1-08 暂停、恢复、取消
                                │    └─ P1-09 终态与重试
                                │         └─ P1-10 崩溃检测与 interrupted
                                │              └─ P1-11 SSE
                                │                   └─ P1-13 性能与故障
                                └─ P1-12 旧新样本对照
                                     └─ P1-13 性能与故障
```

实际执行顺序按编号 01 到 13。P1-12 可以在 P1-07 完成后随时插入，与 P1-08 到 P1-11 并行，不阻塞主线。

## 3. 逐任务说明

### P1-01 SQLite 连接与迁移基础

目标：给任务内核一个可升级、可回退的数据库底座。

依赖：无。

涉及文件：

- 新增 `backend/app/core/config.py`：读取 `TA_JOBS_DB`，默认 `~/.tradingagents/jobs.db`。
- 新增 `backend/app/core/db.py`：连接工厂，开启外键、WAL 与忙等待。
- 新增 `backend/alembic.ini`、`backend/alembic/env.py`、`backend/alembic/versions/0001_base.py`。
- 新增 `tests/backend/test_db_migrations.py`。

测试：

- DB-01：空目录执行 upgrade head，全部表建立。
- DB-02：连接后 `PRAGMA foreign_keys` 为 1、`journal_mode` 为 wal、`busy_timeout` 非 0。
- DB-03：upgrade 与 downgrade 往返两次，schema 无残留。
- DB-04：任务数据库路径指向临时目录，旧版数据目录不被创建或修改。

回退：删除 `backend/` 与 `alembic.ini`。数据库文件独立存放，旧版不引用。

验收：`tests/backend/test_db_migrations.py` 全绿；重复升级幂等；旧版健康检查仍为 ok。

### P1-02 任务、阶段与事件表

目标：把九状态、阶段进度与事件序号落成有约束的表。

依赖：P1-01。

涉及文件：

- 新增 `backend/app/models/job.py`、`stage.py`、`event.py`。
- 新增迁移 `backend/alembic/versions/0002_jobs_stages_events.py`。
- 新增 `tests/backend/test_models_constraints.py`。

表要点：

- `jobs`：id、ticker、trade_date、status、config_snapshot、config_hash、idempotency_key、retry_of_job_id、resume_of_job_id、resume_from_stage、lease_owner、lease_expires_at、error_code、error_message、created_at、updated_at、terminal_at。
- `job_stages`：job_id、stage_id、status、started_at、ended_at、report_path，主键为 job_id 加 stage_id。
- `job_events`：job_id、seq、type、payload、created_at，唯一约束为 job_id 加 seq。

测试：

- DB-05：status 只接受九个枚举值，写入第十个值被拒。
- DB-06：同一 job 的 seq 重复写入被唯一约束拒绝。
- DB-07：删除 job 时阶段与事件按外键级联删除。
- DB-08：迁移 downgrade 后三张表消失，其他表不受影响。

回退：执行 downgrade 到 0001。新表无外部依赖。

验收：约束测试全绿；SM-01 可在此层先跑通建行与 `created` 审计记录。

### P1-03 配置快照与配置哈希

目标：同一份配置在任何进程都得到同一哈希，续跑校验有唯一依据。

依赖：P1-02。

涉及文件：

- 新增 `backend/app/services/config_snapshot.py`。
- 新增 `tests/backend/test_config_snapshot.py`。

测试：

- CFG-01：字段顺序不同、内容相同的两份配置，哈希相同。
- CFG-02：任一字段变化，哈希变化。
- CFG-03：浮点、空值与整数的规范化规则固定，跨进程重算一致。
- CFG-04：续跑指纹包含配置哈希与图版本，任一不匹配则拒绝续跑。

回退：配置快照是普通 JSON 列。清空该列不影响任务读取，原始请求体另存。

验收：CFG-01 至 CFG-04 全绿；同一配置连续 100 次计算哈希一致。

### P1-04 创建任务与幂等

目标：创建任务只有一条写路径，重复请求不产生第二个任务。

依赖：P1-03。

涉及文件：

- 新增 `backend/app/api/v1/jobs.py` 中的创建路由。
- 新增 `backend/app/services/job_service.py` 的创建五步。
- 新增 `tests/backend/test_create_idempotency.py`。

测试：

- ID-01：同幂等键同请求体，返回原 job，行数不变。
- ID-02：同幂等键异请求体，409 `idempotency_mismatch`。
- ID-03：同活动配置指纹，200 加 `X-Existing-Job`。
- ID-04：同股同日异配置且有活动任务，409 `active_conflict`。
- ID-05：20 并发同指纹，恰好 1 个活动 job，其余 19 个拿到同一 id。
- ID-06：GET 不存在的任务返回 404，表行数不变。

回退：下线 `POST /jobs` 路由。已创建任务仍可读，旧版不受影响。

验收：ID-01 至 ID-06 全绿；并发测试重复 10 次结果一致。

### P1-05 Worker 单行租约

目标：首期只允许一个 Worker 执行任务，误启动第二个也只能等待或退出。

依赖：P1-02，P1-04 完成后接入创建。

涉及文件：

- 新增 `backend/app/worker/main.py`、`backend/app/services/lease.py`。
- 新增 `tests/backend/test_worker_lease.py`。

测试：

- SM-02：T02 认领后状态 running，租约字段写入。
- CB-01：B1 崩溃后任务仍 queued，重启可正常认领一次。
- WK-01：第二个 Worker 启动时拿不到租约，进入等待或退出。
- WK-02：心跳按固定间隔刷新租约到期时间。
- WK-03：租约过期后任务不被 Worker 自动重跑。

回退：停 Worker 进程。租约字段留空不影响任务读取。

验收：单 Worker 串行执行；双 Worker 不产生双重执行；租约过期只改变状态，不自动重跑。

### P1-06 假图执行适配

目标：Worker 默认执行 Day 6 假图，真实模型执行器默认关闭。

依赖：P1-05。

涉及文件：

- 新增 `backend/app/services/analysis_runner.py`：执行器工厂。
- 新增 `tests/backend/test_fake_adapter.py`。
- 复用 `tests/fake_analysis_graph.py`，不复制其中逻辑。

测试：

- GF-05：默认路径无网络、无模型客户端、不写真实报告目录。
- GF-06：假图事件流驱动真实进度追踪器。
- S00：14 次模型调用、182430 输入 Token、41208 输出 Token、40 条事件，与假图文档一致。
- AD-01：真实执行器开关默认关闭；显式开启需要环境变量与配置双条件。

回退：执行器工厂切回空实现，Worker 只认领不执行。

验收：默认配置下跑完整任务不出现任何外部请求；S00 数字逐项相等。

### P1-07 阶段保存与统计事件

目标：每个阶段结束即落库，统计事件与阶段报告可查。

依赖：P1-06。

涉及文件：

- 新增 `backend/app/services/job_service.py` 的阶段写入与统计方法。
- 新增 `backend/app/services/report_store.py` 的阶段报告文件写入。
- 新增 `tests/backend/test_stage_persistence.py`。

测试：

- GF-03：阶段事件 24 条、统计事件 13 条、顺序固定。
- GF-13：B3 阶段输出已落盘但事件未写，重启对账补备注。
- SM-03：完成时报告行与内容哈希落库。
- ST-01：阶段报告路径按 job 与 stage 隔离，不覆盖旧文件。

回退：按 job 删除阶段行与报告文件。事件表只追加，不回改。

验收：12 个阶段各有开始与结束事件；统计事件 13 条；阶段报告 GET 返回与假图输出一致。

### P1-08 暂停、恢复与取消

目标：三个控制动作在安全边界生效，状态按 T05 至 T20 转换。

依赖：P1-07。

涉及文件：

- 新增 `backend/app/api/v1/jobs.py` 的 actions 路由。
- 新增 `backend/app/services/job_service.py` 的控制请求方法。
- 新增 `tests/backend/test_control_actions.py`。

测试：

- SM-05：running 到 pause_requested 到 paused，暂停落在步骤边界。
- SM-07：paused 恢复到 running，检查点阶段不重复执行。
- SM-08：Worker 忙时恢复转 queued，检查点引用保留。
- SM-09：running 到 cancel_requested 到 cancelled，阶段报告只读保留。
- SM-10：取消迟到，图完成转 succeeded，取消记 no-op。
- SM-11：pause_requested 上发取消，转 cancel_requested，不转 paused。
- SM-12：queued 直接取消，不经过 cancel_requested。
- SM-14：paused 上发取消，走 T20 到 cancel_requested，再由 T13 收尾。

回退：关闭 actions 路由。进行中的任务仍可自然完成。

验收：上述编号全绿；每次动作后 `allowed_actions` 与 api-v1 一致。

### P1-09 终态与重试

目标：三个终态只写一次，重试创建新任务且原任务不变。

依赖：P1-08。

涉及文件：

- 新增 `backend/app/services/job_service.py` 的终态写入与重试方法。
- 新增 `backend/app/api/v1/jobs.py` 的 retry 路由。
- 新增 `tests/backend/test_terminal_retry.py`。

测试：

- SM-03：running 到 succeeded，报告行与哈希落库。
- SM-04：running 到 failed，错误码与文本落库。
- SM-07、SM-10、SM-12 复跑，确认终态只写一次。
- ID-09：PDF 缓存命中不重新渲染。
- RT-01：retry 返回新 job id，`retry_of_job_id` 指向旧任务。
- RT-02：原任务状态、报告和事件不被 retry 修改。

回退：下线 retry 路由。旧任务保持可读。

验收：终态不可再次转换；重试后任务数加一；`report_ready` 只发一次。

### P1-10 崩溃检测与 interrupted

目标：进程崩溃与租约失效只产生 interrupted，绝不自动重跑。

依赖：P1-05、P1-09。

涉及文件：

- 新增 `backend/app/worker/reconcile.py`。
- 新增 `backend/app/services/job_service.py` 的对账备注写入。
- 新增 `tests/backend/test_crash_recovery.py`。

测试：

- SM-13：三个非终态在租约过期后一律 interrupted。
- SM-I04：interrupted 上发恢复被拒，只有带确认的续跑创建新 job。
- CB-01 至 CB-06：六个崩溃边界逐条断言，含 B3、B4 的 `reconcile_notes`。
- GF-21：queued 与检查点缺失的对账分支。

回退：关闭启动对账开关。任务停在原状态，由人工处理。

验收：六个边界的结局与 `crash-boundaries.md` 一致；事件表可还原崩溃前顺序。

### P1-11 SSE 快照、事件与重连

目标：客户端断线只补事件，不创建任务，序号无空洞。

依赖：P1-09、P1-10。

涉及文件：

- 新增 `backend/app/api/v1/jobs.py` 的 events 路由。
- 新增 `backend/app/services/event_stream.py`。
- 新增 `tests/backend/test_sse.py`。

测试：

- GF-19：多浏览器重连只读事件表，任务数不变。
- GF-20：断线后按 `Last-Event-ID` 补发，seq 连续。
- CB-05：B5 已成功后重连补收到 `report_ready`。
- SSE-01 至 SSE-06：六类事件形状、终态顺序、心跳、410、审计记录不占 seq、快照先行。

回退：关闭 events 路由。任务写入与查询不受影响。

验收：补发无空洞；终态顺序为 stats、status_changed、report_ready；410 后整页刷新可恢复。

### P1-12 旧新 Runner 黄金样本对照

目标：旧报告样本导入后与黄金样本章节一致，哈希可重算。

依赖：P1-07。

涉及文件：

- 新增 `backend/app/services/report_schema.py` 的旧样本转换。
- 新增 `tests/backend/test_legacy_golden.py`。
- 复用 `tests/fixtures/upgrade/legacy_report_v1.json` 与 `final_state_v1.json`。

测试：

- T1 至 T13 中与导入和渲染无关的部分，至少覆盖 T1、T2、T3、T9、T10、T11。
- RC-01：旧样本键集合不越界，`trader_investment_plan` 只进 `legacy_aliases`。
- RC-02：`signal_legacy` 只存档，渲染层不读取。
- RC-03：转换后 `content_hash` 可重算，且与报告 meta 一致。

回退：对照工具只在测试内，删除测试文件即可，不影响生产导入。

验收：旧样本转换后 13 个章节 ID 与黄金样本一致；哈希重算通过。

### P1-13 任务内核性能与故障测试

目标：把 Day 6 的性能模板与故障场景跑成可重复的记录。

依赖：P1-11、P1-12。

涉及文件：

- 新增 `tests/backend/test_kernel_perf_faults.py`。
- 新增 `tests/backend/perf/` 下的测量脚本。
- 复用 `docs/upgrade/fake-graph/perf-template.md` 与 `perf-result-template.json`。

测试：

- P05：任务事件端到端延迟，按模板口径记录。
- FT-01：API 重启后可重连并补发事件。
- FT-02：Worker 崩溃不自动重跑，任务转 interrupted。
- FT-03：20 并发同指纹创建只执行一次。
- FT-04：SQLite 忙等不导致图重跑。
- FT-05：1000 条事件补发顺序与 seq 完整。
- FT-06：配置串行隔离，两个任务不共享运行期配置。

回退：只增测试，不改产品行为，删除测试即可。

验收：结果写入 `perf-result-template.json` 的副本并附环境信息；无失败项。

## 4. P1 出口判据

P1 完成必须同时满足：

1. 20 个并发相同创建请求只执行一次。
2. API 重启后客户端可以重连并补发遗漏事件。
3. Worker 崩溃不自动重跑，任务一律 interrupted 并带原因。
4. 配置串行隔离通过，两个任务不共享运行期配置。
5. 旧版 Streamlit 仍可独立启动，健康检查 ok。
6. 全部测试使用假图，真实模型默认关闭。
7. 每个任务一个本地提交，回退方式经过演练。

详细证据格式沿用 P0：测试编号、命令、输出摘要、提交号。

## 5. 与 P0 契约的对应

- 状态与转换：`contracts/job-state-machine.md` 的 T01 至 T20、I01 至 I11。
- 字段与按钮：`contracts/api-v1.md`、`contracts/semantic-dictionary.md`。
- 事件与序号：`contracts/sse-events-v1.md`。
- 崩溃边界：`contracts/crash-boundaries.md`。
- 幂等：`contracts/idempotency-conflicts.md`。
- 报告结构：`contracts/report-schema-v1.md` 与 `report-schema-v1.json`。
- 冻结与变更：`contracts/FREEZE-v1.md`。

P1 不允许在代码里另立状态名、事件名或错误码。发现契约缺陷时先走 `FREEZE-v1.md` 第 4 节的解冻流程。
