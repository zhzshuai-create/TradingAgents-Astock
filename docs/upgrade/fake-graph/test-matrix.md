# 契约条款到测试的映射（P0 Day 6）

日期：2026-10-29
状态：P0 Day 6 交付
配套：`scenarios.md`、`README.md`、`tests/test_upgrade_fake_graph.py`

## 1. 怎么读

测试文件共 28 条用例，编号 GF-01 到 GF-28，与本文第 3 节逐条对应。

GF-26 用它做自检：从测试文件里抽出全部 GF 编号，与本表出现的编号比对，多一个少一个都失败。

第 2 节按契约条款查，第 4 节按 P1 用例编号查。

## 2. 契约条款到测试

### 2.1 假图自身与确定性

| 契约条款 | 场景 | 测试 |
| --- | --- | --- |
| `api-v1.md` 1.2 固定 12 阶段，顺序与 `web/progress.py` 一致 | S00 | GF-01 |
| `report-schema-v1.md` 黄金样本与 `report-schema-v1.json` | S00 | GF-02 |
| 相同输入产生相同事件与报告 | S00 重复两次 | GF-04 |
| 不访问网络、模型、真实报告目录、随机数、系统时间 | S00 | GF-05 |
| 假图的流能驱动产品组件 | 5 阶段后订阅 | GF-06 |
| 命令行可独立运行 | S00 | GF-27 |

### 2.2 事件流

| 契约条款 | 场景 | 测试 |
| --- | --- | --- |
| `sse-events-v1.md` 3 节六类事件；`seq` 从 1 连续 | S00 | GF-03 |
| 终态顺序 `stats → status_changed → report_ready` | S00 | GF-03 |
| 终态统计等于各阶段之和 | S00 | GF-03 |
| 首帧 `snapshot` 的 `seq` 等于最大序号，不占序号 | S11 | GF-19 |
| `Last-Event-ID` 补发只读且连续 | S12 | GF-20 |
| 多路订阅互不影响、不改状态 | S11 | GF-19 |

### 2.3 状态机

| 契约条款 | 场景 | 测试 |
| --- | --- | --- |
| T01/T02/T03 创建、认领、完成 | S00 | GF-03 |
| T04 失败（阶段内部与阶段之后两种） | S04、S04B | GF-10、GF-11 |
| T05/T06/T09 暂停、落地、继续 | S02 | GF-08 |
| T12 暂停请求未落地时取消 | S02B | GF-28 |
| T13/T19 取消到终态 | S01、S03 | GF-07、GF-09 |
| T14 取消迟到、收尾先提交 | S09 | GF-16 |
| T20 暂停后取消（Day 6 新增） | S03 | GF-09 |
| I06 queued 上暂停必须被拒 | 直接调用 | GF-22 |
| `allowed_actions` 九个状态逐字一致 | 直接比对 | GF-22 |

### 2.4 幂等与冲突

| 契约条款 | 场景 | 测试 |
| --- | --- | --- |
| 第 1 步同键同体重放 | S10 | GF-18 |
| 第 2 步同键异体 409 | S10 | GF-18 |
| 第 3 步新键同指纹复用原任务 | S10 | GF-18 |
| 第 4 步同票同日异配置 409 | S10 | GF-18 |
| 第 5 步不同键只产生一个任务 | S10 | GF-18 |
| 任务结束后指纹释放，不再命中 | S10 | GF-18 |

### 2.5 崩溃边界

| 契约条款 | 场景 | 测试 |
| --- | --- | --- |
| B1 重启后保持 queued，Worker 正常认领 | 直接对账 | GF-21 |
| B2 无核心报告一律 interrupted | S05 | GF-12 |
| B3 未登记阶段产物写对账备注 | S06 | GF-13 |
| B4 未登记完整报告不自动判成功 | S07 | GF-14 |
| B5 补发 `report_ready` 且不重放 | S08 | GF-15 |
| B6 完成先落盘记 no-op | S09 | GF-16 |
| B6 取消先确认丢弃收尾 | S09B | GF-17 |
| paused 检查点缺失改判 interrupted | 直接对账 | GF-21 |
| pause_requested / cancel_requested 对账后 interrupted | 直接对账 | GF-21 |

### 2.6 文档与工具链

| 条款 | 测试 |
| --- | --- |
| `scenarios.md` 覆盖 S00 到 S12 且标题逐条出现 | GF-23 |
| Day 6 发现的四处契约缺口已回写 | GF-24 |
| 性能模板覆盖 P01 到 P08 并有机器可读模板 | GF-25 |
| 本表与测试文件编号一致 | GF-26 |
| 命令行输出与库内调用一致 | GF-27 |

## 3. 二十八条测试逐条说明

