# 任务状态机（P0 Day 2）

首期状态固定为九个，不再增减。任何新需求先尝试用现有状态表达，表达不了才允许提案加状态。

```text
queued
running
pause_requested
paused
cancel_requested
cancelled
succeeded
failed
interrupted
```

终态四个：`cancelled`、`succeeded`、`failed`、`interrupted`。终态永不自动离开。

## 1. 状态属性表

「占用 Worker」指是否持有执行租约。Worker 全系统只有一个，串行执行。

| 状态 | 占用 Worker | 允许暂停 | 允许恢复 | 允许取消 | 允许重试/续跑 | 可以有报告 | 浏览器刷新后展示 | 服务重启后展示 |
|---|---|---|---|---|---|---|---|---|
| queued | 否 | 否 | 否 | 是 | 否 | 否 | 排队中 | 仍排队，Worker 起来后认领 |
| running | 是 | 是 | 否 | 是 | 否 | 仅阶段报告 | 当前阶段 + 事件流续传 | 改判 interrupted |
| pause_requested | 是 | 否 | 否 | 是 | 否 | 仅阶段报告 | 暂停请求已提交 | 改判 interrupted |
| paused | 否（租约释放，检查点保留） | 否 | 是 | 是 | 否 | 阶段报告只读 | 已暂停 + 已完成阶段 | 仍 paused，检查点在磁盘 |
| cancel_requested | 是 | 否 | 否 | 否 | 否 | 仅阶段报告 | 取消中 | 改判 interrupted |
| cancelled | 否 | 否 | 否 | 否 | 否 | 阶段报告只读 | 已取消 | 已取消 |
| succeeded | 否 | 否 | 否 | 否 | 可重试（新任务） | 最终报告 | 报告只读 | 报告只读 |
| failed | 否 | 否 | 否 | 否 | 可重试（新任务） | 阶段报告只读 | 已失败 + 错误摘要 | 已失败 |
| interrupted | 否 | 否 | 否 | 否 | 人工确认后续跑或重分析（均为新任务） | 阶段报告只读 | 执行中断 + 原因 + 两个显式选项 | 执行中断 |

两个刻意的设计决定：

- `paused` 不占 Worker。暂停可能持续很久，占着唯一 Worker 会堵死整条队列。代价是恢复时要重新抢租约。
- `interrupted` 不给「恢复」，只给「续跑 / 重分析」，且两者都创建新 job。原 job 保持终态，对账时能清楚看到「哪一次执行断了、断在哪」。

## 2. 合法转换表

编号用于测试用例引用。

| 编号 | 从 | 到 | 触发者 | 条件 |
|---|---|---|---|---|
| T01 | （无） | queued | 用户创建 / API 创建 | 幂等校验通过 |
| T02 | queued | running | Worker | 抢到租约 |
| T03 | running | succeeded | Worker | 图正常结束且报告提交成功 |
| T04 | running | failed | Worker | 执行抛异常 |
| T05 | running | pause_requested | 用户 | 当前无未决暂停/取消请求 |
| T06 | pause_requested | paused | Worker | 当前步骤在边界结束 |
| T07 | pause_requested | succeeded | Worker | 收尾期间图恰好完成 |
| T08 | pause_requested | failed | Worker | 收尾期间执行报错 |
| T09 | paused | running | 用户点继续 | Worker 空闲、配置指纹与图版本匹配 |
| T10 | paused | queued | 用户点继续 | Worker 忙；排队等待续跑，保留检查点引用 |
| T11 | running | cancel_requested | 用户 | 当前无未决取消请求 |
| T12 | pause_requested | cancel_requested | 用户 | 取消优先于暂停 |
| T13 | cancel_requested | cancelled | Worker | 当前步骤收尾完成 |
| T14 | cancel_requested | succeeded | Worker | 收尾期间图恰好完成；取消记为 no-op 并提示用户 |
| T15 | cancel_requested | failed | Worker | 收尾期间执行报错 |
| T16 | running | interrupted | 对账 | 租约过期或进程死亡被检测到 |
| T17 | pause_requested | interrupted | 对账 | 同上 |
| T18 | cancel_requested | interrupted | 对账 | 同上 |
| T19 | queued | cancelled | 用户 | 尚未认领即可直接取消 |

续跑与重试不是状态转换，而是创建新 job：

| 编号 | 动作 | 新 job 字段 | 原 job |
|---|---|---|---|
| N01 | 重试（failed / interrupted） | `retry_of_job_id = 原 id`，配置取原 job 深拷贝 | 保持终态 |
| N02 | 续跑（interrupted / paused 且指纹匹配） | `resume_of_job_id = 原 id`，`resume_from_stage = 首个未完成阶段` | 保持终态（interrupted）或转 queued（paused 走 T10 时不新建） |

## 3. 非法转换表

以下转换在任何入口都返回 409，并记录拒绝原因。测试逐条覆盖。

| 编号 | 从 | 到 | 为什么非法 |
|---|---|---|---|
| I01 | succeeded | running | 已完成的任务不能重新执行；要重跑必须新建 |
| I02 | cancelled | queued | 已取消不能自动重排 |
| I03 | failed | running | 重试必须生成新任务，不能覆盖原任务 |
| I04 | interrupted | running | 中断不自动重放，必须人工确认 |
| I05 | paused | succeeded | 不能跳过执行直接成功 |
| I06 | queued | paused | 没在跑的东西不能暂停 |
| I07 | cancel_requested | paused | 取消优先，暂停请求作废而非转暂停 |
| I08 | succeeded | failed | 终态之间互不转换 |
| I09 | cancelled | succeeded | 同上 |
| I10 | running | queued | 租约一旦发出不能退回排队（Worker 死亡走 T16） |
| I11 | paused | cancelled 直接 | 必须先 cancel_requested 再收尾（T13），保证取消有确认点 |

## 4. 对账规则（服务启动时）

启动时扫一遍 job 表，逐条按下面顺序判定：

1. 状态是终态：不动。
2. 状态是 `queued`：不动，等 Worker 认领。
3. 状态是 `paused`：检查点文件存在则不动；不存在则改判 `interrupted`，原因记 `checkpoint_missing`。
4. 状态是 `running / pause_requested / cancel_requested`：租约心跳超过阈值即改判 `interrupted`，原因记 `lease_expired`。

对账只改状态和写一条 `status_changed` 事件，不触发任何执行，不调用任何模型。
