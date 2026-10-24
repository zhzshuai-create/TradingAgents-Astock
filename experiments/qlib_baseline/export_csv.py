# -*- coding: utf-8 -*-
"""T3 阶段2: 东财后复权日K -> qlib dump CSV（主环境跑）.

数据源: 东财 push2his kline/get, klt=101 日线, fqt=2 后复权。
🔴 口径教训(2026-10-24 实测): EM fqt=1 前复权全历史 OHLC 是损坏的——
600519 在 2016 段 close=25.6 而 amount/volume 推算真实价≈309(12 倍失真,
比值逐年漂移), 且只返回近~10年。后复权锚定 IPO、只乘不减、永不为负,
是因子/回测数据的标准做法(qlib 官方数据同口径)。
输出: 每股一个 CSV（列: date,open,close,high,low,volume）, 文件名
{SH|SZ}{code}.csv（dump_bin 以文件名为 symbol, 自动生成 instruments/日历）。
volume 单位=手(EM 口径); vwap 不导出——EM 的 amount 是原始口径与复权价不
一致, 且基础 Alpha158 只用 OHLCV(仅 Alpha158vwap 子类才要 $vwap)。

用法:
    python experiments/qlib_baseline/export_csv.py --pool eval     # 评估池(run_*.json 标的)
    python experiments/qlib_baseline/export_csv.py --pool train    # 训练池(沪深300, 失败退成交额前300)
    python experiments/qlib_baseline/export_csv.py --pool all
    python experiments/qlib_baseline/export_csv.py --pool all --source tencent  # 强制腾讯引擎

引擎: --source auto(默认)=EM 优先、全池任一失败则整池切腾讯（全池同源,
杜绝混口径）; EM push2his 间歇拒连是常态, 腾讯 fqkline hfq 稳定（单次
上限 800 根, 起点由 --start 控制, 默认 2010-01-01）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests as _requests

PROJ = Path(__file__).resolve().parents[2]
RESULTS = PROJ / "experiments" / "results"
OUT_DEFAULT = Path(__file__).resolve().parent / "csv_data"

sys.path.insert(0, str(PROJ))

from tradingagents.dataflows.a_stock._common import _em_get  # noqa: E402

KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EM_HEADERS = {"Referer": "https://quote.eastmoney.com/"}
TX_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TX_HEADERS = {"Referer": "https://gu.qq.com/"}


def exchange_prefix(code: str) -> str:
    return "SH" if code.startswith("6") else "SZ"


def em_daily(code: str) -> pd.DataFrame:
    """EM 全量后复权日K; 失败抛异常由上层处理。"""
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    params = {
        "secid": secid, "klt": "101", "fqt": "2",
        "beg": "19900101", "end": "20500101",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56",
    }
    r = _em_get(KLINE_URL, params=params, headers=EM_HEADERS, timeout=20)
    klines = ((r.json().get("data") or {}).get("klines")) or []
    rows = []
    for line in klines:
        p = line.split(",")
        if len(p) < 6:
            continue
        try:
            rows.append((p[0], float(p[1]), float(p[2]), float(p[3]),
                         float(p[4]), float(p[5])))
        except ValueError:
            continue
    if not rows:
        raise ValueError(f"empty klines for {code}")
    return _clean_rows(rows)


def tencent_daily(code: str, start: str = "2010-01-01") -> pd.DataFrame:
    """腾讯 fqkline 后复权日K: 单次上限 800 根, 以本页首日为新终点向前翻页。"""
    sym = ("sh" if code.startswith("6") else "sz") + code
    seen: set[str] = set()
    all_rows: list[tuple] = []
    end = "2050-01-01"
    for page in range(12):  # ~9600 根安全上限
        url = f"{TX_URL}?param={sym},day,{start},{end},800,hfq"
        j = _requests.get(url, timeout=20, headers=TX_HEADERS).json()
        inner = (j.get("data") or {}).get(sym) or {}
        rows = inner.get("hfqday")
        if rows is None:
            if page == 0:
                raise ValueError(f"tx no hfqday for {code}: {j.get('msg')}")
            break
        for r in rows:
            if r[0] not in seen:
                seen.add(r[0])
                all_rows.append((r[0], float(r[1]), float(r[2]),
                                 float(r[3]), float(r[4]), float(r[5])))
        first = rows[0][0]
        if first <= start or len(rows) < 2:
            break
        end = first  # 翻页: 下一请求终点=本页首日(重复行由 seen 去重)
        time.sleep(0.15)
    if not all_rows:
        raise ValueError(f"tx empty for {code}")
    return _clean_rows(all_rows)


def _clean_rows(rows: list[tuple]) -> pd.DataFrame:
    """守卫: 后复权价理论上恒正, 非正行=脏数据剔除; 去重排序。"""
    df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low",
                                     "volume"])
    ok = (df[["open", "close", "high", "low"]] > 0).all(axis=1)
    df = df[ok].drop_duplicates("date").sort_values("date").reset_index(drop=True)
    if df.empty:
        raise ValueError("no positive-price rows")
    return df[["date", "open", "close", "high", "low", "volume"]]


def eval_pool() -> list[str]:
    """评估池 = run_*.json 里全部成功运行的标的（与 T2/T3 信号对照同源）。"""
    codes = set()
    for f in sorted(RESULTS.glob("run_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("error") is None and d.get("ticker"):
            codes.add(d["ticker"])
    return sorted(c for c in codes if c.startswith(("0", "3", "6")))


def train_pool() -> list[str]:
    """训练池: 沪深300 成分(EM clist i: 通道), 失败退化为成交额(f6)前300。"""
    # 阶梯1: 指数成分通道
    codes, source = [], ""
    try:
        for pn in (1, 2, 3):
            params = {
                "pn": pn, "pz": "100", "po": "1", "np": "1",
                "fltt": "2", "invt": "2", "fid": "f12",
                "fs": "i:1.000300", "fields": "f12",
            }
            r = _em_get(CLIST_URL, params=params, headers=EM_HEADERS, timeout=15)
            diff = (r.json().get("data") or {}).get("diff") or []
            codes += [str(x.get("f12")) for x in diff if x.get("f12")]
        if len(codes) >= 250:
            source = "csi300"
    except Exception:
        codes = []
    # 阶梯2: 成交额前300（与评估信号对照的训练池口径记录进 manifest）
    if not codes:
        try:
            for pn in (1, 2, 3):
                params = {
                    "pn": pn, "pz": "100", "po": "1", "np": "1",
                    "fltt": "2", "invt": "2", "fid": "f6",
                    "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "fields": "f12",
                }
                r = _em_get(CLIST_URL, params=params, headers=EM_HEADERS, timeout=15)
                diff = (r.json().get("data") or {}).get("diff") or []
                codes += [str(x.get("f12")) for x in diff if x.get("f12")]
            source = "turnover-top300"
        except Exception as e:
            raise RuntimeError(
                f"训练池两阶梯均失败(EM 拒连?): {e}; 限流通常数小时内解除后重试") from e
    seen, uniq = set(), []
    for c in codes:
        if c not in seen and c.startswith(("0", "3", "6")):
            seen.add(c)
            uniq.append(c)
    print(f"[pool] train source={source} count={len(uniq)}")
    return uniq[:300]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", choices=["eval", "train", "all"], default="eval")
    ap.add_argument("--source", choices=["auto", "em", "tencent"], default="auto")
    ap.add_argument("--start", default="2010-01-01",
                    help="腾讯引擎翻页起点(EM 引擎忽略, 返回全历史)")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    pools: list[str] = []
    if args.pool in ("eval", "all"):
        pools += eval_pool()
    if args.pool in ("train", "all"):
        pools += [c for c in train_pool() if c not in set(pools)]
    print(f"[pool] {args.pool}: {len(pools)} tickers")

    def run_pass(engine: str, force: bool) -> tuple[list[str], list[tuple]]:
        done, failed = [], []
        fetch = (em_daily if engine == "em"
                 else lambda c: tencent_daily(c, args.start))
        for i, code in enumerate(pools, 1):
            sym = exchange_prefix(code) + code
            csv_path = out / f"{sym.lower()}.csv"
            if csv_path.exists() and not force:
                done.append(sym)
                continue
            try:
                df = fetch(code)
                df.to_csv(csv_path, index=False)
                done.append(sym)
                if i % 20 == 0 or i == len(pools):
                    print(f"[{engine} {i}/{len(pools)}] {sym} rows={len(df)} "
                          f"{df['date'].iloc[0]}~{df['date'].iloc[-1]}")
            except Exception as e:
                failed.append((code, str(e)[:80]))
            if engine == "em" and i % 10 == 0:
                time.sleep(0.5)  # _em_get 自带令牌桶, 批量再加一层保险
        return done, failed

    if args.source == "auto":
        # 全池同源规则: EM 先试, 任一失败(EM 间歇拒连常态)→整池切腾讯重跑
        done, failed = run_pass("em", force=True)
        engine = "em"
        if failed:
            print(f"[auto] EM {len(failed)} 失败 → 整池切腾讯(全池同源)")
            engine = "tencent"
            done, failed = run_pass("tencent", force=True)
    else:
        engine = args.source
        done, failed = run_pass(engine, force=True)

    manifest = {
        "pool": args.pool, "engine": engine,
        "source_api": ("eastmoney push2his klt=101 fqt=2(后复权)" if engine == "em"
                       else f"tencent fqkline hfq(后复权, start={args.start})"),
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ok": len(done), "failed": len(failed), "failed_detail": failed,
    }
    (out / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] engine={engine} ok={len(done)} failed={len(failed)} -> {out}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
