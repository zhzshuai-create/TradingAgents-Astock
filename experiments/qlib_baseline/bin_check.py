# -*- coding: utf-8 -*-
"""T3 阶段2b: dump .bin 直接解码比对（主环境跑, 纯 python 零 qlib/joblib）.

背景: qlib D.features 在 Windows 上 300 只全量读回会 MemoryError/Errno22
死锁（joblib 多进程）; bin 格式极简(首 float=起始日历索引, 其后 float32 值),
直接解码即等价于 qlib 读取路径的核心, 且全量覆盖无死角。

用法: python experiments/qlib_baseline/bin_check.py [--field close] [--csv csv_data]
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent


def read_bin(path: Path) -> tuple[int, np.ndarray]:
    raw = path.read_bytes()
    start_idx = struct.unpack("<f", raw[:4])[0]
    vals = np.frombuffer(raw[4:], dtype="<f")
    return int(start_idx), vals


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--field", default="close")
    ap.add_argument("--csv", default=str(BASE / "csv_data"))
    ap.add_argument("--qlib", default=str(BASE / "qlib_data"))
    args = ap.parse_args()

    cal = [line.strip() for line in
           (Path(args.qlib) / "calendars" / "day.txt").read_text().splitlines()
           if line.strip()]
    csv_dir, feat_dir = Path(args.csv), Path(args.qlib) / "features"

    n_checked = n_mismatch = n_missing = 0
    problems: list[str] = []
    syms = sorted(p.stem.upper() for p in csv_dir.glob("*.csv"))
    for sym in syms:
        bin_path = feat_dir / sym.lower() / f"{args.field}.day.bin"
        src = pd.read_csv(csv_dir / f"{sym.lower()}.csv").set_index("date")
        if not bin_path.exists():
            n_missing += 1
            problems.append(f"{sym}: {args.field}.day.bin 缺失")
            continue
        start_idx, vals = read_bin(bin_path)
        if start_idx < 0 or start_idx >= len(cal):
            problems.append(f"{sym}: 非法起始索引 {start_idx}")
            continue
        n_bin = len(vals)
        if n_bin > len(cal) - start_idx:
            problems.append(f"{sym}: bin 长度 {n_bin} 超出日历余量")
            continue
        bin_dates = cal[start_idx:start_idx + n_bin]
        bin_series = pd.Series(vals, index=bin_dates)
        common = src.index.intersection(bin_series.index)
        # 源 CSV 的每个日期都应出现在 bin 中(且非 NaN, 停牌日 dump 时为 NaN 源本就无行)
        for d in common:
            a, b = float(src.loc[d, args.field]), float(bin_series.loc[d])
            n_checked += 1
            if not np.isclose(a, b, rtol=1e-4, atol=1e-3):
                n_mismatch += 1
                if len(problems) < 20:
                    problems.append(f"{sym} {d}: csv={a:.4f} bin={b:.4f}")
        miss = len(src) - len(common)
        if miss:
            problems.append(f"{sym}: {miss} 个源日期不在 bin 中")

    print(f"校验 {len(syms)} 标的 field={args.field}: 比对 {n_checked} 项, "
          f"不符 {n_mismatch}, 缺 bin {n_missing}")
    if problems:
        print("PROBLEMS:")
        for p in problems[:20]:
            print(" ", p)
        raise SystemExit(1)
    print("BIN DECODE CHECK PASS")


if __name__ == "__main__":
    main()
