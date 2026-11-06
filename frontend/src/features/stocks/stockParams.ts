/** URL query <-> W07 stock workspace state (p4-backlog D7 and 1.6). */

import type { KlinePeriod, MarketId } from "../../api/types";
import { isMarketDate } from "../market/marketParams";

export const STOCK_TABS = [
  "valuation",
  "kline",
  "intraday",
  "news",
  "reports",
] as const;

export type StockTab = (typeof STOCK_TABS)[number];

export const DEFAULT_STOCK_TAB: StockTab = "valuation";

export const STOCK_TAB_LABELS: Record<StockTab, string> = {
  valuation: "估值",
  kline: "K 线",
  intraday: "分时",
  news: "新闻",
  reports: "报告",
};

export const KLINE_PERIODS: KlinePeriod[] = ["day", "week", "month"];
export const DEFAULT_KLINE_PERIOD: KlinePeriod = "day";

export const KLINE_LIMIT = 120;
export const STOCK_NEWS_LIMIT = 20;
export const STOCK_REPORTS_LIMIT = 20;

export const TICKER_PATTERN = /^\d{6}$/;

export interface StockState {
  tab: StockTab;
  period: KlinePeriod;
  /** "" means the provider's latest trading day. */
  date: string;
}

export function isTickerFormat(value: string): boolean {
  return TICKER_PATTERN.test(value);
}

/** Presentation-only market label; the contract has no market field here. */
export function marketOf(ticker: string): MarketId | null {
  if (ticker.startsWith("92")) {
    return "bj";
  }
  const first = ticker.charAt(0);
  if (first === "5" || first === "6" || first === "9") {
    return "sh";
  }
  if (first === "0" || first === "1" || first === "2" || first === "3") {
    return "sz";
  }
  if (first === "4" || first === "8") {
    return "bj";
  }
  return null;
}

export function marketLabel(market: MarketId | null): string {
  if (market === "sh") {
    return "沪市";
  }
  if (market === "sz") {
    return "深市";
  }
  if (market === "bj") {
    return "京市";
  }
  return "未知市场";
}

function parseTab(raw: string | null): StockTab {
  return (STOCK_TABS as readonly string[]).includes(raw ?? "")
    ? (raw as StockTab)
    : DEFAULT_STOCK_TAB;
}

function parsePeriod(raw: string | null): KlinePeriod {
  return (KLINE_PERIODS as readonly string[]).includes(raw ?? "")
    ? (raw as KlinePeriod)
    : DEFAULT_KLINE_PERIOD;
}

export function parseStockSearch(search: string): StockState {
  const params = new URLSearchParams(search);
  const date = (params.get("date") ?? "").trim();
  return {
    tab: parseTab(params.get("tab")),
    period: parsePeriod(params.get("period")),
    date: isMarketDate(date) ? date : "",
  };
}

/** Canonical query without "?"; defaults and invalid values are dropped. */
export function toStockSearch(state: StockState): string {
  const params = new URLSearchParams();
  if (state.tab !== DEFAULT_STOCK_TAB) {
    params.set("tab", state.tab);
  }
  if (state.period !== DEFAULT_KLINE_PERIOD) {
    params.set("period", state.period);
  }
  if (isMarketDate(state.date)) {
    params.set("date", state.date);
  }
  return params.toString();
}
