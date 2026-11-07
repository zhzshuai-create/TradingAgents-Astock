# P6-04pre 交接卡：真实执行器接入（P6-04a 的前置票）

一句话：新增 `backend/app/services/real_runner.py`，把 `TradingAgentsGraph` 接进现有 `AnalysisExecutor` 协议（12 阶段事件、累计转增量统计、report-v1 DTO），新增 `scripts/run_backend.py` 作为真实数据根入口；测试全部用桩图与桩统计，不建真实模型客户端、不联网。**本票不跑 Canary、不花钱。**

## 一、为什么要插入这一票

`P6拆票.md` 的 P6-04a 直接要求“一次人工批准的真实模型分析”，但新栈没有真实执行器：

- `backend/app/services/analysis_runner.py` 的 `create_analysis_executor` 在双开关成立时抛 `real_runner_unavailable`，注释与 `P1进度存档.md` 第 155 行都写着“P6 接真实执行器时再改这里”。
- `P6拆票.md` 的票表里没有任何一票承担“接入真实执行器”，这是拆票缺口，不是实现缺陷。

所以 P6-04a 的前置条件先由本票补齐；本票完成后 P6-04a 按原口径执行，不需要再改判据。

## 二、现在到哪

- HEAD 为 `44862fd`（P6-03 文档与证据）。P6-01 至 P6-03 已本地提交，未推送。
- 基线：Python 802 passed / 4 skipped；前端 534 tests；迁移头 `0007`；预检 10 PASS。
- 默认入口仍是旧版 8501；`run_all.bat` 未动。
- 真实模型配置事实（本机，2026-11-07）：
  - `~/.tradingagents/llm_config.json`：`llm_provider=mimo`、`quick=mimo-v2.6-flash`、`deep=mimo-v2.6-pro`、`llm_base_url` 为空、`parallel_analysts=true`。
  - 凭据在仓库根 `.env`（`MIMO_API_KEY` 等）；`.env` 目前只有 `web/app.py:27` 加载，新入口必须自己加载。

## 三、交付物与边界

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `backend/app/services/stage_map.py` | 新增 | 12 阶段目录与“状态字典 → 阶段正文”的纯映射；不 import `web` |
| `backend/app/services/real_runner.py` | 新增 | `RealAnalysisExecutor`：配置组装、图生命周期、阶段事件、统计增量、report DTO |
| `backend/app/services/analysis_runner.py` | 修改 | 工厂在双开关成立时返回真实执行器，不再抛 `real_runner_unavailable` |
| `backend/app/worker/runloop.py` | 新增 | 从 `dev_backend.py` 提取的 Worker 循环与信号处理，两个入口共用 |
| `scripts/dev_backend.py` | 修改 | 改为从 `runloop` 导入，行为不变 |
| `scripts/run_backend.py` | 新增 | 真实数据根入口：`.env`、`TA_DATA_ROOT`、迁移、API + Worker、`--real-models` |
| `tests/backend/test_real_runner.py` | 新增 | RR-01 至 RR-08 |
| `tests/backend/test_run_backend.py` | 新增 | 入口参数与路径解析（不起服务） |

边界：不改 `web/`、不改 `tradingagents/`、不改 `run_all.bat`、不碰 `trade-journal`；不加迁移、不加运行时依赖（`python-dotenv`、`alembic` 已在依赖里）；不推送；本票不调用真实模型。

## 四、七项决定

**D1 执行器在进程内跑图，不 import `web.*`**

`RealAnalysisExecutor` 直接 `from tradingagents.graph.trading_graph import TradingAgentsGraph`。旧版的阶段识别、报告写盘、断点文件都不复用；新栈的事件与报告入口只有 `AnalysisExecutor` 协议。

**D2 阶段映射独立成模块，靠测试对账**

`stage_map.py` 复制旧版的三类映射：

- 分析师：`market_report` / `sentiment_report` / `news_report` / `fundamentals_report` / `policy_report` / `hot_money_report` / `lockup_report` → 前七个阶段；
- `data_quality_summary` → `quality_gate`；`investment_debate_state.judge_decision` → `debate`；`trader_investment_plan` → `trader`；`risk_debate_state.judge_decision` → `risk`；`final_trade_decision` → `pm`。
- 正文只做 `<think>` 清洗；**不做**旧版的股票名称归一化（见第五节）。

同步性由 RR-06 保证：测试可以 import `web.progress`，断言两边的阶段 id 与 report_key 完全一致；后端代码本身不 import `web`。

**D3 报告 DTO 复用 `build_legacy_report`，元信息交给 `JobService`**

真实图跑完后的 `last_chunk` 就是旧版 `full_states_log` 的同一结构，直接 `build_legacy_report(last_chunk)` 得到 `sections` 与 `meta`；`JobService.finish_success` 里的 `finalize_report` 会覆盖 `job_id` / `generated_at` / `origin` / `content_hash` 等服务器权威字段，执行器不自己算哈希。

**D4 阶段续跑不支持，直接 fail-fast**

真实图只在整跑时可用；收到 `resume_from_stage` 就抛 `AnalysisRunError("real_resume_unsupported")`，不静默重跑已完成阶段。P6-04a 只跑新任务，不受影响；后续要补续跑单独开票。

**D5 入口与双开关**

`scripts/run_backend.py`：

