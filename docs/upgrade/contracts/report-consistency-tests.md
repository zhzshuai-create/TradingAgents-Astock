# 报告一致性测试清单（P0 Day 3）

P1/P3 实现报告存储与三端渲染时按本清单补测试。编号稳定，评审与回归引用编号。

黄金样本位置：`tests/fixtures/upgrade/`。schema 位置：`docs/upgrade/contracts/report-schema-v1.json`。

## 1. Schema 与样本（T1–T4）

| 用例 | 内容 | 断言要点 |
| --- | --- | --- |
| T1 | 四个 DTO 样本通过 schema 校验 | `final_state_v1 / missing_fields_report / long_report / unsafe_text_report` 全部 validate 通过 |
| T2 | schema 有牙齿 | 六类违规必须被拒：signal 与 rating 不一致、legacy_import 带 generated_at、未知章节 id、rating 超枚举、ticker 非六位、多余字段 |
| T3 | 旧样本键集合 | `legacy_report_v1.json` 的键是旧键集合的子集，无意外新增键 |
| T4 | 样本无密钥与隐私 | 正则扫描 sk- / api_key / Bearer / 手机号 / 邮箱，零命中 |

## 2. 归一化唯一性（T5–T8）

| 用例 | 内容 | 断言要点 |
| --- | --- | --- |
| T5 | 五档→三档映射 | Buy/Overweight→Buy、Hold→Hold、Underweight/Sell→Sell、unknown→unknown；逐档单测 |
| T6 | rating 解析不做猜测 | 对 21 份历史报告跑导入归一化：`**Rating**: X` 精确命中则 rating=X；未命中一律 unknown，**不允许**出现关键词扫描值进入 `meta.rating` |
| T7 | signal_legacy 只存档 | 归一化结果中 `signal_legacy` 等于旧 `extract_signal` 值，且渲染层不读取该字段（字符串扫描渲染代码） |
| T8 | 别名归一唯一 | 对照表每旧键恰一行：`trader_investment_plan` 只进 `legacy_aliases`，不进 body；mtime 不映射到任何字段 |

## 3. 三端一致（T9–T13）

| 用例 | 内容 | 断言要点 |
| --- | --- | --- |
| T9 | 同样本三端章节集合相同 | 网页目录、Markdown 标题序列、PDF 书签序列都等于 schema 第 3 节顺序表中「存在且非空」的章节 |
| T10 | content_hash 稳定 | 同一 DTO 重复序列化哈希不变；改动任一 body 后哈希变化 |
| T11 | 缺失不编造 | `missing_fields_report` 渲染：决策卡目标价/止损/时间范围显示「—」；目录不出现缺失章节；不出现「暂无数据」以外的填充文案 |
| T12 | 长报告不截断 | `long_report` 的 sec-market 渲染后字符数等于 body 字符数（允许分页标记，不允许内容丢失） |
| T13 | 不安全文本被转义 | `unsafe_text_report` 渲染后 DOM 中不存在可执行 script/onerror/javascript: 链接；markdown 注入不产生新 HTML 元素 |

## 4. 版本与导出（T14–T17）

| 用例 | 内容 | 断言要点 |
| --- | --- | --- |
| T14 | 重跑不覆盖 | 同 ticker+date 第二次成功分析产生新 report_id，旧报告仍可读取且 content_hash 不变 |
| T15 | 多版本共存 | 同 ticker+date 两条报告同时出现在列表，按 generated_at 倒序，null 排最后 |
| T16 | 打开报告零副作用 | GET 报告前后：事件表行数不变、无 PDF 文件新增、无外部行情请求（网络打桩计数为 0） |
| T17 | 旧报告补数导出有标注 | legacy_import 报告导出 PDF/MD 时，产物内含补数时间标注且 `chart_snapshot_status = refetch_needed` |

## 5. 覆盖核对

- T1–T4 对应 Day 3 验收「样本不含密钥」「缺失不编造」的机器化部分。
- T5–T8 对应「新旧字段别名有唯一归一化结果」。
- T9–T13 对应「同一黄金样本可明确表示网页、Markdown 和 PDF 的预期内容」。
- T14–T17 对应「同股票同日期两个版本可以同时存在」与导出规则。
- 合计 17 个用例编号位。
