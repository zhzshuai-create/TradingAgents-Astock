# 报告结构契约 v1（report-schema-v1）
版本：v1（2026-10-29 冻结）

日期：2026-10-29
状态：冻结候选（Day 3 交付）
配套文件：`report-schema-v1.json`（机器可读）、`tests/fixtures/upgrade/*.json`（黄金样本）、`report-consistency-tests.md`（一致性测试清单）

目标：让「刚完成的报告」「历史导入报告」「网页」「Markdown」「PDF」消费同一份规范结构（ReportDTO），任何一端都不再直接理解 Python 私有对象或数组下标。

---

## 1. 字段盘点（来源 × 别名 × 必需 × 缺失表现）

盘点路径：

| 代号 | 路径 | 说明 |
| --- | --- | --- |
| S1 | `tradingagents/graph/trading_graph.py::_log_state` | 核心报告落盘（`full_states_log_<date>.json`） |
| S2 | `web/history.py::load_analysis / extract_signal` | 历史文件读取与信号提取 |
| S3 | `web/components/report_viewer.py::render_report / decision_facts` | 网页阅读器 |
| S4 | `web/pdf_export.py::generate_markdown` | Markdown 导出 |
| S5 | `web/pdf_export.py::generate_pdf` | PDF 导出 |
| S6 | `web/stock_display.py::_REPORT_STR_KEYS / _REPORT_DICT_KEYS` | 报告字典归一 |
| S7 | `cli/display.py` | CLI 展示（含历史别名） |

### 1.1 顶层字段

| 旧键 | 类型 | 消费方 | 别名 | 必需 | 缺失时表现（现状） | v1 归一化 |
| --- | --- | --- | --- | --- | --- | --- |
| `company_of_interest` | str | S1,S3,S4,S5,S6 | `ticker` | 是 | 落盘必写 | `meta.ticker_code` |
| `trade_date` | str(YYYY-MM-DD) | S1,S2,S3,S4,S5 | `analysis_date` | 是 | 落盘必写 | `meta.analysis_date` |
| `market_report` | str | S1,S3,S4,S5,S6 | 「技术分析」 | 是 | 章节不渲染 | `sections[sec-market]` |
| `sentiment_report` | str | 同上 | 「市场情绪」 | 是 | 章节不渲染 | `sections[sec-sentiment]` |
| `news_report` | str | 同上 | 「新闻舆情」 | 是 | 章节不渲染 | `sections[sec-news]` |
| `fundamentals_report` | str | 同上 | 「基本面」 | 是 | 章节不渲染 | `sections[sec-fundamentals]` |
| `policy_report` | str | S1(get),S3,S4,S5,S6 | 「政策分析」 | 否 | 章节不渲染 | `sections[sec-policy]`，可缺 |
| `hot_money_report` | str(get) | 同上 | 「游资追踪」 | 否 | 章节不渲染 | `sections[sec-hot-money]`，可缺 |
| `lockup_report` | str(get) | 同上 | 「解禁/减持」 | 否 | 章节不渲染 | `sections[sec-lockup]`，可缺 |
| `data_quality_summary` | str(get) | S1(get),S3,S6 | 「数据质量」 | 否 | 章节不渲染 | `sections[sec-quality]` + `meta.data_quality_status` |
| `investment_debate_state` | dict | S1,S3,S4,S5,S6 | — | 是 | 多空章节不渲染 | `sections[sec-debate]`（子结构见 1.2） |
| `trader_investment_decision` | str | S1,S2,S3,S4,S5,S6 | — | 是 | 交易员章节不渲染 | `sections[sec-trader]` |
| `trader_investment_plan` | str | 仅 S7 | 与 `investment_plan` 混用 | 否 | CLI 不展示 | **废弃**：导入时若非空且与 `investment_plan` 不同，保留为 `sections[sec-plan].legacy_aliases`，不参与渲染 |
| `investment_plan` | str | S1,S2,S3,S4,S5,S6 | 「最终投资建议」 | 是 | 决策章节不渲染 | `sections[sec-plan]` |
| `final_trade_decision` | str | S1,S2,S3,S4,S5,S6 | — | 是 | 决策卡与信号缺失 | `sections[sec-decision]` + 结构化 `meta.rating` 解析源 |
| `risk_debate_state` | dict | S1,S3,S4,S5,S6 | — | 是 | 风控章节不渲染 | `sections[sec-risk]`（子结构见 1.2） |

