# 崩溃与竞争场景清单（P0 Day 6）

日期：2026-10-29
状态：P0 Day 6 交付
配套：`README.md`、`test-matrix.md`、`tests/fake_analysis_graph.py`、`contracts/crash-boundaries.md`、`contracts/job-state-machine.md`

## 1. 怎么用这份清单

每个场景是一条可独立复现的执行路径。

跑一条：`.venv/Scripts/python.exe tests/fake_analysis_graph.py --scenario S06 --json`

跑全部：`.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'tests'); import fake_analysis_graph as f; [f.run_scenario(s) for s in f.SCENARIOS]"`

所有场景共用同一组起点：任务 `job-0001`、标的 `000629`、分析日 `2026-10-24`、虚拟时钟从 `09:30:00 +08:00` 开始。

场景输出 `RunOutcome` 含五项：任务详情、SSE 事件、审计记录、报告对象、对账备注。

下表数字均由代码实际运行取得，改动假图后必须重新核对。

## 2. 总览

| 场景 | 标题 | 注入点 | 终态 | 完成阶段 | 事件数 | 模型调用 | 报告写盘 | 报告提交 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S00 | 正常完成 | 无 | succeeded | 12 | 40 | 14 | 是 | 是 |
| S01 | 创建后立即取消 | `cancel()` 于 queued | cancelled | 0 | 2 | 0 | 否 | 否 |
| S02 | 运行中暂停 | 3 阶段后 `pause()` | succeeded | 12 | 43 | 14 | 是 | 是 |
| S02B | 暂停请求已受理后取消 | `pause()` + `cancel()` | cancelled | 3 | 14 | 3 | 否 | 否 |
| S03 | 暂停后取消 | 暂停落地后 `cancel()` | cancelled | 3 | 15 | 3 | 否 | 否 |
| S04 | 阶段完成后异常 | `fail_after="news"` | failed | 3 | 11 | 3 | 否 | 否 |
| S04B | 阶段执行中异常 | `FakeAnalysisGraph(fail_at="news")` | failed | 2 | 11 | 2 | 否 | 否 |
| S05 | 最终报告前中断 | `interrupt_at="before:pm"` | interrupted | 11 | 35 | 13 | 否 | 否 |
| S06 | 阶段产物已写、事件未保存 | `interrupt_at="after:news"` | interrupted | 2 | 9 | 2 | 否 | 否 |
| S07 | 最终报告后、数据库提交前中断 | `interrupt_at="after_report"` | interrupted | 12 | 38 | 14 | 是 | 否 |
| S08 | 报告已提交、完成事件未发 | `interrupt_at="after_commit"` | succeeded | 12 | 40 | 14 | 是 | 是 |
| S09 | 取消迟到，收尾先落盘 | `auto_finalize=False` + `finalize()` | succeeded | 12 | 41 | 14 | 是 | 是 |
| S09B | 取消先确认，收尾产物丢弃 | `finalize(cancel_wins=True)` | cancelled | 12 | 40 | 14 | 否 | 否 |

交互类场景 S10 到 S12 不产出单个任务的结果，见第 5 节。

## 3. 逐条说明

### S00 正常完成

路径：`queued → running → succeeded`，十二个阶段依次开始、结束。

事件 40 条：`stage_changed` 24 条（12 开始 + 12 结束）、`stats` 13 条（每阶段一条加终态前一条）、`status_changed` 2 条、`report_ready` 1 条。

统计累计 14 次模型调用、182430 输入 Token、41208 输出 Token。

报告与 `tests/fixtures/upgrade/final_state_v1.json` 逐字段相等，`generated_at` 为 `2026-10-24T15:30:00+08:00`。

对应契约：T01、T02、T03；SSE 终态顺序 `stats → status_changed → report_ready`。

对应测试：GF-03、GF-04。

### S01 创建后立即取消

路径：`queued → cancelled`，走 T19。

一个阶段都没开始，模型调用 0 次，事件只有 1 条 `stats`（全零）与 1 条 `status_changed`。

