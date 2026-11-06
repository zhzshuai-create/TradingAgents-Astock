import { describe, expect, it } from "vitest";

import type { ReportSection } from "../../api/types";
import {
  orderedPartKeys,
  orderedSections,
  partLabel,
  sectionHasContent,
  sectionNumber,
} from "./sections";

function section(
  id: string,
  title: string,
  body: string,
  extra: Partial<ReportSection> = {},
): ReportSection {
  return { id, title, body, ...extra };
}

describe("report section order (T9 web side)", () => {
  it("follows report-schema-v1 order, not JSON key order", () => {
    const ordered = orderedSections({
      "sec-risk": section("sec-risk", "风控评估", "风控正文"),
      "sec-decision": section("sec-decision", "最终交易决策", "决策正文"),
      "sec-market": section("sec-market", "技术分析", "技术正文"),
    });
    expect(ordered.map((item) => item.id)).toEqual([
      "sec-decision",
      "sec-market",
      "sec-risk",
    ]);
  });

  it("drops missing, blank and whitespace-only sections", () => {
    const ordered = orderedSections({
      "sec-decision": section("sec-decision", "最终交易决策", "决策正文"),
      "sec-market": section("sec-market", "技术分析", "   "),
      "sec-news": section("sec-news", "新闻舆情", ""),
      "sec-quality": section("sec-quality", "数据质量", "", {
        parts: { summary: "  " },
      }),
      "sec-policy": section("sec-policy", "政策分析", "", {
        parts: { summary: "有内容" },
      }),
      "sec-debate": section("sec-debate", "多空辩论", "", {
        parts_ref: { judge: "sec-decision" },
      }),
    });
    expect(ordered.map((item) => item.id)).toEqual([
      "sec-decision",
      "sec-policy",
      "sec-debate",
    ]);
    expect(sectionHasContent(undefined)).toBe(false);
  });

  it("numbers chapters by their contract position so gaps stay visible", () => {
    expect(sectionNumber("sec-decision")).toBe(1);
    expect(sectionNumber("sec-market")).toBe(2);
    expect(sectionNumber("sec-risk")).toBe(13);
    expect(sectionNumber("sec-bogus")).toBe(0);
  });

  it("orders debate and risk parts with the backend labels", () => {
    expect(
      orderedPartKeys("sec-debate", {
        judge: "结论",
        bull: "多方",
        current: "  ",
        bear: "空方",
        extra: "补充",
      }),
    ).toEqual(["bull", "bear", "judge", "extra"]);
    expect(partLabel("sec-debate", "judge")).toBe("研究经理结论");
    expect(partLabel("sec-risk", "neutral")).toBe("中性观点");
    expect(partLabel("sec-risk", "unknown-key")).toBe("unknown-key");
  });
});
