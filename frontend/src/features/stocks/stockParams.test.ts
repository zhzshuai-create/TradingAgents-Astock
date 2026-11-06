import { describe, expect, it } from "vitest";

import {
  DEFAULT_KLINE_PERIOD,
  DEFAULT_STOCK_TAB,
  KLINE_PERIODS,
  marketLabel,
  marketOf,
  parseStockSearch,
  STOCK_TABS,
  toStockSearch,
  type StockState,
} from "./stockParams";

const BASE: StockState = {
  tab: DEFAULT_STOCK_TAB,
  period: DEFAULT_KLINE_PERIOD,
  date: "",
};

describe("stockParams", () => {
  it("parses every legal tab and period", () => {
    for (const tab of STOCK_TABS) {
      expect(parseStockSearch(`?tab=${tab}`).tab).toBe(tab);
    }
    for (const period of KLINE_PERIODS) {
      expect(parseStockSearch(`?period=${period}`).period).toBe(period);
    }
  });

  it("falls back to valuation/day/latest for illegal values", () => {
    const state = parseStockSearch("?tab=task&period=year&date=2026-13-01");
    expect(state).toEqual({ tab: "valuation", period: "day", date: "" });
  });

  it("keeps a valid date and drops it from the canonical query when empty", () => {
    expect(parseStockSearch("?date=2026-10-29").date).toBe("2026-10-29");
    expect(toStockSearch({ ...BASE, date: "2026-10-29" })).toBe(
      "date=2026-10-29",
    );
    expect(toStockSearch(BASE)).toBe("");
  });

  it("serialises only non-default tab and period", () => {
    expect(toStockSearch({ tab: "kline", period: "week", date: "" })).toBe(
      "tab=kline&period=week",
    );
    expect(toStockSearch({ tab: "valuation", period: "day", date: "" })).toBe("");
  });
});

describe("marketOf", () => {
  it("maps 6-digit codes onto the three exchange labels", () => {
    expect(marketOf("600000")).toBe("sh");
    expect(marketOf("688981")).toBe("sh");
    expect(marketOf("000001")).toBe("sz");
    expect(marketOf("300750")).toBe("sz");
    expect(marketOf("830799")).toBe("bj");
    expect(marketOf("920001")).toBe("bj");
    expect(marketOf("900901")).toBe("sh");
    expect(marketOf("700000")).toBeNull();
  });

  it("renders Chinese market labels", () => {
    expect(marketLabel("sh")).toBe("沪市");
    expect(marketLabel("sz")).toBe("深市");
    expect(marketLabel("bj")).toBe("京市");
    expect(marketLabel(null)).toBe("未知市场");
  });
});
