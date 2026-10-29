# 契约冻结清单 v1

版本：v1（2026-10-29 冻结）
作用：把 P0 的契约内容固定成可校验的快照，P1 开工前不再口头约定。
校验：`tests/test_upgrade_contract_consistency.py::test_ct08_freeze_manifest_matches_contract_files`

## 1. 冻结范围与变更规则

冻结范围：本目录下 13 份契约 Markdown 与 2 份 JSON Schema，共 15 个文件。

允许变更，不升版本：

- 新增可选字段，且旧客户端忽略后行为不变。
- 新增错误码，且不复用既有码的含义。
- 新增文档章节、补充示例、修错别字与失效链接。
- 新增测试，不改既有断言。

需要升版本（v1.1 起）：

- 修改字段含义、类型或必填性。
- 修改状态机转换、`allowed_actions` 或对账规则。
- 修改报告章节 id、章节顺序或 `content_hash` 计算方式。
- 修改 SSE 事件类型、`seq` 规则或终态发送顺序。
- 修改错误码的 HTTP 状态或用户动作。

需要评审，评审通过才允许改：

- 删除字段、状态、事件类型、错误码或章节。
- 修改默认值、超时、保留窗口与限频参数。
- 替换任何一份黄金样本。

同步义务：

- 状态机新增状态时，必须同步 `semantic-dictionary.md` 文案、`api-v1.md` 的 `allowed_actions`、SSE 契约与 P1 用例。
- 报告结构变化时，必须同步 `report-schema-v1.json` 与 `tests/fixtures/upgrade/` 五份样本。
- SSE 规则变化时，必须同步假图事件实现与 `test_upgrade_fake_graph.py` 的断言。
- 任何冻结文件变化，必须在同一次提交更新本清单的哈希，并在当日评审记录写明理由。

## 2. 冻结文件与校验值

哈希为文件字节的 SHA-256，包含 UTF-8 BOM 与 CRLF 行尾，算法与校验代码一致。

| 文件 | SHA-256 | 说明 |
| --- | --- | --- |
| `api-v1.md` | `b0f53c59899313bcf2e41c0bd1122a777de8ce46838a8ca564a60c71516ab5b5` | 任务、报告与市场接口 |
| `core-wireframes.md` | `909c528c80164f4f075094cc117e5a5a9f25fbcad55ce1884378688b435ef000` | 十屏线框结构说明 |
| `crash-boundaries.md` | `721499392d166bf7a5b9b163bece89fdd8509c17f29fa60765067c9702f5379b` | 崩溃边界 B1–B6 |
| `error-codes-v1.md` | `5afc486e8ef6c8e210d89971649891feed3074ea1c5b7a286d82c4b6933e6b81` | 错误码与用户动作 |
| `idempotency-conflicts.md` | `ca0a1e0bb69d059289408bed780e6849da9b27cf8dc98a26525795df2a6bd371` | 幂等五步与冲突裁决 |
| `interaction-checklist.md` | `e536ad0817ced335aa79cb30f71f146e3eeef973950fef0fc84cce7b3eb60350` | 交互走查清单 |
| `job-state-machine.md` | `99ac0b9f92b86e94653074a29e7d29566285a42af679803dfa4f25cb6e6737c4` | 九状态、T01–T20、I01–I11 |
| `market-data-envelope-v1.json` | `e34a2242728fef59305e429f13c4004e4784a619f6522690839369baac5c7546` | 市场数据信封 Schema |
| `p1-state-machine-tests.md` | `357fc4e969b21446d798ab8861c05be85658d412db4122bd4a198e1bbb33433c` | P1 用例编号 SM/ID/CB/TX |
| `report-consistency-tests.md` | `d58f14ce9fd9631dacce3eee338df9700e89576d17ea165e8bdd9872aaeb0932` | 报告一致性测试清单 |
| `report-schema-v1.json` | `d189dc60ee93032d1f3cd84fbb0b8827976c8c75c1f4d13f8b6b530789bf9b80` | 报告 Schema |
| `report-schema-v1.md` | `9ec64472bd3b845981cb3ea0fc1a23fced5bf2085b5147286eed4e61c571316b` | 报告结构与归一化 |
| `routes.md` | `195c9f5077f5c73ad53fec39f7bdb8e443b1ef259936e0e096808e0189eb58a6` | 九条路由规则 |
| `semantic-dictionary.md` | `72cfa0a5bad64e1d76e6178ecac7465677f027ade08719e9e8d0fa84e9ae4aab` | 状态文案与禁用词 |
| `sse-events-v1.md` | `ecfb67191b9ffc339fff7e7cf31c51394320c9fa39302c3fbb7caf4614725cd7` | SSE 六类事件与序号规则 |

## 3. 冻结依据

- Day 2 语义、状态机、幂等与崩溃边界评审通过。
- Day 3 报告契约与五份黄金样本通过 Schema 校验。
- Day 4 接口、SSE、信封与错误字典评审通过。
- Day 5 十屏线框与十四条主线走查闭合。
- Day 6 假图与 28 条 GF 测试通过，演练发现的 4 处缺口已回写。
- Day 7 七组交叉检查全部通过，证据见 `p0-exit-review.md`。

## 4. 解除冻结

只有两种情况允许改冻结文件：

1. P0 出口评审结论为 No-Go，且改动用于消除 No-Go 项。
2. P1 实现发现契约本身有缺陷，且改动通过评审。

改动后重新冻结为 v1.1，更新本清单哈希，并在评审记录写清改了什么、为什么、影响哪些端。

不允许先改代码再补契约，也不允许只改契约不改测试。
