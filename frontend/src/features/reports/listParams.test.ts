import { describe, expect, it } from "vitest";

import {
  normalizeReportDateRange,
  parseReportListSearch,
  reportListStateHasFilters,
  REPORT_RATING_ORDER,
  toReportListFilters,
  toReportListSearch,
} from "./listParams";

describe("P3-04 report list query conversion", () => {
  it("defaults to every rating without writing a rating parameter", () => {
    const state = parseReportListSearch("");
    expect(state.ratings).toEqual([...REPORT_RATING_ORDER]);
    expect(toReportListSearch(state)).toBe("");
    expect(toReportListFilters(state)).toEqual({ limit: 20 });
  });

  it("treats all six ratings as no filter", () => {
    const state = parseReportListSearch(
      `rating=${REPORT_RATING_ORDER.join(",")}`,
    );
    expect(state.ratings).toEqual([...REPORT_RATING_ORDER]);
    expect(toReportListSearch(state)).toBe("");
    expect(toReportListFilters(state)).toEqual({ limit: 20 });
  });

  it("keeps a subset in contract order and drops unknown ratings", () => {
    const state = parseReportListSearch("rating=Sell,bogus,Buy,Hold");
    expect(state.ratings).toEqual(["Buy", "Hold", "Sell"]);
    expect(toReportListSearch(state)).toBe("rating=Buy%2CHold%2CSell");
    expect(toReportListFilters(state)).toEqual({
      rating: ["Buy", "Hold", "Sell"],
      limit: 20,
    });
  });

  it("drops an empty or fully invalid rating list back to all", () => {
    for (const search of ["rating=", "rating=bogus"]) {
      const state = parseReportListSearch(search);
      expect(state.ratings).toEqual([...REPORT_RATING_ORDER]);
      expect(toReportListSearch(state)).toBe("");
    }
  });

  it("accepts only six-digit tickers", () => {
    expect(parseReportListSearch("ticker=000629").ticker).toBe("000629");
    expect(parseReportListSearch("ticker=629").ticker).toBe("");
    expect(parseReportListSearch("ticker=00062a").ticker).toBe("");
  });

  it("validates dates and rejects a reversed range", () => {
    expect(
      parseReportListSearch("date_from=2026-11-01&date_to=2026-11-05"),
    ).toMatchObject({
      dateFrom: "2026-11-01",
      dateTo: "2026-11-05",
    });
    expect(parseReportListSearch("date_from=2026-02-30")).toMatchObject({
      dateFrom: "",
      dateTo: "",
    });
    expect(
      parseReportListSearch("date_from=2026-11-05&date_to=2026-11-01"),
    ).toMatchObject({
      dateFrom: "",
      dateTo: "",
    });
    expect(normalizeReportDateRange("2026-11-01", "2026-11-05")).toEqual({
      dateFrom: "2026-11-01",
      dateTo: "2026-11-05",
    });
  });

  it("keeps the cursor opaque and detects an active filter", () => {
    const state = parseReportListSearch("ticker=000629&cursor=abc%1Fdef");
    expect(state.cursor).toBe("abc\u001fdef");
    expect(toReportListSearch(state)).toBe("ticker=000629&cursor=abc%1Fdef");
    expect(reportListStateHasFilters({ ...state, cursor: null })).toBe(true);
    expect(reportListStateHasFilters(parseReportListSearch(""))).toBe(false);
  });
});
