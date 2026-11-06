/** Fixed synthetic bars for the P4-08 chart tests. No real market data. */

import type {
  IntradayData,
  IntradayPoint,
  KlineBar,
  KlineData,
} from "../../api/types";

function bar(
  date: string,
  open: number,
  high: number,
  low: number,
  close: number,
  volume: number,
  amount: number | null = volume * close * 100,
): KlineBar {
  return { date, open, high, low, close, volume, amount };
}

export const DAILY_BARS: KlineBar[] = [
  bar("2026-09-01", 10.1, 10.4, 10.0, 10.32, 118000),
  bar("2026-09-02", 10.32, 10.55, 10.2, 10.28, 132000),
  bar("2026-09-03", 10.26, 10.35, 10.05, 10.12, 98000),
  bar("2026-09-04", 10.12, 10.44, 10.08, 10.4, 141000),
  bar("2026-09-07", 10.42, 10.72, 10.38, 10.66, 168000),
  bar("2026-09-08", 10.66, 10.8, 10.5, 10.55, 154000),
  bar("2026-09-09", 10.55, 10.62, 10.28, 10.35, 120000),
  bar("2026-09-10", 10.35, 10.48, 10.22, 10.44, 113000),
  bar("2026-09-11", 10.44, 10.88, 10.4, 10.82, 205000),
  bar("2026-09-14", 10.82, 11.0, 10.7, 10.9, 198000),
  bar("2026-09-15", 10.9, 11.12, 10.8, 10.86, 176000),
  bar("2026-09-16", 10.86, 10.94, 10.6, 10.68, 149000),
  bar("2026-09-17", 10.68, 10.75, 10.42, 10.48, 138000),
  bar("2026-09-18", 10.48, 10.66, 10.44, 10.62, 121000),
  bar("2026-09-21", 10.62, 10.98, 10.58, 10.94, 189000),
  bar("2026-09-22", 10.94, 11.08, 10.84, 10.88, 162000),
  bar("2026-09-23", 10.88, 10.92, 10.62, 10.7, 134000),
  bar("2026-09-24", 10.7, 10.78, 10.5, 10.58, 116000),
  bar("2026-09-25", 10.58, 10.64, 10.3, 10.38, 127000),
  bar("2026-09-28", 10.38, 10.52, 10.26, 10.5, 109000),
  bar("2026-09-29", 10.5, 10.74, 10.46, 10.72, 143000),
  bar("2026-09-30", 10.72, 10.96, 10.68, 10.92, 171000),
  bar("2026-10-08", 10.92, 11.06, 10.76, 10.82, 156000),
  bar("2026-10-09", 10.82, 10.9, 10.54, 10.6, 133000),
];

export const WEEKLY_BARS: KlineBar[] = [
  bar("2026-08-07", 9.8, 10.2, 9.7, 10.1, 512000),
  bar("2026-08-14", 10.1, 10.45, 9.95, 10.3, 548000),
  bar("2026-08-21", 10.3, 10.6, 10.05, 10.22, 601000),
  bar("2026-08-28", 10.22, 10.7, 10.1, 10.62, 633000),
  bar("2026-09-04", 10.62, 10.88, 10.4, 10.4, 590000),
  bar("2026-09-11", 10.4, 11.0, 10.2, 10.82, 711000),
  bar("2026-09-18", 10.82, 11.12, 10.42, 10.62, 689000),
  bar("2026-09-25", 10.62, 11.08, 10.3, 10.38, 655000),
];

export const MONTHLY_BARS: KlineBar[] = [
  bar("2026-06-30", 9.2, 9.9, 9.0, 9.75, 2100000),
  bar("2026-07-31", 9.75, 10.35, 9.6, 10.06, 2380000),
  bar("2026-08-31", 10.06, 10.72, 9.95, 10.62, 2510000),
  bar("2026-09-30", 10.62, 11.12, 10.2, 10.92, 2260000),
];

export const UNITS = { price: "元", volume: "手", amount: "元" } as const;

export const DAILY_DATA: KlineData = {
  adjust: "none",
  bars: DAILY_BARS,
  units: UNITS,
};

export const WEEKLY_DATA: KlineData = {
  adjust: "none",
  bars: WEEKLY_BARS,
  units: UNITS,
};

export const MONTHLY_DATA: KlineData = {
  adjust: "none",
  bars: MONTHLY_BARS,
  units: UNITS,
};

/** One bar with a missing amount; every other field stays valid. */
export const MISSING_AMOUNT_DATA: KlineData = {
  adjust: "none",
  bars: DAILY_BARS.map((item, index) =>
    index === DAILY_BARS.length - 1 ? { ...item, amount: null } : item,
  ),
  units: UNITS,
};

const POINTS: IntradayPoint[] = [
  { time: "09:30", price: 10.0, volume: 1000, avg_price: 10.0 },
  { time: "09:35", price: 10.05, volume: 1200, avg_price: 10.02 },
  { time: "10:00", price: 9.98, volume: 900, avg_price: 10.01 },
  { time: "10:30", price: 10.12, volume: 1500, avg_price: 10.05 },
  { time: "11:25", price: 10.08, volume: 800, avg_price: 10.06 },
  { time: "11:30", price: 10.1, volume: 600, avg_price: 10.06 },
  { time: "13:00", price: 10.15, volume: 1400, avg_price: 10.08 },
  { time: "13:30", price: 10.2, volume: 1100, avg_price: 10.1 },
  { time: "14:00", price: 10.18, volume: 700, avg_price: null },
  { time: "14:30", price: 10.25, volume: 900, avg_price: 10.12 },
  { time: "14:55", price: 10.22, volume: 500, avg_price: 10.13 },
  { time: "15:00", price: 10.24, volume: 1600, avg_price: 10.13 },
];

export const INTRADAY_DATA: IntradayData = {
  date: "2026-11-05",
  points: POINTS,
  session_gaps: [["11:30", "13:00"]],
  units: UNITS,
};

export const SINGLE_POINT_DATA: IntradayData = {
  date: "2026-11-05",
  points: [{ time: "09:35", price: 10.05, volume: 1200, avg_price: null }],
  session_gaps: [["11:30", "13:00"]],
  units: UNITS,
};
