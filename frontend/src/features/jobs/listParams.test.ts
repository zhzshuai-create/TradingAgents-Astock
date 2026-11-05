import { describe, expect, it } from "vitest";

import {
  JOB_STATUS_ORDER,
  listStateHasFilters,
  normalizeDateRange,
  parseJobListSearch,
  toJobListFilters,
  toJobListSearch,
} from "./listParams";

describe("WEB-10 list query conversion", () => {
  it("defaults to every status without writing a status parameter", () => {
    const state = parseJobListSearch("");
    expect(state.statuses).toEqual([...JOB_STATUS_ORDER]);
    expect(toJobListSearch(state)).toBe("");
    expect(toJobListFilters(state)).toEqual({ limit: 20 });
  });

  it("treats all nine statuses as no filter", () => {
    const state = parseJobListSearch(`status=${JOB_STATUS_ORDER.join(",")}`);
    expect(state.statuses).toEqual([...JOB_STATUS_ORDER]);
    expect(toJobListSearch(state)).toBe("");
    expect(toJobListFilters(state)).toEqual({ limit: 20 });
  });

  it("keeps a subset in contract order and drops unknown statuses", () => {
    const state = parseJobListSearch("status=failed,bogus,running,queued");
    expect(state.statuses).toEqual(["queued", "running", "failed"]);
    expect(toJobListSearch(state)).toBe("status=queued%2Crunning%2Cfailed");
    expect(toJobListFilters(state)).toEqual({
      status: ["queued", "running", "failed"],
      limit: 20,
    });
  });

  it("drops an empty or fully invalid status list back to all", () => {
    for (const search of ["status=", "status=bogus"]) {
      const state = parseJobListSearch(search);
      expect(state.statuses).toEqual([...JOB_STATUS_ORDER]);
      expect(toJobListSearch(state)).toBe("");
    }
  });

  it("accepts only six-digit tickers", () => {
    expect(parseJobListSearch("ticker=000629").ticker).toBe("000629");
    expect(parseJobListSearch("ticker=629").ticker).toBe("");
    expect(parseJobListSearch("ticker=00062a").ticker).toBe("");
  });

  it("validates dates and rejects a reversed range", () => {
    expect(parseJobListSearch("date_from=2026-11-01&date_to=2026-11-05")).toMatchObject({
      dateFrom: "2026-11-01",
      dateTo: "2026-11-05",
    });
    expect(parseJobListSearch("date_from=2026-02-30")).toMatchObject({
      dateFrom: "",
      dateTo: "",
    });
    expect(parseJobListSearch("date_from=2026-11-05&date_to=2026-11-01")).toMatchObject({
      dateFrom: "",
      dateTo: "",
    });
    expect(normalizeDateRange("2026-11-01", "2026-11-05")).toEqual({
      dateFrom: "2026-11-01",
      dateTo: "2026-11-05",
    });
  });

  it("reads active=1 and active=true, and omits status from the request", () => {
    const state = parseJobListSearch("status=failed&active=1");
    expect(state.activeOnly).toBe(true);
    expect(toJobListFilters(state)).toEqual({ active: true, limit: 20 });
    expect(toJobListSearch(state)).toBe("status=failed&active=true");
  });

  it("keeps the cursor opaque while filters reset it", () => {
    const state = parseJobListSearch("ticker=000629&cursor=abc%1Fdef");
    expect(state.cursor).toBe("abc\u001fdef");
    expect(toJobListSearch(state)).toBe("ticker=000629&cursor=abc%1Fdef");
    expect(listStateHasFilters({ ...state, cursor: null })).toBe(true);
    expect(listStateHasFilters(parseJobListSearch(""))).toBe(false);
  });
});
