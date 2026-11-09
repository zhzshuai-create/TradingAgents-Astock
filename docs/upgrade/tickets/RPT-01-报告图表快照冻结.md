# RPT-01 新报告冻结图表输入（chart_snapshot_status=frozen）

一句话：任务成功时把「行情快照 + 日 K」写进 `<job>/chart_snapshot.json`，只有文件真正落盘才把报告标成 `frozen`；抓取或写盘失败一律回落 `none`，报告照常成功。

**状态：待开工，未分配提交。** 无外部依赖，不碰 api-v1，不需要数据库迁移。

> 编号说明：叫 RPT-01 而不是 R2，因为回滚手册已有 R2 步骤，避免同名。

## 一、为什么开这张票

| 事实 | 证据 |
| --- | --- |
| 契约要求新版报告冻结图表输入 | `docs/upgrade/contracts/report-schema-v1.md:138`：新版报告 `chart_snapshot_status = frozen`；旧报告补数必须是 `refetch_needed` |
| 枚举只有三个值 | 同文件 `:95`：`frozen / refetch_needed / none` |
| 真实跑出的报告全部是 `none` | `backend/app/services/real_runner.py:356` 用 `build_legacy_report`，其 meta 默认 `chart_snapshot_status="none"`（`report_schema.py:260`） |
| 假图报告写的是 `frozen`，但没有对应数据文件 | `tests/fake_analysis_graph.py:50` 指向 `final_state_v1.json`，fixture 的 meta 是 `frozen`；worker 没有写过任何快照 |
| 状态字段已经在 DTO、DB、前端类型里 | `frontend/src/api/types.ts:272`、`backend/app/models/report.py:42`；前端只展示了 `data_quality_status`，没有展示快照状态 |
| 当前 PDF 只有文字，没有图表 | `backend/app/services/pdf_renderer.py` 只做文本渲染 |
| 落盘时机已有一个可复用的先例 | `backend/app/worker/main.py:326-343`：`report.json` 在终态事务之前写，失败不影响提交 |

结论：现在 `frozen` 是一个「有人写、没人兑现」的字段。本票把它改成证据驱动：有快照文件才 frozen，没有就 none，并且 `none` 不再被 fixture 冒充成 `frozen`。

## 二、本票口径（先定死）

**D1 快照是文件证据，不是新契约。**

路径固定为 `<job>/chart_snapshot.json`，由 `ReportStore` 读写；不新增数据库表、不新增 `api-v1` 字段、不新增接口、不改 `report-schema-v1` 结构。`chart_snapshot_status` 仍只有三个值。

**D2 只冻结图表真正需要的东西。**

按股票取两块：行情快照（`stock:snapshot:quote`）与日 K（`stock:kline`，`day`，120 根）。不抓估值、不抓板块。理由：板块当前受百度风控（见 R1），估值与图表无关；少抓一块就少一次失败面。

**D3 状态判定只有一条规则。**

`frozen` 当且仅当行情与日 K 两块都拿到可用数据（`ok` 或 `stale`，且 `data` 非空）；否则 `none`。`empty`、`error`、缺块都算 none。`stale` 可以 frozen，因为历史数据仍有 `as_of`，图表要的是「当时看到的那份数据」，不是「必须实时」。

**D4 `frozen` 必须以文件写成功为前提。**

顺序固定：抓取 → 写 `chart_snapshot.json` → 把状态传给终态事务。写盘失败时状态必须是 `none`，并在日志里留异常栈。数据库里的 `frozen` 不允许出现「文件不存在」的情况。

**D5 抓取失败绝不拖垮报告。**

任何异常（供应商超时、JSON 解析、磁盘错误）都只让状态变 `none`，`finish_success` 照常提交。快照不是报告成功的前置条件。

**D6 覆盖所有成功出口。**

T03（正常完成）、T07（pause_noop）、T14（cancel_noop）三条路径都要走同一段快照逻辑；不要在一条路径上漏掉，否则同一份报告会因控制请求而状态不同。

**D7 默认关闭，显式接线。**

`Worker` 新增可选参数 `chart_snapshotter`，默认 `None`。默认 None 时行为与今天完全一致（状态 none），全部离线测试不需要网络。`scripts/run_backend.py` 显式注入真实实现，并支持 `TA_CHART_SNAPSHOT=0` 关闭，作为回滚开关。

**D8 不对旧报告补快照。**

`origin=legacy_import` 与兼容投影永远保持 `none`，不尝试补数；补数导出属于未来的 `refetch_needed` 逻辑，不在本票。

