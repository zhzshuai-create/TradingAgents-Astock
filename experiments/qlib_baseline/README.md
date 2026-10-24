# T3：qlib 量化基线对照实验

多智能体信号 vs 量化基线（买入持有 / 均线规则 / 动量规则 / LGBM+Alpha158），
统一协议：同标的池 × 同信号日 × 同持有窗口（信号日收盘 → 评估日收盘），
方向判定与 T2 同一口径（`experiments/backtest_eval.py::signal_direction`）。

## 环境边界（重要）

qlib 运行在**独立 venv**（`.venv-qlib/`，Python 3.12.10），与主项目环境
（Python 3.13，mootdx/streamlit/langchain 等）物理隔离，互不可见：

| 环境 | 解释器 | 用途 | 关键钉版 |
|------|--------|------|----------|
| 主环境 | `Python313\python.exe` | TradingAgents 全部功能、数据导出、对照汇总 | mootdx 0.11.7 / httpx 0.28.1 / streamlit 1.57.0 / pandas 3.0.3 |
| qlib venv | `.venv-qlib\Scripts\python.exe` | dump_bin 转换、基线回测 | pyqlib 0.9.7 / pandas **2.2.3** / numpy 2.5.4 / lightgbm 4.7.0 |

规则：
- **任何 pip install 只进 `.venv-qlib`**（用 `.venv-qlib\Scripts\python.exe -m pip`），
  绝不向主环境 3.13/3.14 装包
- pandas 钉 2.2.3：pyqlib 的约束只有 `pandas>=0.24` 无上界，pip 会装 3.x，
  但 qlib 0.9.7 是 pandas 1.x/2.x 时代代码，3.x 运行期必炸——**重建环境时必须带此钉版**
- 完整钉版见 `requirements-qlib.lock.txt`（pip freeze 全量）；
  主环境装 qlib 前的快照在 `main-env-3.13.snapshot.txt`（未跟踪，仅供本机核对）

## 复建（从零）

```bat
winget install -e --id Python.Python.3.12
cd C:\Users\zhzsh\TradingAgents-astock
py -3.12 -m venv .venv-qlib
.venv-qlib\Scripts\python.exe -m pip install pyqlib==0.9.7 lightgbm pandas==2.2.3
.venv-qlib\Scripts\python.exe -m pip install -r experiments\qlib_baseline\requirements-qlib.lock.txt
```

## 回退（随时）

- **qlib 环境整体回退**：删除 `.venv-qlib\` 目录即可，主环境零影响
  （已验证：装完全套后主环境 `pip freeze` 与快照逐行 diff 为空）
- **Python 3.12 卸载**：`winget uninstall -e --id Python.Python.3.12`
- **代码回退锚点**：git tag `pre-qlib-baseline`（= 74e73ac），本目录所有代码
  改动在该 tag 之后，`git diff pre-qlib-baseline -- experiments/qlib_baseline` 可审

## 阶段进度

- [x] 阶段 1：环境隔离与钉版（本文件）
- [x] 阶段 2a：评估池管线打通——export_csv.py（EM fqt=2 / 腾讯 fqkline hfq 双引擎,
  全池同源规则）→ dump_bin（`--data_path` 非 csv_path）→ verify_dump.py 读回
  400 项数值比对 0 不符
- [ ] 阶段 2b：宽池（评估 10 + 训练 300）全量导出与 dump（等 EM/腾讯限流解除;
  `python experiments/qlib_baseline/export_csv.py --pool all --source auto`）
- [x] 阶段 3a：规则基线 B1/B2/B3（baselines_rule.py, 两个窗口已出结果）
- [ ] 阶段 3b：B4 LGBM+Alpha158（依赖阶段 2b 宽池）
- [ ] 阶段 4：对照汇总（compare.py，与 run_*.json 同表）
- [ ] 阶段 5：论文 T3 接入

### 阶段 3a 初步结果（hfq 同源, T2 同口径方向判定）

窗口1 2026-08-13→09-11（6 标的）: TA 2/2 方向全中(另 4 只 Hold 中性) /
B1 B&H 4/6=67% / B2 均线 3/6=50% / B3 动量 5/6=83%（该窗口普涨反弹利多动量）
窗口2 2026-10-06→10-23（601208）: 区间 **-18.40%**, TA Underweight 为**唯一**
命中策略, 三条规则基线全部多头落空——多智能体捕获熊市案例的硬数据点。
样本极小(n=7 方向样本), 论文表述必须带样本量, 禁止写成百分比排名结论。

### 阶段 2 数据口径决策（2026-10-24，实测驱动）

- **后复权(hfq) 而非前复权**：EM fqt=1 前复权全历史 OHLC 实测损坏（600519
  2016 段 close=25.6 vs 真实≈309, 比值漂移 12x→1x）——弃用。后复权锚定 IPO、
  只乘不减, 收益忠实（验证: 腾讯 hfq 2015-08-24 千股跌停日 -7.99% 与真实一致）
- **腾讯 hfq 为等比复权**（若等差, 高分红股收益会被稀释数倍, 实测无此现象）
- **vwap 不导出**：EM amount 是原始口径与复权价不一致; 基础 Alpha158 只用
  OHLCV（仅 Alpha158vwap 子类才要 $vwap）
- **引擎统一**：--source auto 时 EM 任一失败即整池切腾讯, manifest 记录最终引擎
- dump_bin 参数：`dump_all --data_path csv_data --qlib_dir qlib_data
  --include_fields open,close,high,low,volume`（0.9.7 用 data_path 不是 csv_path）

### 已知坑（Windows / 本机）

- **qlib 脚本必须落成文件再跑**：stdin/heredoc 脚本会触发 Windows multiprocessing
  spawn 挂死（__main__ 无文件可再导入）
- `D.features(instruments)` 必须传**列表**; 逗号串会被当成单个 instrument 名
- EM push2his 间歇拒连是常态（历史多案）; 腾讯 fqkline 高频抓取会触发 501
  挑战页, 两家限流通常数小时内解除