| 编号 | 测试函数 | 验证内容 |
| --- | --- | --- |
| GF-01 | `test_gf01_stage_catalog_matches_contract` | 12 个阶段 id、名称、顺序与 `web.progress.PIPELINE_STAGES` 及 `api-v1.md` 表格三处一致 |
| GF-02 | `test_gf02_golden_report_matches_fixture_and_schema` | S00 报告与黄金样本逐字段相等，通过 JSON Schema，内容哈希可复算 |
| GF-03 | `test_gf03_happy_path_event_order_and_counts` | 40 条事件、`seq` 为 1 到 40、24 条阶段事件、13 条统计、终态顺序与总量正确 |
| GF-04 | `test_gf04_repeated_runs_are_identical` | 两次运行的事件、任务详情、报告完全相同 |
| GF-05 | `test_gf05_no_network_model_or_real_report_dir` | 封死 socket 后照常跑完；AST 禁止导入真实依赖；源码不含写盘与环境读取 |
| GF-06 | `test_gf06_fake_stream_drives_real_progress_tracker` | 假图流经 `_detect_completed_stages` 驱动真实 `ProgressTracker`，阶段完成数与统计一致 |
| GF-07 | `test_gf07_create_then_cancel_queued` | T19：queued 直接取消，零调用、零报告、事件 2 条 |
| GF-08 | `test_gf08_pause_then_resume` | T05/T06/T09：暂停停在第 3 阶段边界，继续后跑完 12 阶段并成功 |
| GF-09 | `test_gf09_pause_then_cancel_uses_t20` | T20：paused 上取消先转 cancel_requested 再 cancelled，不直接跳终态 |
| GF-10 | `test_gf10_fail_after_stage_completes` | 阶段完成后异常：终态 failed，已完成阶段保留，`detail = post_stage_error` |
| GF-11 | `test_gf11_fail_inside_stage` | 阶段执行中异常：该阶段标 failed，后续阶段 pending，`detail = stage_failed` |
| GF-12 | `test_gf12_b2_interrupt_before_final_report` | B2：无核心报告，对账改判 interrupted，原因 lease_expired |
| GF-13 | `test_gf13_b3_stage_output_without_event` | B3：产物存在而事件未保存，改判 interrupted 并写对账备注 |
| GF-14 | `test_gf14_b4_report_written_before_db_commit` | B4：报告已写、数据库未提交，不自动判成功，备注提示未登记报告 |
| GF-15 | `test_gf15_b5_backfill_report_ready` | B5：保持 succeeded，补发 report_ready，序号续接不重排 |
| GF-16 | `test_gf16_b6_cancel_loses_to_finalization` | B6 第一种结局：收尾先提交，终态 succeeded，`detail = cancel_noop` |
| GF-17 | `test_gf17_b6_cancel_wins_before_commit` | B6 第二种结局：取消先确认，终态 cancelled，报告不写盘不提交 |
| GF-18 | `test_gf18_duplicate_create_requests` | 幂等五步：同键重放、新键复用、异体 409、活动冲突 409、十键只建一个任务 |
| GF-19 | `test_gf19_multi_browser_reconnect_is_read_only` | 两路订阅首帧相同；订阅前后任务详情、事件条数、序号不变 |
| GF-20 | `test_gf20_event_replay_after_disconnect` | 按 Last-Event-ID 补发 `seq > N` 的全部事件且连续；当前序号补发为空 |
| GF-21 | `test_gf21_reconcile_queued_and_checkpoint_missing` | B1 保持 queued；检查点缺失的 paused 改判 interrupted；三个非终态对账后均 interrupted |
| GF-22 | `test_gf22_allowed_actions_and_illegal_pause` | `allowed_actions` 九状态表逐字一致；queued 暂停抛 I06 且状态与事件不变 |
| GF-23 | `test_gf23_scenario_catalog_matches_docs` | 场景字典等于 S00 到 S09B 十三项；`scenarios.md` 覆盖 S00 到 S12 与十个关键标题 |
| GF-24 | `test_gf24_contract_write_backs_present` | 六份契约的 Day 6 回写逐条存在：T20、SM-14、reconcile_notes、审计记录不占序号、B1/B3 措辞、幂等第 3 步 |
| GF-25 | `test_gf25_performance_template_is_complete` | 性能模板含 P01 到 P08 八项；JSON 模板 `schema_version` 与指标键齐全 |
| GF-26 | `test_gf26_matrix_covers_every_test` | 本文 GF 编号集合等于测试文件 docstring 抽取结果，共 28 条 |
| GF-27 | `test_gf27_cli_runs_standalone` | 子进程运行命令行跑 S00，JSON 摘要与库内调用一致 |
| GF-28 | `test_gf28_pause_requested_then_cancel_uses_t12` | T12：pause_requested 上取消直接转 cancel_requested，不经过 paused |