- 数据根：`TA_DATA_ROOT`，缺省 `~/.tradingagents`；`TA_JOBS_DB` / `TA_JOB_REPORTS_DIR` 若已设置则优先。
- 启动时加载仓库根 `.env`，然后迁移到 head，起 API（8600）与一个 Worker。
- `--real-models` 把 `ServerConfig.real_runner_enabled` 置 True；真实执行仍需环境变量 `TA_ENABLE_REAL_RUNNER=1`，双开关语义不变（AD-01）。
- `write_mode` 仍只由 `ACTIVE_ANALYSIS_UI` 决定，入口不替用户改成 `next`。
- 不实现 8501 端口互锁（属 P6-06）；本票入口只在人工监督下用于 Canary。

**D6 配置优先级**

`llm_config.json` > 环境变量 > `DEFAULT_CONFIG`；任务快照再覆盖两项：

- `parallel_analysts` 用任务快照的值；
- `stage_toggles` 决定 `selected_analysts`：四个固定分析师 + `policy` / `hot_money` / `lockup` 中开启的项。

`data_vendors`、`max_debate_rounds=1`、`max_risk_discuss_rounds=1`、`output_language=Chinese` 与旧版 `_build_config` 一致。缓存、结果、记忆目录沿用 `DEFAULT_CONFIG` 的环境变量入口，测试指向 `tmp_path`。

**D7 统计口径：累计转增量，按阶段均分**

`StatsCallbackHandler.get_stats()` 返回累计值。执行器在每个超步结束时算与上一次的差，记到该步新完成的阶段上；并行分析师的同一步会同时完成多个阶段，增量按完成数均分（阶段行统计是展示用，累计总数以任务级为准）。`duration_ms` 用相邻超步的墙钟差。

## 五、已知差异（必须写进评审记录）

1. **股票名称归一化缺失**：旧版在落盘前把“000629”统一成“000629 攀钢钒钛”，依赖 `web/stock_display.py`（459 行，且带 web 依赖）。新栈不做，报告正文按模型原文保存。Canary 评审记录里要写明这一条，P6-07 出口前决定是否补。
2. **`llm_profile` 只是契约标签**：`deepseek-default` 不代表实际供应商；实际模型来自 `llm_config.json`。同配置快照在换模型后哈希不变，这是既有契约缺口，本票不改。
3. **逐阶段统计为估算**：并行超步均分，单阶段数字可能与真实调用不完全对应；任务级累计是准确值。

## 六、测试矩阵

| 编号 | 断言 |
| --- | --- |
| RR-01 | 双开关缺一即回假图；两个都成立返回 `RealAnalysisExecutor`，构造时不建模型客户端 |
| RR-02 | 桩图逐超步产出 12 个阶段：`started`/`done` 成对且顺序正确，`stages_completed` 为 12 项 |
| RR-03 | 并行超步一次完成多个阶段时，多阶段各收到 `done`，统计增量之和等于该步总增量 |
| RR-04 | `resume_from_stage` 非空时抛 `real_resume_unsupported`，桩图 `prepare_graph_run` 未被调用 |
| RR-05 | 报告 DTO 含 `sections`，`sec-decision` 等章节由状态字典正确派生；`job_id` / `generated_at` 留空，任务级字段由 `finalize_report` 覆盖 |
| RR-06 | `stage_map` 与 `web.progress.PIPELINE_STAGES` 的阶段 id、report_key 完全一致；`backend/` 源码不出现 `import web` / `from web` |
| RR-07 | 配置组装：`llm_config.json` 覆盖环境变量，任务快照覆盖并行开关；关闭 `policy` 后 `selected_analysts` 不含 `policy` |
| RR-08 | 阶段正文去掉 `<think>` 块；`data_quality_summary` 等五个非分析师键映射到正确阶段 |
| 入口 | `run_backend` 的数据根解析：`TA_DATA_ROOT` 生效、`TA_JOBS_DB` / `TA_JOB_REPORTS_DIR` 优先、缺省 `~/.tradingagents` |

## 七、验收命令

```bash
.venv/Scripts/python.exe -m pytest tests/backend/test_real_runner.py tests/backend/test_run_backend.py -q
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m alembic -c backend/alembic.ini heads
.venv/Scripts/python.exe scripts/p0_preflight.py --full --smoke
```

期望：RR 全绿；Python 全量 ≥802 passed / 4 skipped、0 failed；迁移头 `0007`；预检 10 PASS；`git diff --name-only` 不含 `web/`、`run_all.bat`、`tradingagents/`、`frontend/`。

## 八、环境

- 测试不读 `.env`、不读 API Key、不建真实 LLM 客户端、不联网、不写真实 `~/.tradingagents`。
- 桩图接口只要求四个方法：`prepare_graph_run`、`graph.stream`、`finalize_graph_run`、`close_graph_run`；桩统计只要求 `get_stats`。
- Windows 控制台 GBK：脚本输出沿用现有 ASCII 前缀 + 中文行。

## 九、回退

- 删除 `stage_map.py`、`real_runner.py`、`runloop.py`、`run_backend.py` 与两份测试；`analysis_runner.py` 恢复 `real_runner_unavailable`；`dev_backend.py` 恢复内联循环。
- 无迁移、无契约改动、无前端改动、无数据写入。

## 十、下一票

P6-04a 按原口径执行：`ACTIVE_ANALYSIS_UI=next` + `TA_ENABLE_REAL_RUNNER=1` + `run_backend.py --real-models`，单任务、人工批准费用上限；取证事件流、`model_calls`、报告 `content_hash` 与同 `Idempotency-Key` 重放。
