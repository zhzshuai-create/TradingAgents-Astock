/**
 * Section order and part vocabulary from report-schema-v1 section 3, mirroring
 * backend/app/services/report_render.py so the reader, Markdown and PDF show
 * the same sequence. The DOM order is the contract order, never the JSON key
 * order; empty sections are not rendered and not listed in the table of
 * contents.
 */

import type { ReportSection } from "../../api/types";

export const REPORT_SECTION_ORDER = [
  "sec-decision",
  "sec-market",
  "sec-sentiment",
  "sec-news",
  "sec-fundamentals",
  "sec-policy",
  "sec-hot-money",
  "sec-lockup",
  "sec-quality",
  "sec-debate",
  "sec-trader",
  "sec-plan",
  "sec-risk",
] as const;

export const PART_ORDER: Record<string, readonly string[]> = {
  "sec-debate": ["bull", "bear", "history", "current", "judge"],
  "sec-risk": ["aggressive", "conservative", "neutral", "history", "judge"],
};

export const PART_LABELS: Record<string, Record<string, string>> = {
  "sec-debate": {
    bull: "多方论点",
    bear: "空方论点",
    history: "辩论记录",
    current: "当前回应",
    judge: "研究经理结论",
  },
  "sec-risk": {
    aggressive: "激进观点",
    conservative: "保守观点",
    neutral: "中性观点",
    history: "风控记录",
    judge: "风控结论",
  },
};

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function sectionHasContent(
  section: ReportSection | undefined,
): section is ReportSection {
  if (section === undefined) {
    return false;
  }
  if (text(section.body) !== "") {
    return true;
  }
  const parts = section.parts;
  if (parts !== undefined && Object.values(parts).some((value) => text(value) !== "")) {
    return true;
  }
  const refs = section.parts_ref;
  return refs !== undefined && Object.keys(refs).length > 0;
}

export function orderedSections(
  sections: Record<string, ReportSection>,
): ReportSection[] {
  return REPORT_SECTION_ORDER.map((id) => sections[id]).filter(
    sectionHasContent,
  );
}

export function orderedPartKeys(
  sectionId: string,
  parts: Record<string, string>,
): string[] {
  const preferred = PART_ORDER[sectionId] ?? [];
  const keys = preferred.filter((key) => text(parts[key]) !== "");
  const rest = Object.keys(parts)
    .filter((key) => !preferred.includes(key) && text(parts[key]) !== "")
    .sort();
  return [...keys, ...rest];
}

export function partLabel(sectionId: string, key: string): string {
  return PART_LABELS[sectionId]?.[key] ?? key;
}

/** Contract chapter number (1-13) so a missing chapter leaves a gap. */
export function sectionNumber(sectionId: string): number {
  const index = REPORT_SECTION_ORDER.indexOf(
    sectionId as (typeof REPORT_SECTION_ORDER)[number],
  );
  return index === -1 ? 0 : index + 1;
}