**D9 前端只加一行只读展示。**

报告阅读器元信息增加「图表快照」：`frozen=分析时冻结`、`refetch_needed=需补数`、`none=无`。不加操作按钮，不改导出流程。

## 三、开工步骤

### 3.1 数据采集（`backend/app/services/stock_service.py`）

新增 `chart_inputs(ticker)`：

- 用 `self._cache.get_or_fetch("stock:snapshot:quote", {"ticker": ticker}, lambda: self._providers.quote(ticker), source="tencent")`；
- 用 `self._cache.get_or_fetch("stock:kline", {"ticker": ticker, "period": "day", "limit": 120}, lambda: self._providers.kline(ticker, "day", 120), source="mootdx")`；
- 用 `build_blocks_envelope({"quote": ..., "kline": ...})` 合并，保留 `blocks` 里的逐块 `status/source/as_of/fetched_at`。

不新增 endpoint id，`STALE_AFTER` 不动。K 线缓存 TTL 仍是 5 分钟（`market_cache.py:39`），所以刚分析完的任务命中缓存的概率很高。

### 3.2 快照服务（新文件 `backend/app/services/chart_snapshot.py`）

```text
CHART_SNAPSHOT_VERSION = "chart-snapshot-v1"

class ChartSnapshotter(Protocol):
    def capture(self, ticker: str, *, content_hash: str) -> dict[str, Any]: ...

class MarketChartSnapshotter:
    def __init__(self, stock: StockService, *, clock=now_cst): ...
```

`capture` 产出的结构固定为：

```json
{
  "schema_version": "chart-snapshot-v1",
  "ticker": "600000",
  "captured_at": "2026-11-08T21:30:00+08:00",
  "report_content_hash": "64位小写十六进制",
  "status": "frozen",
  "reason": null,
  "blocks": {
    "quote": { "status": "ok", "source": "tencent", "as_of": "...", "fetched_at": "...", "data": {} },
    "kline": { "status": "ok", "source": "mootdx", "as_of": "...", "fetched_at": "...", "data": { "bars": [] } }
  }
}
```

- `status` 按 D3 计算；`reason` 失败时写 `quote_error` / `kline_error` / `quote_empty` / `kline_empty`，成功为 null。
- 落盘前断言 JSON 可序列化；单文件超过 512 KiB 时丢弃并记 `oversize`，状态 none（120 根日 K 正常远低于此）。

### 3.3 存取（`backend/app/services/report_store.py`）

- 常量 `CHART_SNAPSHOT_NAME = "chart_snapshot.json"`；
- `write_chart_snapshot(job_id, payload) -> str`：与 `write_final_report`（第 99 行）同款 `tmp` + `os.replace`，目录用 `_component(job_id)`；
- `read_chart_snapshot(job_id) -> dict | None`：只接受 `schema_version == "chart-snapshot-v1"`、`ticker`、`blocks` 三件齐全的文档；损坏或缺失返回 None。

### 3.4 Worker（`backend/app/worker/main.py`）

1. 构造参数新增 `chart_snapshotter: ChartSnapshotter | None = None`，保存为 `self._snapshotter`。
2. 新增 `_capture_chart_snapshot(job, report) -> str`：

   - `report is None` 或 `self._snapshotter is None` 或 `self._heartbeat.lost` → 返回 `"none"`；
   - `content_hash = compute_content_hash(report["sections"])`（`backend/app/services/report_document.py:39`）；
   - 调 `capture(...)`；异常 → `logger.exception` 后返回 `"none"`；
   - `self._reports.write_chart_snapshot(job_id, payload)`；`OSError` → 返回 `"none"`；
   - 返回 `payload["status"]`。

3. 三条成功路径（`main.py:294-325`）统一改成：

   ```text
   status = self._capture_chart_snapshot(job, result.report)
   self._publish_report(job.id, result.report)
   self._jobs.finish_success(..., chart_snapshot_status=status)
   ```

   顺序不能反：先快照后终态，和 `report.json` 的 B4 语义一致。

### 3.5 终态事务（`backend/app/services/job_service.py`）

`finish_success`（第 935 行）新增关键字参数 `chart_snapshot_status: str | None = None`：

- 为 None 时保持现状（信任报告 meta），所有现有直接调用方不受影响；
- 非 None 时必须属于 `CHART_SNAPSHOT_STATUSES`，否则按 `"none"` 处理；
- 传值生效时，在调用 `finalize_report` 前对报告做浅拷贝并覆盖 `meta["chart_snapshot_status"]`，不修改调用方对象；
- 数据库列、CHECK 约束、`report_ready` 载荷都不改，`finalize_report` 本身也不改。