不写阶段产物，不生成报告。

对应契约：T19。对应测试：GF-07。

### S02 运行中暂停

路径：`queued → running → pause_requested → paused → running → succeeded`。

前 3 个阶段完成后提交暂停，`advance()` 在启动第 4 个阶段前停住，此时 `stage_pointer = 3`。

继续后跑完剩余 9 个阶段，最终成功。

事件 43 条，比 S00 多 3 条：`pause_requested`、`paused`、`paused` 回 `running` 三个状态转换。

对应契约：T05、T06、T09。对应测试：GF-08。

### S02B 暂停请求已受理后取消

路径：`queued → running → pause_requested → cancel_requested → cancelled`。

暂停尚未落地时用户改点取消，走 T12 而不是先落地暂停。

终态取消，已完成 3 个阶段，没有报告。

对应契约：T12、T13。对应测试：GF-28。

### S03 暂停后取消

路径：`queued → running → pause_requested → paused → cancel_requested → cancelled`。

暂停已落地，再取消走 T20（Day 6 新补的转换），然后按 T13 结束。

事件 15 条，比 S02B 多一条 `paused` 转换。

对应契约：T20、T13。对应测试：GF-09。

### S04 阶段完成后异常

注入：`fail_after="news"`。新闻阶段已经完成并落盘，紧接着抛异常。

终态 failed，`detail = post_stage_error`，错误码 `internal_error`。

已完成 3 个阶段，failed 阶段 0 个：异常不在阶段内部，阶段本身是成功的。

对应契约：T04。对应测试：GF-10。

### S04B 阶段执行中异常

注入：`FakeAnalysisGraph(fail_at="news")`。新闻阶段一开始就抛 `FakeGraphError`。

终态 failed，`detail = stage_failed`，新闻阶段标 `failed`，前 2 个阶段保持 `done`。

两个失败场景的区别决定界面文案：阶段内部失败要点名阶段，阶段之后失败只报任务失败。

对应契约：T04。对应测试：GF-11。

### S05 最终报告前中断

注入：`interrupt_at="before:pm"`。风险阶段已完成，最终决策阶段开始前进程死亡。

重启对账后终态 interrupted，`detail = lease_expired`，属于崩溃边界 B2。

已完成 11 个阶段，模型调用 13 次，没有核心报告。

对账不改判成功，也不自动重跑。

对应契约：B2、T16。对应测试：GF-12。

### S06 阶段产物已写、事件未保存

注入：`interrupt_at="after:news"`。新闻阶段的产物已写盘，`stage_changed(done)` 事件还没入库。

重启后证据：事件表里新闻阶段仍是 `active`，但磁盘上有该阶段产物。

对账终态 interrupted，`detail = unregistered_stage_output`，并写一条对账备注「发现未登记的阶段产物：新闻舆情」。

属于崩溃边界 B3。备注只入库、不广播，不占 SSE 序号。

对应契约：B3、T16。对应测试：GF-13。

### S07 最终报告后、数据库提交前中断

注入：`interrupt_at="after_report"`。核心报告文件已写，job 行还是 `running`。

对账终态 interrupted，`detail = unregistered_report`，备注「发现一份未登记的完整报告」。

属于崩溃边界 B4。对账绝不把任务补成 succeeded，因为数据库没提交。

界面对应三个选项：导入为报告、从检查点继续、重新分析。

对应契约：B4、T16。对应测试：GF-14。

### S08 报告已提交、完成事件未发

注入：`interrupt_at="after_commit"`。job 行已是 succeeded，报告已提交，`report_ready` 还没发出。

对账保持 succeeded，补发一条 `report_ready`，序号续接在尾部。

属于崩溃边界 B5。补事件不是重放，只是把已发生的事实广播出去。

最终事件 40 条，与 S00 相同；区别只在 `report_ready` 的产生时机。

对应契约：B5。对应测试：GF-15。

### S09 取消迟到，收尾先落盘

