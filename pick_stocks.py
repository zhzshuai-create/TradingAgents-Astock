"""精选主板强趋势股 — TradingAgents 内置数据源"""
import sys, csv, io, time
sys.path.insert(0, r'C:\Users\zhzsh\TradingAgents-astock')
from tradingagents.dataflows.a_stock import get_stock_data

MAX_P, MIN_P, MIN_RET = 60, 6, 8

STOCKS = {
    '002185':'华天科技','600460':'士兰微','600171':'上海贝岭',
    '000725':'京东方A','600703':'三安光电','603986':'兆易创新',
    '002049':'紫光国微','603005':'晶方科技','603160':'汇顶科技',
    '600584':'长电科技','600745':'闻泰科技','002916':'深南电路',
    '002409':'雅克科技','000636':'风华高科','002138':'顺络电子',
    '603678':'火炬电子','002484':'江海股份','600563':'法拉电子',
    '002436':'兴森科技','000823':'超声电子',
    '002028':'思源电气','000400':'许继电气','600089':'特变电工',
    '601179':'中国西电','600406':'国电南瑞','601727':'上海电气',
    '000063':'中兴通讯','600487':'亨通光电','002396':'星网锐捷',
    '600498':'烽火通信','603236':'移远通信',
    '002747':'埃斯顿','002527':'新时达','600835':'上海机电',
    '002460':'赣锋锂业','600111':'北方稀土','002466':'天齐锂业',
    '002241':'歌尔股份','002456':'欧菲光','002273':'水晶光电',
    '601138':'工业富联','603501':'韦尔股份','600050':'中国联通',
    '600536':'中国软件','601698':'中国卫通',
}

print(f"扫描 {len(STOCKS)} 只主板标的 | ¥{MIN_P}-{MAX_P} | 月收益>{MIN_RET}%\n")

candidates = []
for i, (code, name) in enumerate(STOCKS.items(), 1):
    try:
        raw = get_stock_data(symbol=code, start_date='2026-04-14', end_date='2026-05-14')
        lines = raw.strip().split('\n')
        data_start = 0
        for j, line in enumerate(lines):
            if 'Date,Open' in line or '日期' in line:
                data_start = j + 1
                break
        if data_start == 0:
            continue
        reader = csv.DictReader(lines[data_start-1:])
        rows = list(reader)
        if len(rows) < 7:
            continue

        # K线数据
        close_col = 'Close' if 'Close' in rows[0] else '收盘'
        last = float(rows[-1][close_col])
        first = float(rows[0][close_col])
        if last < MIN_P or last > MAX_P:
            continue

        month_ret = (last / first - 1) * 100
        if month_ret < MIN_RET:
            continue

        # 5日收益
        ret_5d = (last / float(rows[-5][close_col]) - 1) * 100 if len(rows) >= 5 else 0

        # 均线多头
        closes = [float(r[close_col]) for r in rows]
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else ma5
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else ma10
        bull = last > ma5 > ma10 > ma20

        # 量比
        vol_col = 'Volume' if 'Volume' in rows[0] else '成交量'
        vols = [float(r[vol_col]) for r in rows]
        vr = sum(vols[-5:]) / sum(vols[-15:]) if len(vols) >= 15 else 1

        candidates.append({
            'code':code,'name':name,'price':last,
            'month_ret':month_ret,'ret_5d':ret_5d,
            'bullish':bull,'vol_ratio':vr
        })

        b = '▲多头' if bull else ' —'
        print(f"  {len(candidates):2d}. {code} {name:<8s} ¥{last:>7.2f} "
              f"月+{month_ret:>6.1f}% 5d+{ret_5d:>5.1f}% {b} 量{vr:.1f}x")
    except:
        continue

if len(candidates) < 3:
    print(f"\n仅{len(candidates)}只符合条件 (月收益>{MIN_RET}%)")
    import sys; sys.exit(1)

# 排名
import pandas as pd
df = pd.DataFrame(candidates)
df['score'] = (
    df['month_ret'] * 0.40 + df['ret_5d'] * 0.30 +
    df['bullish'].astype(int) * 6 + df['vol_ratio'].clip(0.5, 3) * 2
)
df = df.sort_values('score', ascending=False)

print(f"\n{'='*60}")
print(f"  ★ 精选 3 只主板强趋势股 (本金 ¥6000)")
print(f"{'='*60}")

for rank, (_, r) in enumerate(df.head(3).iterrows(), 1):
    cost = r['price'] * 100
    left = 6000 - cost
    print(f"\n  ┌{'─'*54}┐")
    print(f"  │ #{rank}  {r['code']}  {r['name']}")
    print(f"  ├{'─'*54}┤")
    print(f"  │ 现价 ¥{r['price']:.2f} | 一手 ¥{cost:.0f} | 余额 ¥{left:.0f}")
    print(f"  │ 月收益 +{r['month_ret']:.1f}% | 5日 +{r['ret_5d']:+.1f}%")
    print(f"  │ 趋势 {'多头排列 ▲' if r['bullish'] else '盘整 —'} | 量比 {r['vol_ratio']:.1f}x | 评分 {r['score']:.1f}")
    print(f"  └{'─'*54}┘")

print(f"\n备选:")
for rank, (_, r) in enumerate(df.iloc[3:7].iterrows(), 4):
    print(f"  {rank}. {r['code']} {r['name']:<8s} ¥{r['price']:>6.2f}  "
          f"月+{r['month_ret']:>5.1f}% 5d+{r['ret_5d']:>5.1f}%  {'▲' if r['bullish'] else '—'}")
