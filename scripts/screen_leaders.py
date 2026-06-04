"""
A股龙头筛选 v3

用腾讯行情获取市值/PE，配合手动整理的行业映射（基于申万二级），
按行业市值排名产出龙头名单。
"""

import sys
import urllib.request
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
from mootdx.quotes import Quotes

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ═══════════════════════════════════════════════════════════
# 1. 数据获取
# ═══════════════════════════════════════════════════════════

def all_codes() -> list[str]:
    c = Quotes.factory(market='std')
    df = c.stocks()
    df = df[df["code"].str.match(r'^(6|0|3|4|8)\d{5}$')].copy()
    return sorted(df["code"].unique().tolist())


def tencent_batch(codes: list[str]) -> dict:
    prefixed = []
    for c in codes:
        if c.startswith(("6", "9")): prefixed.append(f"sh{c}")
        elif c.startswith("8"):      prefixed.append(f"bj{c}")
        else:                        prefixed.append(f"sz{c}")
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = resp.read().decode("gbk", errors="replace")
    except Exception:
        return {}
    result = {}
    for line in data.strip().split(";"):
        if "=" not in line or '"' not in line: continue
        vals = line.split('"')[1].split("~")
        if len(vals) < 53: continue
        try:
            result[vals[2]] = {
                "name": vals[1],
                "price": float(vals[3]) if vals[3] else 0,
                "mcap_yi": float(vals[44]) if vals[44] else 0,
                "pe": float(vals[39]) if vals[39] and float(vals[39]) > 0 else None,
                "pb": float(vals[46]) if vals[46] else None,
                "change_pct": float(vals[32]) if vals[32] else 0,
                "turnover": float(vals[38]) if vals[38] else 0,
            }
        except (ValueError, IndexError):
            continue
    return result


# ═══════════════════════════════════════════════════════════
# 2. 行业龙头定义（手动整理代表性行业）
# ═══════════════════════════════════════════════════════════

# 行业 → 该行业需要关注的股票代码
# 这份列表覆盖了A股主要赛道，你可以随时增删
SECTOR_LEADERS_CANDIDATES = {
    "银行": ["601398","601939","601288","600036","000001","600000","002142",
             "601328","601166","600015","601818","600919","601009","601658",
             "600926","002839","601838","601916"],
    "保险": ["601318","601628","601601","601336","601319"],
    "证券": ["600030","300059","601688","601211","000166","600999","600837",
             "601066","002797","300033","600958","601236"],
    "白酒": ["600519","000858","000568","002304","600809","000596","603369"],
    "食品饮料": ["600887","002714","603288","600882","603345","002597","600600"],
    "家电": ["000333","000651","002032","600690","002050"],
    "汽车": ["601238","600104","000625","002594","601689","000800","600418","600733"],
    "新能源车产业链": ["300750","002466","002460","603799","600516","300014",
                      "002074","300124","002340","300073"],
    "光伏": ["601012","600438","002459","688223","688599","688390","688032"],
    "风电": ["002202","601615","300274","688349"],
    "储能/电力设备": ["600406","600875","601877","002129","300274"],
    "半导体": ["688981","002371","603986","688256","688012","688041",
               "603501","688396","002049","300661"],
    "消费电子": ["002475","601138","002241","603160","002456","300433","002384"],
    "通信设备/光模块": ["300308","300502","000063","688313","002281","300394"],
    "AI/计算机": ["002230","603019","688111","300624","688568","002236"],
    "软件": ["688111","300454","300624","002410","600570","002230","600588"],
    "医药": ["600276","300760","000538","300015","603259","002001",
             "600085","688180","300347","300529","300122"],
    "医疗器械": ["300760","688271","300003","300677","300529","688029"],
    "中药": ["600085","000538","002603","600535","000999","600332"],
    "CXO": ["603259","300347","300759","300725","002821"],
    "化工": ["600309","002648","600352","002493","600486","600176","600143"],
    "有色/稀土": ["603993","600111","600547","000831","002460","600259","600988"],
    "钢铁": ["600019","600010","000932","000825","600282","000709"],
    "煤炭": ["601088","600188","600546","601225","601699","600348"],
    "石油": ["601857","600028","600938","600346","603619"],
    "电力/公用事业": ["600900","600025","600905","600023","601985","003816","601991"],
    "建筑/基建": ["601668","601800","601390","601186","601669","600170"],
    "地产": ["000002","600048","001979","600663","000069","600606","002244"],
    "建材": ["600585","002271","000786","601636","002372","603737"],
    "交通运输": ["601919","600009","601111","600029","601006","601816","600115"],
    "军工": ["600760","600893","000768","600150","002025","600316","600391","000733"],
    "农林牧渔": ["002714","002311","000876","002311","300498","600737"],
    "零售": ["601933","002024","603708","600655"],
    "快递/物流": ["002352","600233","603056","002120"],
    "电信/运营商": ["600941","601728","600050"],
    "传媒/游戏": ["002555","300418","002602","300624","600637","603444"],
    "机械/自动化": ["300124","601100","600031","300450","688017","300024"],
    "检测/仪器": ["300012","300887","688007","300416","300797","688012"],
}


def screen_leaders(quotes: dict, sector_map: dict, min_mcap=100) -> pd.DataFrame:
    rows = []
    for sector, codes in sector_map.items():
        for code in codes:
            q = quotes.get(code)
            if not q or q["mcap_yi"] < min_mcap or not q["pe"]:
                continue
            rows.append({
                "行业": sector,
                "代码": code,
                "名称": q["name"],
                "市值(亿)": round(q["mcap_yi"], 0),
                "PE": round(q["pe"], 1),
                "PB": round(q["pb"], 1) if q["pb"] else None,
                "涨跌幅": round(q["change_pct"], 2),
                "换手率": round(q["turnover"], 2),
            })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # 行业内部按市值排名
    df["行业排名"] = df.groupby("行业")["市值(亿)"].rank(ascending=False, method="min")
    # 只取每个行业 top2
    leaders = df[df["行业排名"] <= 2].sort_values(["行业", "行业排名"])
    return leaders


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("📊 A股龙头筛选 v3\n")

    print("① 获取全A股代码...")
    codes = all_codes()
    print(f"   共 {len(codes)} 只\n")

    print("② 批量拉取行情数据（腾讯）...")
    all_q = {}
    for i in range(0, len(codes), 50):
        batch = codes[i:i + 50]
        all_q.update(tencent_batch(batch))
        if (i // 50) % 20 == 0:
            print(f"   {min(i + 50, len(codes))}/{len(codes)}")
    print(f"   获取到 {len(all_q)} 只有效行情\n")

    print("③ 按行业筛选龙头...")
    leaders = screen_leaders(all_q, SECTOR_LEADERS_CANDIDATES, min_mcap=100)

    print(f"\n{'='*75}")
    print(f"  共 {len(leaders)} 只龙头，覆盖 {leaders['行业'].nunique()} 个行业")
    print(f"{'='*75}")

    prev = ""
    for _, r in leaders.iterrows():
        if r["行业"] != prev:
            if prev: print()
            print(f"  【{r['行业']}】")
            prev = r["行业"]
        mcap_str = f"{r['市值(亿)']:.0f}亿"
        pe_str = f"PE {r['PE']:.1f}"
        print(f"    {r['代码']} {r['名称']:<10s}  {mcap_str:>10s}  {pe_str:<12s}")

    # 另存 CSV
    out = Path(__file__).resolve().parent.parent / "output_leaders.csv"
    leaders.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n📁 已导出: {out}")
