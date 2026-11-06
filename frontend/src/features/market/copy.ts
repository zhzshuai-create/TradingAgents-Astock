/**
 * Single copy source for market/stock states, sources and sessions.
 *
 * p4-backlog section 1.4 froze these strings; components import them instead
 * of spelling Chinese status words inline.
 */

import type {
  MarketSession,
  MarketStatus,
  StaleReason,
} from "../../api/types";

export type DataStateValue = MarketStatus | "loading";

export const STATE_COPY = {
  loading: { label: "加载中" },
  ok: { label: "数据已更新" },
  empty: { title: "暂无数据" },
  error: { title: "数据源请求失败", retry: "重试" },
  stale: { title: "数据可能已过期" },
} as const;

export const PARTIAL_COPY = "部分数据不可用";

export const STALE_REASON_COPY: Record<StaleReason, string> = {
  ttl_exceeded: "超过新鲜度阈值",
  trading_day_mismatch: "数据日期早于最近交易日",
  upstream_fallback: "已使用备用数据源",
};

export const SOURCE_LABELS: Record<string, string> = {
  tencent: "腾讯",
  eastmoney: "东方财富",
  ths: "同花顺",
  hexin: "同花顺",
  cls: "财联社",
  mootdx: "通达信",
  "mootdx-cache": "本地名称表",
  baidu: "百度",
  mixed: "多源",
  static: "本地",
};

export const SESSION_LABELS: Record<MarketSession, string> = {
  pre_open: "未开盘",
  trading: "交易中",
  lunch_break: "午间休市",
  closed: "已收盘",
};

export const BLOCK_LABELS: Record<string, string> = {
  quote: "行情",
  valuation: "估值",
  sector_blocks: "板块",
  indices: "指数",
  northbound: "北向",
};

export const EMPTY_COPY = {
  strongStocksNonTrading: "非交易日或盘后未更新",
  intradayOutOfRetention: "该日期没有分时数据",
} as const;

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

export function sessionLabel(session: MarketSession): string {
  return SESSION_LABELS[session];
}

export function blockLabel(block: string): string {
  return BLOCK_LABELS[block] ?? block;
}

export function staleDescription(reason: StaleReason | null): string | null {
  return reason === null ? null : STALE_REASON_COPY[reason];
}
