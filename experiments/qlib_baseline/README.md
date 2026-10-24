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
- [ ] 阶段 2：数据导出（东财前复权日K → qlib dump CSV）与 dump_bin 转换校验
- [ ] 阶段 3：四条基线（B1 B&H / B2 均线 / B3 动量 / B4 LGBM+Alpha158）
- [ ] 阶段 4：对照汇总（compare.py，与 run_*.json 同表）
- [ ] 阶段 5：论文 T3 接入

注意：pyqlib wheel 不含 `scripts/dump_bin.py`，阶段 2 需从 microsoft/qlib 仓库
**v0.9.7 tag** 取该脚本入本目录（钉版本防上游漂移）。
