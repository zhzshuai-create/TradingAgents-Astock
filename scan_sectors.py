"""A股行业板块近一月涨跌幅排名"""
import time
import sys
from datetime import datetime, timedelta
import akshare as ak

start_date = (datetime.now() - timedelta(days=35)).strftime("%Y%m%d")
end_date = datetime.now().strftime("%Y%m%d")
print(f"区间: {(datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")
print("=" * 55)

# 获取行业列表
print("获取行业板块列表...")
df_ind = ak.stock_board_industry_summary_ths()
time.sleep(3)

# 逐个计算月收益
print(f"逐行业获取K线计算月收益 (共 {len(df_ind)} 个行业)...\n")
sector_data = {}

for i, (_, row) in enumerate(df_ind.iterrows()):
    name = row.iloc[1]
    if not name or not isinstance(name, str):
        continue

    for attempt in range(3):
        try:
            df = ak.stock_board_industry_index_ths(
                symbol=name,
                start_date=start_date,
                end_date=end_date,
            )
            if df is None or len(df) < 2:
                break

            close_col = df.columns[4]  # 收盘价
            first_close = float(df[close_col].iloc[0])
            last_close = float(df[close_col].iloc[-1])
            month_ret = (last_close / first_close - 1) * 100

            sector_data[name] = {
                "ret": month_ret,
                "first": first_close,
                "last": last_close,
                "days": len(df),
            }

            bar = "█" * max(1, int(abs(month_ret)))
            sign = "+" if month_ret >= 0 else ""
            print(f"  {i+1:2d}. {name:<16s} {sign}{month_ret:+7.2f}%  {bar}")
            break

        except Exception as e:
            if attempt < 2:
                time.sleep(5)
            else:
                err = str(e)[:50]
                print(f"  {i+1:2d}. {name:<16s} [跳过: {err}]")

    time.sleep(1.5)

if not sector_data:
    print("未获取到数据"); sys.exit(1)

# ---- 排名 ----
sorted_all = sorted(sector_data.items(), key=lambda x: x[1]["ret"], reverse=True)

print("\n" + "=" * 60)
print("  近一月涨势最强行业板块 TOP 15")
print("=" * 60)
for rank, (name, d) in enumerate(sorted_all[:15], 1):
    bar = "█" * max(1, int(d["ret"] / 2))
    a1 = "▲" if d["ret"] > 0 else "▽"
    print(f"  {rank:2d}. {name:<18s} {a1} {d['ret']:+7.2f}%  {bar}")

print("\n" + "=" * 60)
print("  近一月跌幅最大行业板块 BOTTOM 10")
print("=" * 60)
for rank, (name, d) in enumerate(sorted_all[-10:][::-1], 1):
    bar = "▁" * max(1, int(abs(d["ret"]) / 2))
    print(f"  {rank:2d}. {name:<18s}   {d['ret']:+7.2f}%  {bar}")

# 总体分布
rets = [d["ret"] for _, d in sorted_all]
pos = sum(1 for r in rets if r > 0)
neg = sum(1 for r in rets if r < 0)
print(f"\n总计 {len(rets)} 个行业 | 上涨: {pos} | 下跌: {neg} | 平均: {sum(rets)/len(rets):+.2f}%")
print(f"最强: {sorted_all[0][0]} ({sorted_all[0][1]['ret']:.2f}%) | 最弱: {sorted_all[-1][0]} ({sorted_all[-1][1]['ret']:.2f}%)")
