# -*- coding: utf-8 -*-
"""T3 阶段2: dump_bin 产物读回校验（qlib venv 跑, 纯离线）.

qlib.init 读回 dump 产物, 与源 CSV 逐值对数（相对误差 <1e-4）。
覆盖: 全部标的 × 源 CSV 末 N 日 + 首 3 日（头部/尾部都验）+ 行数一致性。

用法:
    ../../.venv-qlib/Scripts/python.exe verify_dump.py [--csv csv_data] [--qlib qlib_data]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import qlib
from qlib.data import D

BASE = Path(__file__).resolve().parent
FIELDS = ["$open", "$close", "$high", "$low", "$volume"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(BASE / "csv_data"))
    ap.add_argument("--qlib", default=str(BASE / "qlib_data"))
    ap.add_argument("--tail", type=int, default=5, help="校验末 N 个交易日")
    args = ap.parse_args()

    qlib.init(provider_uri=args.qlib, region="cn")

    csv_dir = Path(args.csv)
    syms = sorted(p.stem.upper() for p in csv_dir.glob("*.csv"))
    # instruments 必须传列表; 逗号串会被当成单个 instrument 名返回空表
    first = min(pd.read_csv(csv_dir / f"{s.lower()}.csv")["date"].iloc[0] for s in syms)
    last = max(pd.read_csv(csv_dir / f"{s.lower()}.csv")["date"].iloc[-1] for s in syms)
    df = D.features(syms, FIELDS, start_time=first, end_time=last,
                    freq="day").dropna(how="all")
    df.columns = [c.lstrip("$") for c in df.columns]
    df.index = df.index.rename([None, None])

    n_checked = n_mismatch = 0
    problems: list[str] = []
    for sym in syms:
        src = pd.read_csv(csv_dir / f"{sym.lower()}.csv").set_index("date")
        got = df.loc[sym]
        got.index = pd.to_datetime(got.index).strftime("%Y-%m-%d")
        # 行数: qlib 读回按全局日历对齐到该股 [首,末] 区间, 停牌日为 NaN —— 
        # 行数应 >= 源行数(含停牌 NaN), 有效值行数应 == 源行数
        got_valid = got.dropna(how="all")
        if len(got_valid) != len(src):
            problems.append(f"{sym}: 行数不一致 qlib={len(got_valid)} src={len(src)}")
        for probe in list(src.index[-args.tail:]) + list(src.index[:3]):
            if probe not in got_valid.index:
                problems.append(f"{sym}: {probe} 缺行")
                continue
            for col in ("open", "close", "high", "low", "volume"):
                a, b = float(src.loc[probe, col]), float(got_valid.loc[probe, col])
                n_checked += 1
                if not np.isclose(a, b, rtol=1e-4, atol=1e-6):
                    n_mismatch += 1
                    problems.append(f"{sym} {probe} {col}: src={a} qlib={b}")

    print(f"校验 {len(syms)} 标的 × 头尾探测点, 数值比对 {n_checked} 项, 不符 {n_mismatch} 项")
    if problems:
        print("PROBLEMS:")
        for p in problems[:20]:
            print(" ", p)
        raise SystemExit(1)
    print("READ-BACK VERIFY PASS")


if __name__ == "__main__":
    main()
