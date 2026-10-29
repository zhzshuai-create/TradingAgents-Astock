# 错误响应字典 v1（error-codes-v1）

日期：2026-10-29
状态：冻结候选（Day 4 交付）
配套：`api-v1.md`、`market-data-envelope-v1.json`

两条出口，不要混用：

- **接口错误**：请求不合法、对象不存在、状态冲突、服务端故障。用 HTTP 4xx/5xx + 错误体。
- **数据源错误**：接口本身正常，但某个数据源取不到数据。用 HTTP 200 + 信封 `status = error`，`error_code` 取第 4 节的源码。这样前端能区分「后端坏了」和「这只票今天没数据」。

---

## 1. 错误体形状

```json
{
  "error": {
    "code": "active_conflict",
    "message": "该股票今日已有进行中的分析",
    "request_id": "req_01J8Z3K4",
    "details": {"active_job_id": "5b1c..."}
  }
}
```

| 字段 | 必需 | 规则 |
| --- | --- | --- |
| `code` | 是 | 本文件第 2、4 节的枚举值，机器判定用 |
| `message` | 是 | 可直接展示的中文安全文案；同码文案固定，不做变量拼接以外的拼装 |
| `request_id` | 是 | 与响应头 `X-Request-Id` 相同，日志可对账 |
| `details` | 否 | 白名单字段：对象 id、字段名、允许值、冲突任务 id。禁止异常文本、堆栈、路径、密钥 |

`details` 里允许出现的键只有：`job_id`、`report_id`、`export_id`、`active_job_id`、`field`、`allowed_values`、`candidates`、`from`、`to`、`rule`、`retry_after_ms`。多一个键即视为契约违规。

---

## 2. 接口错误码

| code | HTTP | 触发条件 | 安全文案 | 客户端动作 |
| --- | --- | --- | --- | --- |
| `invalid_request` | 400 | JSON 解析失败、类型不对、查询参数取值非法、超出长度上限 | 请求格式不正确 | 修请求；不要重试 |
| `idempotency_key_required` | 400 | 创建任务或重试未带 `Idempotency-Key` | 缺少幂等键 | 生成 UUID 后重发 |
| `method_not_allowed` | 405 | 方法不对，如对 SSE 端点发 POST | 不支持该请求方法 | 修调用 |
| `job_not_found` | 404 | job id 不存在 | 没有找到这个任务 | 回任务列表；不要自动创建 |
| `report_not_found` | 404 | report id 不存在 | 没有找到这份报告 | 回报告列表 |
| `export_not_found` | 404 | export id 不存在 | 没有找到这个导出任务 | 重新发起导出 |
| `stage_not_found` | 404 | stage id 不在固定 12 个阶段内 | 没有找到这个阶段 | 刷新任务详情；按固定阶段列表修正请求 |
| `sse_cursor_expired` | 410 | 重连的 `Last-Event-ID` 早于事件保留窗口 | 事件流已过期，请刷新任务页 | 用 GET 任务详情重建页面，**不创建任务** |
| `idempotency_mismatch` | 409 | 同一幂等键提交了不同请求体 | 该请求与之前的提交不一致 | 换新幂等键，或复用原请求体 |
| `active_conflict` | 409 | 同票同日已有活动任务且配置不同 | 该股票今日已有进行中的分析 | 等它结束，或先取消 |
| `illegal_transition` | 409 | 当前状态不允许该动作，对应 I01–I11 | 当前状态不支持这个操作 | 刷新任务详情，按 `allowed_actions` 重画按钮 |
| `resume_fingerprint_mismatch` | 409 | 续跑时配置指纹或图版本不一致 | 配置已变化，无法从检查点继续 | 只给「重新分析」 |
| `export_not_ready` | 409 | 导出尚未 ready 时请求文件 | 导出尚未完成 | 轮询导出状态 |
| `ticker_unresolved` | 422 | 代码或名称解析不到 | 找不到这只股票 | 改输入；搜索接口可给候选 |
| `ticker_ambiguous` | 422 | 中文名匹配到多只 | 匹配到多只股票，请选择一只 | 用 `details.candidates` 让用户选 |
| `invalid_date` | 422 | 日期格式错误或晚于今天 | 分析日期不正确 | 修日期 |
| `config_unknown_key` | 422 | `config` 出现白名单外键 | 不支持的配置项 | 删掉该键；服务端配置不可由前端提交 |
| `config_invalid_value` | 422 | 枚举值非法 | 配置取值不支持 | 按 `details.allowed_values` 修 |
| `rate_limited` | 429 | 超出并发或频率上限 | 操作太频繁，请稍后再试 | 按 `details.retry_after_ms` 退避 |
| `internal_error` | 500 | 未预期异常 | 服务暂时不可用 | 重试一次，仍失败则报 request id |
| `not_implemented` | 501 | P0 未实现的市场接口 | 该功能尚未开放 | 显示「建设中」，不重试 |
| `upstream_error` | 502 | 服务端依赖的外部服务报错，且无降级数据 | 数据服务暂时不可用 | 稍后重试 |
| `upstream_timeout` | 504 | 外部服务超时，且无降级数据 | 数据服务响应超时 | 稍后重试 |
| `unauthorized` | 401 | 预留：未来启用鉴权后使用 | 未授权 | 重新登录 |

注意：数据源失败如果发生在市场接口内部，优先用 HTTP 200 + 信封表达（第 4 节），不要用 502/504 顶替。502/504 只用于「整个接口都拿不到任何可用数据，且无法形成信封」的极端情况。

---

## 3. 状态冲突与转换编号

`illegal_transition` 的 `details.rule` 取 `job-state-machine.md` 的编号：

- I01–I11：非法状态转换，任何入口一律 409。
- `paused → cancelled` 走 I11，必须先 `cancel_requested` 再收尾。
- 重复提交同一控制动作不算非法转换：返回 200 `accepted = false, reason = already_pending`（见 `api-v1.md` 1.6）。

---

## 4. 数据源错误码（信封内 `error_code`）

| code | 含义 | 典型来源 | 顶层 status |
| --- | --- | --- | --- |
| `upstream_timeout` | 数据源超时 | mootdx / 腾讯 / 东财 / 同花顺 | error |
| `upstream_error` | 数据源返回错误或非预期结构 | 同上 | error |
| `upstream_rate_limited` | 数据源限流 | 东财、同花顺 | error |
| `data_parse_error` | 数据源有响应但字段解析失败 | 腾讯行情、东财资金流 | error |

四个码都允许出现在区块级（`blocks.*.error_code`）。顶层 `status = error` 时顶层 `error_code` 必填；顶层 `status` 为 ok / empty / stale 时顶层 `error_code` 必须为 null，失败信息只留在 `blocks` 里。

`stale_reason` 不属于错误码，取值见 `api-v1.md` 3.0：`ttl_exceeded`、`trading_day_mismatch`、`upstream_fallback`。

---

## 5. 不许出现的内容（实现与测试断言）

错误体与信封的任何字符串字段都不得包含：

1. Python 堆栈特征：`Traceback (most recent call last)`、`File "`、`line `。
2. 密钥特征：`sk-`、`api_key`、`Authorization`、`token=`。
3. 路径特征：Windows 盘符路径、`/home/`、`/Users/`、`C:\`。
4. 内部主机名或 IP 直连地址。

`tests/test_upgrade_market_envelope.py` 对五份样本做这四项扫描；服务端实现阶段加同一份断言的集成测试。
