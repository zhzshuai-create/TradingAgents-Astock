# 确定性假图使用说明（P0 Day 6）

日期：2026-10-29
状态：P0 Day 6 交付
配套：`scenarios.md`、`test-matrix.md`、`perf-template.md`、`tests/fake_analysis_graph.py`

## 1. 用途

P1 要在不调用真实模型的前提下测试任务全生命周期。

假图用固定样本和虚拟时钟执行十二个阶段，输出与契约一致的事件和报告。

它只服务测试、演示和故障演练，不进入产品运行路径。

## 2. 文件

| 文件 | 作用 |
| --- | --- |
| `tests/fake_analysis_graph.py` | 假图、假执行器、幂等账本、场景目录、命令行入口 |
| `tests/test_upgrade_fake_graph.py` | 28 条契约测试，编号 GF-01 到 GF-28 |
| `docs/upgrade/fake-graph/scenarios.md` | 崩溃与竞争场景清单 S00 到 S12 |
| `docs/upgrade/fake-graph/test-matrix.md` | 契约条款到测试的映射表 |
| `docs/upgrade/fake-graph/perf-template.md` | 八项性能指标的测量与记录格式 |

## 3. 三层接口

### 3.1 图层：FakeAnalysisGraph

| 方法 | 行为 | 真实 Runner 对应 |
| --- | --- | --- |
| `prepare_graph_run(ticker, date)` | 返回初始状态、参数、元信息 | `TradingAgentsGraph.prepare_graph_run` |
| `stream(init_state)` | 按固定顺序产出 12 个累积状态块 | `graph.stream(...)` |
| `finalize_graph_run(...)` | 返回三档信号 | `TradingAgentsGraph.finalize_graph_run` |
| `close_graph_run()` | 标记关闭，不落盘 | `close_graph_run` |
| `build_report(...)` | 生成 ReportDTO，只在内存 | 核心报告落盘逻辑 |

`stream` 产出的块与真实图同形：分析师阶段给报告键，辩论给 `investment_debate_state`，风控给 `risk_debate_state`。

因此同一份流既能喂假执行器，也能喂产品 `ProgressTracker`，见测试 GF-06。

### 3.2 执行层：FakeJobRunner

| 方法 | 行为 |
| --- | --- |
| `start()` | T02，queued 到 running，打开阶段流 |
| `advance()` | 跑到下一个阶段边界，最多执行一个阶段 |
| `run_all()` | 从 queued 开始一直跑到终态或 paused |
| `pause()` / `resume()` / `cancel()` | 受理控制请求，按状态机返回 accepted 或抛 `IllegalTransition` |
| `finalize(cancel_wins=...)` | 收尾；用于构造 B6 的两种结局 |
| `reconcile()` | 服务重启对账，覆盖 B1 到 B5 |
| `job_detail()` / `snapshot()` | 生成 JobDetail 与 SSE 首帧 |
| `replay(seq)` / `subscribe(seq)` | 断线补发与只读重连 |

控制请求只在阶段边界生效。

调用 `pause()` 或 `cancel()` 后再调用 `advance()`，会在启动下一个阶段之前停住，不会多跑一个阶段。

`IllegalTransition` 带 `rule` 字段，P1 把它映射为 HTTP 409 `illegal_transition`。

### 3.3 创建层：FakeJobLedger

`FakeJobLedger.create()` 实现 `idempotency-conflicts.md` 的五步判定：

1. 同键同体返回原任务，`replayed=True`。
2. 同键异体返回 409 `idempotency_mismatch`。
3. 幂等键未命中但同活动指纹存在，返回原任务，`existing_header=True`。
4. 同票同日不同配置且有活动任务，返回 409 `active_conflict`。
5. 否则创建新任务，返回 201。

第 3 步覆盖首次出现的新键，这样十个不同键的相同请求也只产生一个 job。

账本只在内存里，不模拟数据库事务与唯一索引。

## 4. 快速开始

### 4.1 命令行

```text
.venv/Scripts/python.exe tests/fake_analysis_graph.py --list
.venv/Scripts/python.exe tests/fake_analysis_graph.py --scenario S00
.venv/Scripts/python.exe tests/fake_analysis_graph.py --scenario S06 --json
```

### 4.2 Python

```python
import sys
sys.path.insert(0, "tests")

from fake_analysis_graph import (
    FakeAnalysisGraph,
    FakeJobRunner,
    run_scenario,
)

outcome = run_scenario("S00")
print(outcome.job["status"], len(outcome.events))

runner = FakeJobRunner(graph=FakeAnalysisGraph(fail_at="news"))
runner.run_all()
print(runner.status, runner.error)
```

### 4.3 暂停与继续