## 4. P1 用例映射

P1 按 `p1-state-machine-tests.md` 的编号补真实内核测试。下表说明每个 P1 用例在假图里已有的替身。

### 4.1 合法与非法转换

| P1 用例 | 假图替身 | 说明 |
| --- | --- | --- |
| SM-01 创建 | GF-18 | 假账本覆盖创建与幂等，不覆盖数据库落库 |
| SM-02 认领 | GF-03 | S00 的 `queued → running` 与阶段开始 |
| SM-03 完成 | GF-02、GF-03 | 报告与内容哈希在内存中完整，落库留给 P1 |
| SM-04 失败 | GF-10、GF-11 | 两种失败位置都有 |
| SM-05 暂停 | GF-08 | 阶段边界生效 |
| SM-06 T07 暂停请求期间完成 | 无 | 假图 `finalize()` 支持 `pause_noop`，但未单列场景，P1 补 |
| SM-07 恢复 | GF-08 | paused 回 running 后从断点阶段继续 |
| SM-08 T10 忙时恢复 | 无 | paused 回 queued 需要 Worker 队列，假图没有队列，P1 补 |
| SM-09 取消 | GF-07、GF-28、GF-09 | 三个入口都覆盖到 cancel_requested 或直接终态 |
| SM-10 T14 取消迟到 | GF-16 | 终态 succeeded，取消记 no-op |
| SM-11 T12 取消优先 | GF-28 | 不经过 paused |
| SM-12 T19 排队取消 | GF-07 | 零调用 |
| SM-13 T16 到 T18 对账 | GF-12、GF-13、GF-14、GF-21 | 三个非终态与检查点缺失都覆盖 |
| SM-14 T20 暂停后取消 | GF-09 | Day 6 新增转换，假图先覆盖 |
| SM-I01 到 SM-I11 非法转换 | GF-22 只覆盖 I06 | 其余十条留给 P1，假图只证明结构可行 |

### 4.2 幂等与冲突

| P1 用例 | 假图替身 | 说明 |
| --- | --- | --- |
| ID-01 同键同体 | GF-18 | 200 重放 |
| ID-02 同键异体 | GF-18 | 409 mismatch |
| ID-03 同指纹新键 | GF-18 | 200 复用，带 existing 标记 |
| ID-04 活动冲突 | GF-18 | 409 active_conflict |
| ID-05 二十并发 | GF-18 部分 | 假图串行验证十个不同键只建一个任务；真实并发与唯一索引由 P1 测 |
| ID-06 详情 404 不创建 | 无 | 假图没有 HTTP 层，P1 补 |
| ID-07 刷新与重连不创建 | GF-19、GF-20 | 只读订阅与补发 |
| ID-08 报告 GET 零副作用 | 无 | 假图不建模报告接口，P1 补 |
| ID-09 PDF 缓存 | 无 | 由性能模板 P07 约束，P1 实现后测 |

### 4.3 崩溃边界

| P1 用例 | 假图替身 |
| --- | --- |
| CB-01 B1 | GF-21 |
| CB-02 B2 | GF-12 |
| CB-03 B3 | GF-13 |
| CB-04 B4 | GF-14 |
| CB-05 B5 | GF-15 |
| CB-06 B6 | GF-16、GF-17 |

## 5. 覆盖与缺口

已覆盖：

- 状态机二十条合法转换中，假图直接演练十六条；T07、T08、T10、T15 未单列场景，留给 P1 补。
- 非法转换只验证 I06 一条，证明拒绝路径可表达。
- 崩溃边界 B1 到 B6 六条全覆盖，含 B6 两种结局。
- 幂等五步全覆盖，并发条款用串行替身近似。
- SSE 的帧格式、序号连续、补发与只读订阅。

未覆盖，必须留给 P1：

- 数据库事务、唯一索引、租约、多进程竞态。
- HTTP 状态码、请求头、错误响应体。
- SSE 服务端心跳、限频、410 游标过期。
- 报告 GET、PDF 导出与缓存。
- 前端文案与按钮状态。

假图通过不代表这些项通过。P1 验收不得用 GF 编号代替 SM、ID、CB 用例。

## 6. 维护规则

新增测试时：

1. 编号顺延，不复用已删除编号。
2. 同步补第 3 节一行、第 2 节对应条款、第 4 节 P1 映射。
3. 跑 GF-26 确认编号集合一致。
4. 若测试依赖新场景，先按 `scenarios.md` 第 7 节补场景。

改契约时：先改契约，再改测试，最后改本表。顺序颠倒会让映射表变成事后编故事。
