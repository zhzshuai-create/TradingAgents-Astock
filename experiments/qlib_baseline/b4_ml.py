# -*- coding: utf-8 -*-
"""T3 阶段3b: B4 机器学习基线 LGBM+Alpha158（qlib venv 跑, 必须落文件执行）.

协议: 全池 300 只训练 Alpha158+LGBM, 在测试段(2026)对信号日逐股出方向
(预测分数符号, 标签=次日收益 Ref($close,-2)/Ref($close,-1)-1)。
方向文件 results/b4_ml_{signal_date}.json 供 compare.py 自动并入。

Windows 防死锁: C.kernels=1 全串行 + joblib_backend=None(loky)——
D.features/数据集构建的 ParallelExt 在 multiprocessing 后端下会 spawn 死锁
（2026-10-24 实测 Errno22/挂死）。

用法: ../../.venv-qlib/Scripts/python.exe b4_ml.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

# 新版 mlflow 禁用 ./mlruns 文件后端(qlib LGBM 记账会炸), 显式放行
os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

BASE = Path(__file__).resolve().parent
PROJ = BASE.parents[1]
SIGNAL_DATES = ("2026-08-13", "2026-09-11", "2026-10-06")

import qlib  # noqa: E402
from qlib.config import C  # noqa: E402

qlib.init(provider_uri=str(BASE / "qlib_data"), region="cn",
          joblib_backend=None)
C["kernels"] = 1  # 全串行: n_jobs=1 时 joblib 内联执行, 不 spawn 子进程

from qlib.contrib.data.handler import Alpha158  # noqa: E402
from qlib.contrib.model.gbdt import LGBModel  # noqa: E402
from qlib.data.dataset import DatasetH  # noqa: E402

SEGMENTS = {
    "train": ("2022-08-01", "2025-06-30"),
    "valid": ("2025-07-01", "2025-12-31"),
    "test": ("2026-01-01", "2026-10-23"),
}


def eval_tickers_by_date() -> dict[str, list[str]]:
    """信号日 → 评估标的列表（与 baselines_rule 同源: run_*.json 成功运行）。"""
    out: dict[str, list[str]] = {}
    for f in sorted((PROJ / "experiments" / "results").glob("run_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        sd = d.get("trade_date")
        if sd in SIGNAL_DATES and d.get("error") is None and d.get("signal"):
            out.setdefault(sd, [])
            if d["ticker"] not in out[sd]:
                out[sd].append(d["ticker"])
    return out


def main() -> None:
    handler = Alpha158(
        instruments="all",
        start_time=SEGMENTS["train"][0], end_time=SEGMENTS["test"][1],
        # processor 拟合(如归一化)只用训练段, 防未来函数
        fit_start_time=SEGMENTS["train"][0], fit_end_time=SEGMENTS["train"][1],
    )
    dataset = DatasetH(handler, SEGMENTS)
    print("dataset ready:", {k: len(dataset.prepare(k, col_set="feature"))
                             for k in SEGMENTS}, flush=True)

    model = LGBModel(
        loss="mse", num_leaves=64, learning_rate=0.05, max_depth=6,
        num_boost_round=300, early_stopping_rounds=50,
    )
    model.fit(dataset)
    pred = model.predict(dataset, segment="test")
    # pred: MultiIndex (instrument, datetime) Series
    print("pred rows:", len(pred), flush=True)

    by_date = {sd: [] for sd in SIGNAL_DATES}
    pred_frame = pred.reset_index()
    pred_frame.columns = [str(c) for c in pred_frame.columns]
    # index 层序不定: 按内容识别——含 SH/SZ 前缀的是 instrument, 其余是 datetime
    inst_col = next(c for c in pred_frame.columns[:2]
                    if pred_frame[c].astype(str).str.match(r"^(SH|SZ)\d{6}$").any())
    dt_col = next(c for c in pred_frame.columns[:2] if c != inst_col)
    pred_frame = pred_frame.rename(columns={inst_col: "inst", dt_col: "dt"})
    pred_frame["dt"] = pd.to_datetime(pred_frame["dt"]).dt.strftime("%Y-%m-%d")
    pred_frame = pred_frame.rename(columns={pred_frame.columns[-1]: "score"})

    for sd, tickers in eval_tickers_by_date().items():
        for t in tickers:
            sym = ("SH" if t.startswith("6") else "SZ") + t
            sub = pred_frame[pred_frame["inst"] == sym].sort_values("dt")
            hit = sub[sub["dt"] <= sd]
            if hit.empty:
                by_date[sd].append({"ticker": t, "b4_ml": None,
                                    "_note": "pred 缺该日"})
                continue
            row = hit.iloc[-1]
            score = float(row["score"])
            by_date[sd].append({
                "ticker": t,
                "b4_ml": "bullish" if score > 0 else "bearish",
                "_score": round(score, 6),
                "_pred_date": row["dt"],
            })

    out_dir = BASE / "results"
    out_dir.mkdir(exist_ok=True)
    for sd, rows in by_date.items():
        if not rows:
            continue
        f = out_dir / f"b4_ml_{sd}.json"
        f.write_text(json.dumps({
            "signal_date": sd,
            "model": "LGBM+Alpha158(qlib 0.9.7, 全池300训练, 串行)",
            "segments": {k: list(v) for k, v in SEGMENTS.items()},
            "rows": rows,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{sd}: " + ", ".join(
            f"{r['ticker']}={r['b4_ml']}" for r in rows), flush=True)
        print(f"  -> {f}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
