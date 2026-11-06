import { describe, expect, it } from "vitest";

import {
  DEFAULT_INDUSTRY_TOP,
  parseMarketSearch,
  toMarketSearch,
} from "./marketParams";

describe("W08-07 market query state", () => {
  it("parses valid top/date/board/theme values", () => {
    expect(
      parseMarketSearch("top=10&date=2026-11-05&board=bk0475&theme=半导体"),
    ).toEqual({
      top: 10,
      date: "2026-11-05",
      board: "BK0475",
      theme: "半导体",
    });
  });

  it("falls back to defaults for illegal or out-of-range values", () => {
    expect(
      parseMarketSearch("top=999&date=2026-13-01&board=600519&theme="),
    ).toEqual({
      top: DEFAULT_INDUSTRY_TOP,
      date: "",
      board: "",
      theme: "",
    });
  });

  it("drops defaults when writing the canonical query", () => {
    expect(
      toMarketSearch({ top: 20, date: "", board: "", theme: "" }),
    ).toBe("");
    expect(
      toMarketSearch({
        top: 30,
        date: "2026-11-05",
        board: "BK0475",
        theme: "算力",
      }),
    ).toBe("top=30&date=2026-11-05&board=BK0475&theme=%E7%AE%97%E5%8A%9B");
  });
});