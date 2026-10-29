# P1 状态机测试用例清单（P0 Day 2）

P1 实现持久化任务内核时按本清单补测试。用例编号稳定，评审与回归都引用编号。

全部用例使用确定性假图（Day 6 产出）或打桩执行器，不触发真实模型调用。

## 1. 合法转换（对应状态机 T01–T20）

| 用例 | 内容 | 断言要点 |
|---|---|---|
| SM-01 | T01 创建 | 新 job 状态 queued，事件表有 created |
| SM-02 | T02 认领 | queued→running，租约字段写入 |
| SM-03 | T03 完成 | running→succeeded，报告行与内容哈希落库 |
| SM-04 | T04 失败 | running→failed，错误码与文本落库 |
| SM-05 | T05/T06 暂停 | running→pause_requested→paused；暂停落在步骤边界 |
| SM-06 | T07 收尾完成 | pause_requested 期间图完成→succeeded |
| SM-07 | T09 恢复 | paused→running，检查点阶段不重复执行 |
| SM-08 | T10 忙时恢复 | Worker 忙时 paused→queued，检查点引用保留 |
| SM-09 | T11/T13 取消 | running→cancel_requested→cancelled，阶段报告只读保留 |
| SM-10 | T14 取消迟到 | cancel_requested 期间图完成→succeeded，取消记 no-op |
| SM-11 | T12 取消优先 | pause_requested 上发取消→cancel_requested，不转 paused |
| SM-12 | T19 排队取消 | queued 直接取消，不经过 cancel_requested |
| SM-13 | T16–T18 对账 | 三个非终态在租约过期后一律 interrupted |
| SM-14 | T20 暂停后取消 | paused→cancel_requested，不转 running，再由 T13 收尾 |

## 2. 非法转换（对应 I01–I11）

每条一个用例，编号 SM-I01 … SM-I11。断言统一为：接口返回 409、状态不变、事件表多一条 `transition_rejected` 且带原因码。

重点三条单独强调：

- SM-I03：failed 上发「重试」不得修改原 job，必须返回新 job id。
- SM-I04：interrupted 上发「恢复」必须被拒；只有带确认的续跑请求才创建新 job。
- SM-I10：running 不能退回 queued；Worker 死亡只能走对账。

## 3. 幂等与冲突（对应决策表）

| 用例 | 内容 | 断言要点 |
|---|---|---|
| ID-01 | 同幂等键同请求体 | 200 + 原 job，job 表行数不变 |
| ID-02 | 同幂等键异请求体 | 409 idempotency_mismatch |
| ID-03 | 同活动配置指纹重复创建 | 200 + 原 job，响应头 X-Existing-Job |
| ID-04 | 同股同日异配置且有活动任务 | 409 active_conflict，body 带现有 id |
| ID-05 | 20 并发同指纹创建 | 恰好 1 个活动 job，其余 19 个拿到同一 id |
| ID-06 | GET 任务详情不创建 | 不存在的 id 返回 404，表行数不变 |
| ID-07 | 刷新与 SSE 重连不创建 | 带 Last-Event-ID 重连只读事件表 |
| ID-08 | 查看报告零副作用 | GET 报告前后事件表行数不变 |
| ID-09 | PDF 缓存命中 | 同 report_id+content_hash+exporter_version 不重新渲染 |

## 4. 崩溃边界（对应 B1–B6）

用「在指定时点杀进程 / 伪造租约过期」的方式构造，每个时点一个用例，编号 CB-01 … CB-06。

| 用例 | 时点 | 断言要点 |
|---|---|---|
| CB-01 | B1 | 重启后仍 queued，被正常认领，无重复创建 |
| CB-02 | B2 | 重启后 interrupted(lease_expired)，无自动执行 |
| CB-03 | B3 | interrupted + reconcile_note；续跑不重复已完成阶段 |
| CB-04 | B4 | interrupted；报告文件不自动登记；导入选项只写报告表 |
| CB-05 | B5 | 保持 succeeded；重连客户端能补收到 report_ready |
| CB-06 | B6 | 结局是 cancelled 或 succeeded 之一，事件序号可还原先后 |

## 5. 文案一致性

| 用例 | 内容 |
|---|---|
| TX-01 | 九个状态的界面文案与语义词典第 2 节逐字一致（前端快照测试） |
| TX-02 | 界面与文档中不出现禁用词「停止」「重跑」「任务不存在」（字符串扫描测试） |

## 6. 覆盖核对

- 合法转换 20 条全覆盖（SM-01…SM-14 对应 T01–T20，其中 T08/T15 并入 SM-05/SM-09 的异常分支，P1 实现时若拆细则沿用 T 编号）。
- 非法转换 11 条全覆盖。
- 幂等 9 条、崩溃 6 条、文案 2 条。
- 合计 42 个用例编号位，P1 验收以本表为准。

SM-14 对应的 T20 由 P0 Day 6 发现并补入，见 `job-state-machine.md` 第 2 节。