### 3.6 接线（`scripts/run_backend.py`）

- 在 `create_app` 之前创建一份 `DefaultMarketProviders()` 与 `MarketCache()`，同时传给 `create_app(..., market_providers=..., market_cache=...)`（签名已支持，`backend/app/main.py:43-44`）和 `StockService`，让 API 与快照共用缓存；
- 构造 `MarketChartSnapshotter(StockService(providers, cache))`，传给 `Worker`；
- `TA_CHART_SNAPSHOT=0` 时不传，worker 打印 `chart snapshot off`；默认开启；
- 不打印路径以外的新配置，不读密钥。

### 3.7 前端（`frontend/src/features/reports/`）

- `format.ts` 增加 `CHART_SNAPSHOT_LABELS: Record<ReportChartSnapshot, string>`，值按 D9；
- `ReportMeta.tsx` 在「数据质量」下方增加一行 `图表快照`，`data-testid="meta-chart-snapshot"`；
- 不改报告列表、不改导出菜单、不改 `api/types.ts`（类型已存在）。

### 3.8 不改的东西

- 不改 `finalize_report` 的默认值逻辑（旧导入仍走 none）；
- 不改 `build_legacy_report`；
- 不给 `/reports/{id}` 增加 `chart_snapshot` 字段；
- 不把快照塞进 `report.json`；
- 不生成图表、不改 PDF 渲染；消费方是未来的导出图表票；
- 不碰旧版 `tradingagents/`、`web/`。

## 四、测试清单

### 4.1 后端

| # | 用例 | 断言 |
| --- | --- | --- |
| RPT-T1 | 假 provider 两块都 ok，Worker 跑完一个任务 | 状态 `frozen`；`<job>/chart_snapshot.json` 存在；`report_content_hash` 等于 `Report.content_hash` |
| RPT-T2 | 假 provider 行情 ok、K 线 `error` | 状态 `none`；文件仍写入且 `status=none`、`reason=kline_error`；任务 `succeeded`、报告存在 |
| RPT-T3 | 快照器抛异常 | 状态 `none`；任务仍 `succeeded`；日志有异常栈；没有文件 |
| RPT-T4 | `write_chart_snapshot` 抛 `OSError` | 状态 `none`；任务仍 `succeeded`；数据库不是 frozen |
| RPT-T5 | 快照器为 None（默认） | 状态 `none`；不写文件；现有假图测试全绿 |
| RPT-T6 | 行情或 K 线 `stale` 且有数据 | 状态 `frozen`；`as_of` 原样保留 |
| RPT-T7 | 行情 `empty` | 状态 `none`、`reason=quote_empty` |
| RPT-T8 | pause_noop 与 cancel_noop 两条路径 | 与正常完成同状态；文件只写一次 |
| RPT-T9 | 心跳丢失 | 不抓取、不写文件、状态 none |
| RPT-T10 | `run_backend` 接线函数 | 默认拿到 snapshotter；`TA_CHART_SNAPSHOT=0` 时为 None |
| RPT-T11 | `read_chart_snapshot` 读取损坏 JSON / 错 schema_version | 返回 None，不抛异常 |
| RPT-T12 | 旧导入与兼容投影 | 状态仍 `none`，文件不存在 |

需要顺带更新的现有断言：

- `tests/backend/test_stage_persistence.py:318` 现在断言运行结果等于 golden 的 `frozen`；默认无快照器后应改为 `none`。这是运行时行为修正，不改 golden 文件、不改契约。
- `tests/backend/test_terminal_retry.py:423` 的 `bogus → none` 保持。
- `tests/backend/test_exports.py:401`、`test_legacy_import.py:175`、`test_legacy_projection.py:158/371/398`、`test_pdf_renderer.py:126/133` 全部是旧报告路径，保持 `none`，不应改动。

### 4.2 前端

| # | 用例 | 断言 |
| --- | --- | --- |
| RPT-F1 | 报告元信息渲染 `frozen` | 显示「分析时冻结」，testid 可查 |
| RPT-F2 | 渲染 `refetch_needed` / `none` | 分别显示「需补数」「无」 |
| RPT-F3 | 旧报告（none） | 行仍显示，不隐藏、不编造 |

### 4.3 一致性

`tests/test_upgrade_contract_consistency.py` 的 CT-01 至 CT-08 必须全绿；本票不改任何冻结文件，哈希清单不变。