```python
runner = FakeJobRunner()
runner.start()
for _ in range(3):
    runner.advance()
runner.pause()
runner.advance()        # 在下一个阶段开始前停住
print(runner.status)    # paused
runner.resume()
runner.run_all()
```

### 4.4 模拟中断

```python
from fake_analysis_graph import FakeJobRunner, SimulatedInterrupt

runner = FakeJobRunner(interrupt_at="before:pm")
try:
    runner.run_all()
except SimulatedInterrupt:
    pass
runner.reconcile()
print(runner.status)    # interrupted
```

## 5. 确定性

虚拟时钟固定从 2026-10-24 09:30:00 +08:00 开始。

十二个阶段各 30 分钟，正常结束时正好是 15:30:00，与黄金样本的 `generated_at` 相同。

正常路径 S00 的固定输出：

| 项 | 值 |
| --- | --- |
| 事件总数 | 40 |
| 阶段事件 | 24 条（12 开始 + 12 结束） |
| 统计事件 | 13 条（每阶段一条，终态前再一条） |
| 模型调用 | 14 次 |
| 输入 Token | 182430 |
| 输出 Token | 41208 |
| 报告 | 与 `final_state_v1.json` 逐字段相等 |

相同输入重复运行，事件、报告、任务详情逐字段相同，见 GF-04。

实现约束：

- 不读取系统时间，只用虚拟时钟。
- 不使用随机数，报告 ID 由 `uuid5` 从 job id 派生。
- 不调用 `sleep`，阶段时长只写进事件字段。
- 不写磁盘，报告只存在于内存。

## 6. 不访问真实依赖

测试 GF-05 同时做两件事：

1. 把 `socket.socket` 替换为抛错函数，再跑完 S00。
2. 用 AST 扫描模块导入，禁止 `tradingagents`、`web`、`requests`、`urllib`、`http`、`socket`、`random`、`time`、`os`。

模块内也不出现 `write_text`、`write_bytes`、`open(`、`expanduser`、`Path.home`、`os.environ`、`time.sleep`。

唯一读取的文件是黄金样本 `tests/fixtures/upgrade/final_state_v1.json`。

不写真实用户报告目录，不读行情，不碰任何密钥。

## 7. 故障注入点

| 参数 | 取值 | 行为 | 对应边界 |
| --- | --- | --- | --- |
| `fail_at` | 阶段 id | 阶段开始前抛 `FakeGraphError`，该阶段标 failed | T04 |
| `fail_after` | 阶段 id | 阶段完成后抛错，已完成阶段保留 | T04 |
| `interrupt_at` | `before:<阶段>` | 阶段开始前模拟进程死亡 | B2 / T16 |
| `interrupt_at` | `after:<阶段>` | 阶段产物已写、done 事件未保存 | B3 / T16 |
| `interrupt_at` | `after_report` | 报告已写、数据库未提交 | B4 / T16 |
| `interrupt_at` | `after_commit` | 已提交并改状态、`report_ready` 未发 | B5 |
| `checkpoint_present` | `False` | paused 对账改判 interrupted，原因 `checkpoint_missing` | 状态机第 4 节 |
| `auto_finalize` | `False` | 最后阶段完成后停在 running，便于构造 B6 | B6 |
| `finalize(cancel_wins=True)` | 布尔 | 取消先确认，收尾产物丢弃 | B6 / T13 |

`SimulatedInterrupt` 继承 `BaseException`，普通 `except Exception` 不会吞掉它。

## 8. 与真实 Runner 的差异

假图刻意保留差异，避免把测试替身当成实现：

- 不做模型调用，阶段内容是黄金样本的反向映射。
- 不写检查点文件，`checkpoint_present` 是显式参数。
- 不实现数据库、唯一索引、租约和 HTTP 状态码。
- 控制请求只在阶段边界生效，没有真正的并发线程。
- 阶段时长是虚拟值，不能当性能数据用。

需要测数据库、SSE 服务端或 HTTP 语义时，P1 用本假图加真实内核实现。

## 9. 验收结果

| 项 | 结果 |
| --- | --- |
| 可重复产生一致结果 | GF-04 通过 |
| 可指定失败位置 | GF-10、GF-11 通过 |
| 可指定中断位置 | GF-12 到 GF-17 通过 |
| 默认路径无真实模型与行情 | GF-05 通过 |
| 与真实 ProgressTracker 对接 | GF-06 通过 |
| 场景清单与测试矩阵 | GF-23、GF-26 通过 |

## 10. 限制

假图不是 P1 任务内核。

它不证明数据库迁移、租约竞态、HTTP 契约或 SSE 服务端实现正确。

这些由 P1 的独立测试覆盖，假图只提供确定性输入。