### 1.2 辩论子结构

| 旧路径 | v1 归一化 | 缺失表现 |
| --- | --- | --- |
| `investment_debate_state.bull_history` | `sections[sec-debate].parts[bull]` | 该 part 不展示 |
| `investment_debate_state.bear_history` | `sections[sec-debate].parts[bear]` | 该 part 不展示 |
| `investment_debate_state.history` | `sections[sec-debate].parts[history]` | 该 part 不展示 |
| `investment_debate_state.current_response` | `sections[sec-debate].parts[current]` | 该 part 不展示 |
| `investment_debate_state.judge_decision` | `sections[sec-debate].parts[judge]` | 该 part 不展示 |
| `risk_debate_state.aggressive_history` | `sections[sec-risk].parts[aggressive]` | 该 part 不展示 |
| `risk_debate_state.conservative_history` | `sections[sec-risk].parts[conservative]` | 该 part 不展示 |
| `risk_debate_state.neutral_history` | `sections[sec-risk].parts[neutral]` | 该 part 不展示 |
| `risk_debate_state.history` | `sections[sec-risk].parts[history]` | 该 part 不展示 |
| `risk_debate_state.judge_decision` | `sections[sec-risk].parts[judge]`；**注意**：框架把同一段文本同时写入 `risk_debate_state.judge_decision` 与 `final_trade_decision`（见 `pdf_export.py` 注释），导入时若两者完全相同，`sec-risk.parts[judge]` 置为引用 `sec-decision`，不重复存储 | 该 part 不展示 |

### 1.3 派生字段（现状为正则/关键词扫描，v1 改为结构化）

| 派生量 | 现状来源 | 现状问题（实测证据） | v1 归一化 |
| --- | --- | --- | --- |
| 五档评级 rating | `final_trade_decision` 文本中 `**Rating**: X`（`schemas.py::render_pm_decision` 渲染） | 结构化值在落盘前被渲染成 markdown，保存后只能正则取回 | `meta.rating` ∈ {Buy, Overweight, Hold, Underweight, Sell, unknown}；导入时按 `**Rating**:` 精确解析，解析失败为 `unknown`，**不做关键词猜测** |
| 三档展示信号 signal | `history.extract_signal`：按 `investment_plan → trader_investment_decision → final_trade_decision` 顺序扫描 BUY/SELL/HOLD 关键词 | **与评级矛盾**：对 21 份历史报告审计，3 份扫描为 Buy 而评级为 Sell，2 份 Buy/Underweight、2 份 Sell/Underweight、1 份 N/A；Overweight/Underweight 不含三个关键词，直接落到 N/A 或被前文无关词劫持 | `meta.signal` 由 `meta.rating` 按固定映射导出：Buy/Overweight→Buy，Hold→Hold，Underweight/Sell→Sell，unknown→unknown；旧扫描值仅存 `meta.signal_legacy` 供对照，不参与展示 |
| 目标价 target | `decision_facts` 正则（`**Price Target**:` / `目标价`） | 双格式兼容已做，缺失返回 None | `meta.price_target`（number|null） |
| 止损参考 stop | `decision_facts` 正则（`止损|止损位|硬止损`） | 同上 | `meta.stop_reference`（string|null） |
| 时间范围 horizon | `decision_facts` 正则（`**Time Horizon**:` / `时间范围|周期|跨度`） | 同上 | `meta.time_horizon`（string|null） |

