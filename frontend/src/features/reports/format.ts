/** Display vocabulary for ReportSummary rows (W05). */

import type { ReportRating, ReportSummary } from "../../api/types";
import type { BadgeTone } from "../../ui";

export interface ReportRatingMeta {
  label: string;
  tone: BadgeTone;
}

export const REPORT_RATING_META: Record<ReportRating, ReportRatingMeta> = {
  Buy: { label: "买入", tone: "success" },
  Overweight: { label: "增持", tone: "info" },
  Hold: { label: "中性", tone: "neutral" },
  Underweight: { label: "减持", tone: "warning" },
  Sell: { label: "卖出", tone: "danger" },
  unknown: { label: "未知", tone: "neutral" },
};

export function originLabel(report: ReportSummary): string {
  return report.meta.origin === "legacy_import" ? "历史导入" : "AI 分析";
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/**
 * Same-year reports read as "10-28 11:41"; older rows keep the year. A null or
 * unparsable timestamp is shown as unknown, never replaced by a file mtime.
 */
export function formatGeneratedAt(
  iso: string | null,
  now: Date = new Date(),
): string {
  if (iso === null) {
    return "生成时间未知";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "生成时间未知";
  }
  const monthDay = `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  const clock = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const year =
    date.getFullYear() === now.getFullYear() ? "" : `${date.getFullYear()}-`;
  return `${year}${monthDay} ${clock}`;
}

export function summaryLabel(report: ReportSummary): string {
  return report.summary_available ? "有" : "—";
}