注入：`auto_finalize=False`。十二个阶段跑完后停在 running，用户点取消（进入 cancel_requested），随后收尾先提交。

终态 succeeded，`detail = cancel_noop`，取消记为无操作。

事件 41 条，比 S00 多一条 `running → cancel_requested`。

属于崩溃边界 B6 的第一种结局：完成先提交。

对应契约：B6、T14。对应测试：GF-16。

### S09B 取消先确认，收尾产物丢弃

同一注入，但 `finalize(cancel_wins=True)`：取消先确认。

终态 cancelled，收尾产物不保留，报告不写盘、不提交。

属于崩溃边界 B6 的第二种结局。

对应契约：B6、T13。对应测试：GF-17。

## 4. 崩溃边界对照

| 边界 | 场景 | 终态 | 自动动作 | 人工动作 |
| --- | --- | --- | --- | --- |
| B1 任务已创建、Worker 未开始 | GF-21（无独立场景编号） | queued | Worker 认领 | 无 |
| B2 图已开始、无核心报告 | S05 | interrupted | 无 | 续跑或重分析 |
| B3 阶段产物已写、事件未保存 | S06 | interrupted | 无 | 对账后续跑或重分析 |
| B4 核心报告已落盘、数据库未提交 | S07 | interrupted | 无 | 导入报告 / 续跑 / 重分析 |
| B5 报告已提交、完成事件未发 | S08 | succeeded | 补发 report_ready | 无 |
| B6 取消与收尾竞争 | S09、S09B | succeeded 或 cancelled | 无 | 无 |

B1 是唯一不需要对账动作的崩溃时点，用检查组直接验证：`FakeJobRunner().reconcile()` 前后状态都是 queued，事件表为空。

## 5. 交互与竞争场景

### S10 重复启动请求

不进 `SCENARIOS` 字典，由 GF-18 用 `FakeJobLedger` 直接构造。

四种情况按 `idempotency-conflicts.md` 的五步顺序验证：

1. 同键同体：201 一次，之后 200 重放，`replayed=True`。
2. 同票同日同配置、换新键：200 返回原任务，`existing_header=True`。
3. 同键异体：409 `idempotency_mismatch`。
4. 同票同日不同配置、有活动任务：409 `active_conflict`，带当前活动任务 id。
5. 十个不同键同时提交同一意图：只创建 1 个任务，全部返回 `job-0001`。

第 5 条是并发条款的替身验证：真实系统靠数据库部分唯一索引兜底，假账本靠内存判断。

### S11 多浏览器重连

由 GF-19 验证，两个浏览器先后订阅同一任务。

要求：两路首帧逐字段相同；首帧 `snapshot` 的 `seq` 等于当前最大序号；订阅前后任务详情、事件条数、序号都不变。

订阅是纯读操作，不创建任务、不推进状态。

### S12 事件断线后补发

由 GF-20 验证：跑到第 5 个阶段后记下游标 N，继续跑完，再用 `Last-Event-ID: N` 重连。

要求：补发的事件恰好是 `seq > N` 的全部事件，序号从 N+1 连续到当前最大值；首帧仍是 `snapshot`；用当前最大序号重连时补发为空。

## 6. 假图覆盖不到的场景

以下留给 P1 用真实内核加数据库验证，假图不冒充覆盖：

- 数据库唯一索引在并发下的真实裁决。
- Worker 租约过期与多进程抢锁。
- HTTP 状态码、请求头与错误响应体。
- SSE 服务端的心跳、限频与 410 游标过期。
- PDF 导出与报告渲染。

## 7. 新增场景的规则

新增一个场景要做四件事：

1. 在 `tests/fake_analysis_graph.py` 写构造函数并登记进 `SCENARIOS`。
2. 在本文件第 2 节总览表补一行，第 3 节补一节说明。
3. 在 `test-matrix.md` 登记对应的 GF 编号。
4. 跑 GF-23 与 GF-26，确认清单与编号仍然一致。

总览表的数字必须来自实际运行，不许手写估计值。