审计命令（可复跑）：遍历 `~/.tradingagents/logs/*/TradingAgentsStrategy_logs/full_states_log_*.json`，对比 `extract_signal(d)` 与 `**Rating**: X` 解析值；21 份样本组合分布：
`{(Buy,Overweight):3, (Hold,Hold):4, (Sell,Underweight):2, (Buy,Underweight):2, (Sell,None):2, (N/A,None):1, (Buy,Sell):3, (Buy,Hold):2, (Buy,None):2}`。

另：21 份历史报告**全部**没有非空 `data_quality_summary`（质量门控为后加阶段），故 v1 中该章节与 `meta.data_quality_status` 均为可空，导入旧报告时 `data_quality_status = "absent"`，网页显示「—」而非编造。

---

## 2. 报告元数据（ReportDTO.meta）

| 字段 | 类型 | 必需 | 说明 |
| --- | --- | --- | --- |
| `report_id` | string(uuid) | 是 | 每次成功分析新建；重跑不覆盖 |
| `job_id` | string 或 null | 否 | 历史导入报告为 null |
| `ticker_code` | string | 是 | 如 `000629` |
| `ticker_name` | string 或 null | 否 | 导入旧报告可为 null，显示回退为 code |
| `analysis_date` | string(YYYY-MM-DD) | 是 | 分析标的日期 |
| `generated_at` | string(ISO8601) 或 null | 否 | 实际生成时间；**旧报告无真实生成时间时为 null，禁止用文件 mtime 冒充**，同时 `generated_at_source = "unknown"` |
| `generated_at_source` | enum: job_clock, import_clock, unknown | 是 | 标明时间来源 |
| `origin` | enum: new, legacy_import | 是 | 报告来源 |
| `schema_version` | string | 是 | 固定 `report-v1` |
| `content_hash` | string(sha256) | 是 | 对 `sections` 规范序列化结果计算；网页/MD/PDF 一致性校验依据 |
| `config_digest` | string 或 null | 否 | 生成配置摘要（模型、阶段开关） |
| `data_quality_status` | enum: ok, degraded, absent | 是 | 旧报告为 absent |
| `chart_snapshot_status` | enum: frozen, refetch_needed, none | 是 | 新版尽量 frozen；旧报告为 none |
| `retry_of_job_id` | string 或 null | 否 | 重试来源任务 |
| `rating` | enum 五档+unknown | 是 | 见 1.3 |
| `signal` | enum: Buy, Hold, Sell, unknown | 是 | 由 rating 映射 |
| `signal_legacy` | string 或 null | 否 | 旧扫描值，仅对照 |
| `price_target` | number 或 null | 否 | |
| `stop_reference` | string 或 null | 否 | |
| `time_horizon` | string 或 null | 否 | |

---

## 3. 章节结构（ReportDTO.sections）

- `sections` 为**对象**，键为稳定章节 ID；顺序由下表固定，前端按表渲染目录，**禁止依赖数组下标**。
- 每章：`{id, title, body, parts?, legacy_aliases?}`；`body` 为清洗后 markdown 文本。
- 缺失规则统一：章节键不存在或 body 为空 → 该章节**不渲染且不出现在目录**；决策卡单元格缺失显示「—」。任何端不得静默截断 body；导出分页由渲染层处理。

| 顺序 | id | 标题 | 来源旧键 |
| --- | --- | --- | --- |
| 1 | sec-decision | 最终交易决策 | `final_trade_decision` |
| 2 | sec-market | 技术分析 | `market_report` |
| 3 | sec-sentiment | 市场情绪 | `sentiment_report` |
| 4 | sec-news | 新闻舆情 | `news_report` |
| 5 | sec-fundamentals | 基本面 | `fundamentals_report` |
| 6 | sec-policy | 政策分析 | `policy_report` |
| 7 | sec-hot-money | 游资追踪 | `hot_money_report` |
| 8 | sec-lockup | 解禁/减持 | `lockup_report` |
| 9 | sec-quality | 数据质量 | `data_quality_summary` |
| 10 | sec-debate | 多空辩论 | `investment_debate_state` |
| 11 | sec-trader | 交易员决策 | `trader_investment_decision` |
| 12 | sec-plan | 最终投资建议 | `investment_plan` |
| 13 | sec-risk | 风控评估 | `risk_debate_state` |