## 五、退出验收

```text
.venv/Scripts/python.exe -m pytest tests/backend/test_stage_persistence.py tests/backend/test_terminal_retry.py tests/backend/test_exports.py tests/backend/test_reports_api.py -q
.venv/Scripts/python.exe -m pytest -q
cd frontend && npm test -- --run src/features/reports
.venv/Scripts/python.exe scripts/p0_preflight.py --full --smoke
```

硬断言：

- 一次假 provider 的完整任务后，`SELECT chart_snapshot_status FROM reports WHERE job_id=...` 必须是 `frozen`，且 `job_reports/<job>/chart_snapshot.json` 的 `report_content_hash` 与该行 `content_hash` 完全一致。
- 把 K 线 provider 改成抛错再跑一次，状态必须是 `none`，任务仍 `succeeded`，报告 `content_hash` 不变。
- 关掉快照（`TA_CHART_SNAPSHOT=0` 或默认 None）跑同一任务，状态 `none`、无文件、任务成功。
- 全量测试与预检全绿；前端报告相关用例全绿；入口 bundle 不因本票增加（新增文案与一行 DOM 可忽略，但仍要过 P3 预算）。
- 真实模型验证不阻塞本票：S6 仍受 402 余额限制。余额恢复后跑一次真实任务，确认 `frozen` 行与文件同时存在，把证据补进评审；在此之前用假 provider 的集成测试作为出口证据，并明确写「未用真实模型验证」。

收尾写 `docs/upgrade/reviews/2026-11-XX_RPT-01评审.md`：改了什么、状态判定表、两条失败路径实测、旧报告未受影响、真实模型验证状态。

## 六、回滚

- 单票一个本地提交；`git revert` 即可回到「所有新报告 none」。
- 运行期开关：`TA_CHART_SNAPSHOT=0` 立即停止抓取；已写出的 sidecar 和已标记的 frozen 行保持真实，不需要清理。
- 无数据库迁移、无契约变更、无依赖变更。
- 回滚后已有 frozen 报告仍可正常阅读和导出；导出逻辑不读 sidecar，因此没有兼容风险。

## 七、风险与坑

1. **抓取会拖慢终态提交**：冷缓存下两块最多各 10 秒。可以先命中缓存，但不要为了速度跳过 `as_of`；如果实测终态延迟明显，下一步是在独立线程抓取并在提交前 join 一个上限，而不是把状态提前写成 frozen。
2. **不要在事务里写文件**：`finish_success` 是单事务，文件写入必须在此之前完成（与 `report.json` 同序），否则会出现「事务失败但文件已落」的孤儿。
3. **content_hash 必须用最终 sections 计算**：`finalize_report` 不会改 sections，但仍要用同一函数 `compute_content_hash`，并在测试里比对数据库值。
4. **`stale` 不是失败**：非交易日或缓存超时得到 stale 是正常的，仍然 frozen；不要把 stale 一律判 none。
5. **默认 None 会让现有假图报告的 frozen 变成 none**：这是修正，不是回归；只更新 `test_stage_persistence` 一处，不动 golden。
6. **pause_noop / cancel_noop**：三条路径都要接线，漏一条会出现「同样成功、状态不同」。
7. **文件路径安全**：只用 `ReportStore._component` 拼 job_id，不接受外部路径；读取端只认固定文件名。
8. **e2e 离线确定性**：`e2e_p6.py` 使用假图、真实 providers；如果本机离线，抓取会走到超时。e2e 启动时设 `TA_CHART_SNAPSHOT=0`，真实常驻栈保持开启。
9. **不要把 `refetch_needed` 提前用掉**：它属于旧报告补数导出，本票不产生该状态。

## 八、交接

- 新增文件：`backend/app/services/chart_snapshot.py`、`tests/backend/test_chart_snapshot.py`。
- 修改文件：`stock_service.py`、`report_store.py`、`worker/main.py`、`job_service.py`、`run_backend.py`、`frontend/src/features/reports/format.ts`、`ReportMeta.tsx`、`test_stage_persistence.py`、`e2e/e2e_p6.py`。
- 需要更新的证据：`docs/upgrade/reviews/2026-11-XX_RPT-01评审.md`，以及评审里贴出的两条 SQL/文件比对输出。
- 与其他票的关系：不依赖 R1；真实模型复核依赖 S6 余额恢复，但不阻塞本票出口。
- 收工必须报告：提交哈希、测试总数、预检结果、一条 frozen 样例的 `report_id/job_id/content_hash`、以及「未推送」。
