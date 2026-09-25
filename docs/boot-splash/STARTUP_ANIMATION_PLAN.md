# AStock Pro 启动动画 · 评估与实施方案

日期: 2026-09-25 · 目标仓库: `C:\Users\zhzsh\TradingAgents-astock` · 状态: 待批准,未改动任何项目文件

---

## 1. 需求界定

用户从桌面图标双击 `run_all.bat` → 浏览器打开 → **进入主界面之前的这段过渡,要有设计感的动画**,替代现在那段"Streamlit 自带 spinner + 白屏 reflow"。

覆盖范围:

| 阶段 | 时长 | 能否放动画 | 说明 |
|---|---|---|---|
| 控制台窗口(`launch.py` 启动 streamlit) | ~5s | 否 | 此时浏览器还没打开,没有画面载体。Streamlit 是就绪后才 open browser |
| 浏览器打开 → 首帧渲染完成 | **1.5–5.5s** | **是,全部可接管** | 本方案的唯一战场 |
| 运行时分析进度 | 分钟级 | 已存在 | `web/progress.py` 的 12 阶段面板,不在本次范围 |

## 2. 实测依据(全部为本机可复现数据)

### 2.1 关键前提已验证:遮罩能盖住真实等待

探针 `splash_probe.py`(注入遮罩 → `time.sleep(4)` → 渲染主内容),浏览器侧 40ms 采样:

| 时刻 | 页面状态 |
|---|---|
| 0–361ms | 静态壳 |
| 401ms | Streamlit spinner 出现 |
| **456ms** | **遮罩已上屏** |
| 456–4563ms | 遮罩持续覆盖,共 **4.11s** |
| 4610ms | 主内容出现,spinner 消失 |

结论: Streamlit 边执行脚本边通过 websocket 增量下发元素。在阻塞代码之前 `yield` 的元素会立刻显示。所谓"结构性死结"不成立。

### 2.2 等待的钱花在哪(这是评估的重点)

逐个模块首次 import 计时(同一进程内顺序累加):

| 模块 | 耗时 | 备注 |
|---|---|---|
| `web.components.sidebar` | **3.20s** | 元凶 1 |
| `web.components.report_viewer` | **2.04s** | 元凶 2 |
| `streamlit` | 0.30s | 不可移 |
| `tradingagents.default_config` | 0.00s | 意外地便宜 |
| `web.data_functions` | 0.01s | 已被上面传递导入 |
| `web.history` / `progress` / `runner` | 0.00s | 同上 |
| **合计** | **5.57s** | |

`-X importtime` 精确归因(sidebar 一条链,2025 个模块):

- `langgraph.types` 累计 279ms、`langsmith.run_trees` 155ms、`langgraph.prebuilt.chat_agent_executor` 90ms、`pyarrow.compute` 27ms、`bs4`/`rich`/`charset_normalizer` 各 25–30ms
- 根因链: `sidebar.py:10-11` → `tradingagents.graph.checkpointer` + `llm_clients.model_catalog` → 拉起整个 langgraph/langchain/langsmith 图
- `report_viewer.py:12` → `web.pdf_export` → 报告导出依赖,首屏根本用不到

数字差异说明: 同一进程内首次 3.20s vs `-X importtime` 全新进程 1.30s,差异来自 `.pyc` 与磁盘暖缓存。**按 1.3–3.2s 区间估计,别按 0.3s 写时间线。**

### 2.3 附带发现: 这个等待本身是可以削掉的

把 `report_viewer`、`progress_panel` 的导入下沉到实际使用处(第 440 行之后),用户冷启动就少等 ~2s。也就是说动画不只是遮丑,还能顺手做真优化 —— 但这是独立收益,应独立提交。

## 3. 方案选型

| 方案 | 做法 | 评价 | 工时 |
|---|---|---|---|
| **A 遮罩 + 导入下沉**(推荐) | 在 `set_page_config` 之后注入 CSS 遮罩,再把重导入移到遮罩之后 | 盖住真实等待,同时缩短等待;纯标准 Streamlit API;可分步验证 | 3–4h |
| B 只做遮罩,不动导入 | 遮罩放最前,但导入挪不动 | 不可行: `app.py:23-33` 在 `set_page_config` 之前,不重排就没有遮罩的插入点 | — |
| C launcher 静态引导页 | `launch.py` 自己起 8500 端口 serve 一个 HTML,探活 8501 后 `location.replace` | 能盖到更早,但控制台那几秒仍无画面,且要自己管端口/进程生命周期,丢 Streamlit session | 6–8h |
| D 只改视觉不改时序 | 固定时长动画放主界面顶部 | 最差: 时长与真实等待无关,机器一慢就穿帮 | — |

推荐 **A**。C 只在"未来想让浏览器窗口本身也参与品牌体验"时才值得,现在收益不抵复杂度。

## 4. 交互与视觉规格

### 4.1 门控语义(与最初讨论不同,需要确认)

最初我给的是"每次加载都播"。看完代码后要改成:

**每个标签页播一次,用 `sessionStorage['astock-boot']` 判定。**

原因: `app.py` 里 `st.rerun()` 出现在 228/468/480/558/599 六处,`components.html` 的断线重连 JS 还会 `location.reload()`(最多 20 次)。"每次加载都播"在这些路径上会变成同一屏动画重播 3–5 次,是负面效果。`sessionStorage` 天然实现"新开标签页播、本标签页内永不重播",而 `st.session_state` 挡不住 reload。

仓库里已有同构先例: `app.py:57-65` 用 `window.parent.document` + `localStorage` 存主题,直接复用那层写法。

### 4.2 动画本体

- 主体: 7 个分析师节点(`PIPELINE_STAGES` 的 market / social / news / fundamentals / policy / hot_money / lockup)沿弧线排列,依次点亮 → 光点汇聚到中心"最终决策"节点 → 整层淡出
- 复用 `PIPELINE_STAGES` 的 icon 与中文名,不新造常量
- 时长: 最短 1.4s,最长 4.5s。**淡出双条件**: 主内容元素已出现 且 已过 1.4s;超 4.5s 未就绪则从"逐节点点亮"切到不确定态呼吸循环(不假报进度)
- 节奏: 全 CSS `@keyframes`,Python 侧零 `time.sleep`、零逐帧 rerun
- 主题: 跟随 `documentElement.className`,亮色底 `#ffffff`,主色 `#e85d04`
- 跳过: 点击任意处立即淡出;URL 带 `?noboot=1` 完全禁用(开发期用)
- 无障碍: `prefers-reduced-motion: reduce` 时只留 0.4s 纯色淡入淡出,不做节点动画
- `aria-hidden="true"`,遮罩不参与读屏

## 5. 实施分解(每步一个提交,可单独回滚)

| # | 提交 | 内容 | 验收 |
|---|---|---|---|
| 1 | `refactor(web): 导入下沉到首次使用点` | `app.py:23-33` 按使用行拆分: `render_sidebar`@184 前 / `index_spot`@231 前 / `components`@57 前 / 其余@440 后;`load_dotenv` 保持在 `default_config` 之前 | 应用行为零变化;测冷启动耗时对比表 |
| 2 | `feat(web): 启动遮罩骨架` | 新增 `web/components/boot_splash.py`:`render_boot_mask()`(纯 HTML+CSS)、`finish_boot()`(注入淡出 JS)。在 `set_page_config` 后调用一次 | 探针脚本量出遮罩上屏 <600ms 且覆盖到主内容出现 |
| 3 | `feat(web): 分析师节点点亮序列` | 7 节点 + 汇聚 + 双条件淡出 + 4.5s 兜底 + 点击跳过 | 截图 3 帧(0.3s / 0.9s / 淡出后)肉眼确认 |
| 4 | `feat(web): 门控与主题联动` | `sessionStorage` 标记、`?noboot=1`、`prefers-reduced-motion`、亮/暗适配 | 连点 5 次模式切换 + 手动 reload,动画不重播 |
| 5 | `chore(web): 可选懒加载 report_viewer` | 把 2.04s 推到真要看报告时 | 冷启动总时长下降有数字 |

第 5 步可独立否决,不影响前 4 步。

## 6. 风险清单

| 风险 | 等级 | 说明 | 对策 |
|---|---|---|---|
| 重排 import 遗漏使用点 | **高** | `app.py` 683 行平铺无函数封装,名字在模块级共享 | 已逐个 grep 定位:`DEFAULT_CONFIG`@412、`render_progress`@466、`render_report`@460/472、`render_sidebar`@184、`extract_signal`/`load_analysis`@456/457/502、`get_history`@526、`ProgressTracker`@440/450、`run_analysis_in_thread`@445、`index_spot`@231、`components`@57/68/269/375/668。第 1 步只按此表挪,提交前 `python -c "import web.app"` 冒烟 + 跑一遍三种模式 |
| `set_page_config` 不再是首条 Streamlit 命令 | 中 | Streamlit 强制它先于任何元素 | 顺序锁死: page_config → `components.html` 主题 JS(已存在) → 遮罩 |
| rerun 重播 | 中 | 见 4.1 | `sessionStorage`,不用 `session_state` |
| 增量下发未覆盖首帧之外的等待 | 低 | 若 `index_spot()` 网络卡 5s,动画会先淡出 | 双条件淡出 + 4.5s 兜底切呼吸态,不显示假百分比 |
| journal iframe 白屏 | 低 | `launch.py:40` 是 `time.sleep(2)` 硬等 8502 | 本次不动它。已有"手动启动引导"文案兜底,共用同一探活结果作为后续独立改动 |
| 视觉与现有主题打架 | 低 | `theme.py` 33KB 已有完整设计系统 | 遮罩只读 CSS 变量,不新增色值 |

## 7. 明确不做

- 不改 `launch.py` 的 `time.sleep(2)`(独立议题)
- 不做运行时进度面板改版
- 不覆盖控制台阶段的等待(无载体)
- 不引入视频/GIF 资源(体积 + 主题不适配)
- 不碰 `data/` 与任何隐私路径