注：网页现状把 `investment_plan` 的标题也叫「最终投资建议」（`report_viewer.py` 216 行），与 `final_trade_decision` 同标题；v1 起 `sec-decision` 标题为「最终交易决策」，`sec-plan` 为「最终投资建议」，消除重名。

---

## 4. 版本与导出规则

1. 每次成功分析生成新 `report_id`；重跑、重试一律新建，不覆盖旧报告。
2. 同 `ticker_code + analysis_date` 允许多版本共存；列表按 `generated_at` 倒序，`generated_at` 为 null 的排最后。
3. 网页、Markdown、PDF 三者从同一 ReportDTO 渲染，渲染前校验 `content_hash` 一致。
4. 打开报告（GET）不生成 PDF、不请求外部行情；PDF 仅在显式导出动作时生成。
5. 新版报告冻结图表输入（`chart_snapshot_status = frozen`）；旧报告补数导出必须写入 `chart_snapshot_status = refetch_needed` 并在导出页标注补数时间。
6. 旧报告导入：`origin = legacy_import`、`generated_at = null`、`generated_at_source = unknown`、`data_quality_status = absent`、`chart_snapshot_status = none`。

---

## 5. 新旧字段对照表（归一化唯一结果）

| 旧键/旧来源 | v1 路径 | 归一化规则 |
| --- | --- | --- |
| `company_of_interest` | `meta.ticker_code` | 原样 |
| `trade_date` | `meta.analysis_date` | 原样 |
| 文件 mtime | — | **丢弃**，不映射到任何时间字段 |
| `**Rating**: X` 文本 | `meta.rating` | 精确匹配五档；失败→unknown |
| `extract_signal` 扫描值 | `meta.signal_legacy` | 原样存档，不展示 |
| `meta.rating` | `meta.signal` | Buy/Overweight→Buy；Hold→Hold；Underweight/Sell→Sell；unknown→unknown |
| `**Price Target**: n` / `目标价 n` | `meta.price_target` | 数值解析；失败→null |
| `止损…n` | `meta.stop_reference` | 原样字符串；失败→null |
| `**Time Horizon**: t` / `时间范围 t` | `meta.time_horizon` | 原样字符串；失败→null |
| 7 个分析师键 | `sections[sec-*].body` | 清洗（去 think 标签/框架标记/代码围栏/跨章去重）后原样 |
| `data_quality_summary` | `sections[sec-quality].body` + `meta.data_quality_status` | 空→absent 且章节不渲染 |
| `investment_debate_state.*` | `sections[sec-debate].parts.*` | 空子键丢弃 |
| `risk_debate_state.*` | `sections[sec-risk].parts.*` | 与 `final_trade_decision` 相同的 judge 文本改为引用 |
| `trader_investment_plan` | `sections[sec-plan].legacy_aliases` | 仅存档 |
| `investment_plan` | `sections[sec-plan].body` | 清洗后原样 |
| `final_trade_decision` | `sections[sec-decision].body` | 清洗后原样 |

---

## 6. 验收映射

| Day 3 验收项 | 本契约对应条款 |
| --- | --- |
| 同一黄金样本可明确表示网页/MD/PDF 预期内容 | §3 章节表 + §4.3 content_hash |
| 新旧字段别名有唯一归一化结果 | §5 对照表（每旧键恰一行） |
| 缺失字段不会导致前端编造数据 | §1 缺失表现列 + §3 缺失规则 + §2 可空字段 |
| 同股票同日期两个版本可同时存在 | §4.1、§4.2 |
| 样本不含真实密钥和个人数据 | 黄金样本生成脚本扫描断言（见 `report-consistency-tests.md` T9） |