## 8. 验收清单(交付时逐条打勾)

- [ ] 冷启动: 遮罩上屏 <600ms,无 Streamlit 原生 spinner 露出
- [ ] 冷启动: 主内容出现到淡出之间无白屏闪烁
- [ ] 热重载(F5): 不重播
- [ ] 模式切换 5 次: 不重播
- [ ] 断网 3s 再恢复(触发重连 reload): 不重播
- [ ] 暗色模式下节点对比度可读
- [ ] `?noboot=1` 完全跳过
- [ ] `prefers-reduced-motion` 下只 0.4s 淡入淡出
- [ ] 交易分析全流程跑通(证明导入重排无回归)
- [ ] 第 1 步前后冷启动耗时数字都留在 commit message

## 9. 完整工程流程(阶段制,每阶段一个门禁)

阶段 1 是关键: 先把测量工具建起来,否则后面每步的"成功"都是主观判断。

| 阶段 | 动作 | 门禁(过了才进下一阶段) | 产物 | 预算 |
|---|---|---|---|---|
| 0 基线冻结 | `git status` 干净 → 建分支 `feat/boot-splash` → 记 HEAD 为回滚锚点 → 冷启动耗时跑 3 次取中位数 → 三种模式各一张截图 → `python -c "import web.app"` 冒烟 | 基线数字与截图存档 | `baseline.md` | 0.5h |
| 1 测量工具化 | 把 `splash_probe.py` 改造成 `tools/measure_boot.py`: 起 streamlit → 浏览器侧 40ms 采样 → 输出 JSON(遮罩上屏 ms / 主内容 ms / spinner 露出 ms / 总时长) | 工具能对一个故意慢的假 app 稳定复现探针那组数字 | 测量脚本 | 0.5h |
| 2 导入下沉 · 远端 | 只挪 `report_viewer` / `progress_panel` / `history` / `progress` / `runner`(用点在第 440 行之后) | 冒烟 + 三模式截图无差异 + 跑一次完整分析 + measure_boot 数字下降 | commit(带数字) | 0.5h |
| 3 导入下沉 · 近端 | `render_sidebar`@184 前、`index_spot`@231 前、`components`@57 前;`load_dotenv` 必须仍在 `default_config` 之前 | 阶段 2 全部门禁 + **单独打开 8502 journal iframe 页验证一次** | commit(带数字) | 0.75h |
| 4 遮罩骨架 | 新建 `web/components/boot_splash.py`,只实现 `render_boot_mask()` / `finish_boot()`;纯色遮罩 + 一条不确定进度线,**不做任何美术** | measure_boot 证明: 遮罩 <600ms 上屏、覆盖到主内容、spinner 全程未露出 | commit | 0.5h |
| 5 动画本体 | 7 分析师节点点亮 → 汇聚决策 → 双条件淡出 → 4.5s 兜底呼吸态 → 点击跳过 → `prefers-reduced-motion` | 0.3s / 0.9s / 淡出后三帧截图肉眼确认 + 暗色对比度可读 | commit | 1h |
| 6 门控与韧性 | `sessionStorage['astock-boot']` 标记,写回方式复用 `app.py:57-65` 的 `window.parent` 范式 | 连点 5 次模式切换、F5、断网 3s 触发重连 reload、新开标签页 —— 四条都不重播 | commit | 0.5h |
| 7 懒加载(可否决) | `report_viewer` 推到真正要显示报告时;或把 `sidebar` 里的 `checkpointer` / `MODEL_OPTIONS` 下沉到调用处 | 冷启动数字再降,且报告页/侧栏功能无回归 | commit | 0.75h |
| 8 收尾 | 删探针、更新 `CHANGELOG.md` / `DEV_LOG.md`、`assets/` 补截图、README 一句说明 | 你确认后再决定是否 push(本机 github.com:443 被拦,只能走 SSH) | commit | 0.25h |

**总计 4–5 小时**(此前 3–4h 的估算未含阶段 1 的测量工具,已修正)。

### 每阶段通用的验证循环

1. `python -c "import web.app"` —— 抓 import 期错误,1 秒
2. `tools/measure_boot.py` —— 抓时序,自动出数字
3. 三模式手动走一遍(分析 / 看板 / 交易日志)—— 抓静默回归,**这一步不能省**
4. `git diff` 自查 + commit,commit message 里写死前后数字

### 回滚策略

每个阶段一个独立 commit,出问题只回滚那一块。阶段 2、3 是高风险改动,若阶段 3 失败可保留阶段 2 的收益直接放弃动画,走方案 C。阶段 4 之后全部是新文件 + 一处调用点,删掉调用点即完全复原。

### 决策点(仍未回答)

1. 门控: "每标签页一次"(推荐) vs "每次加载都播"
2. 阶段 3 的近端导入重排是否批准 —— 不批准则只能走方案 C(6–8h)
3. 阶段 7 懒加载做不做
