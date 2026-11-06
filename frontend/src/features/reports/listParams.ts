/** URL query <-> report filter state <-> GET /reports parameters (api-v1.md 2.1). */

import type { ReportListFilters, ReportRating } from "../../api/types";

export const REPORT_PAGE_LIMIT = 20;

/** Contract order; the checkbox list and the comma list both follow it. */
export const REPORT_RATING_ORDER: readonly ReportRating[] = [
  "Buy",
  "Overweight",
  "Hold",
  "Underweight",
  "Sell",
  "unknown",
];

export interface ReportListState {
  ticker: string;
  dateFrom: string;
  dateTo: string;
  ratings: ReportRating[];
  /** Opaque server cursor; never parsed or built by the client. */
  cursor: string | null;
}

const CODE_PATTERN = /^\d{6}$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function isReportDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}

export function normalizeReportDateRange(
  from: string,
  to: string,
): { dateFrom: string; dateTo: string } {
  const dateFrom = isReportDate(from) ? from : "";
  const dateTo = isReportDate(to) ? to : "";
  if (dateFrom !== "" && dateTo !== "" && dateFrom > dateTo) {
    return { dateFrom: "", dateTo: "" };
  }
  return { dateFrom, dateTo };
}

function parseRatings(raw: string | null): ReportRating[] {
  if (raw === null || raw.trim() === "") {
    return [...REPORT_RATING_ORDER];
  }
  const wanted = new Set(raw.split(",").map((value) => value.trim()));
  const picked = REPORT_RATING_ORDER.filter((rating) => wanted.has(rating));
  // Unknown values are dropped; nothing valid left means "all".
  if (picked.length === 0 || picked.length === REPORT_RATING_ORDER.length) {
    return [...REPORT_RATING_ORDER];
  }
  return picked;
}

function selectedRatings(ratings: ReportRating[]): ReportRating[] {
  const picked = REPORT_RATING_ORDER.filter((rating) =>
    ratings.includes(rating),
  );
  return picked.length === 0 ? [...REPORT_RATING_ORDER] : picked;
}

export function parseReportListSearch(search: string): ReportListState {
  const params = new URLSearchParams(search);
  const ticker = (params.get("ticker") ?? "").trim();
  const dates = normalizeReportDateRange(
    params.get("date_from") ?? "",
    params.get("date_to") ?? "",
  );

  return {
    ticker: CODE_PATTERN.test(ticker) ? ticker : "",
    dateFrom: dates.dateFrom,
    dateTo: dates.dateTo,
    ratings: parseRatings(params.get("rating")),
    cursor: params.get("cursor") || null,
  };
}

/** Request parameters only; the cursor is added by the page per page. */
export function toReportListFilters(state: ReportListState): ReportListFilters {
  const filters: ReportListFilters = { limit: REPORT_PAGE_LIMIT };
  if (CODE_PATTERN.test(state.ticker)) {
    filters.ticker = state.ticker;
  }
  const dates = normalizeReportDateRange(state.dateFrom, state.dateTo);
  if (dates.dateFrom !== "") {
    filters.date_from = dates.dateFrom;
  }
  if (dates.dateTo !== "") {
    filters.date_to = dates.dateTo;
  }
  const ratings = selectedRatings(state.ratings);
  if (ratings.length < REPORT_RATING_ORDER.length) {
    filters.rating = ratings;
  }
  return filters;
}

/** Canonical query string without the leading "?"; "" is the default view. */
export function toReportListSearch(state: ReportListState): string {
  const params = new URLSearchParams();
  if (CODE_PATTERN.test(state.ticker)) {
    params.set("ticker", state.ticker);
  }
  const dates = normalizeReportDateRange(state.dateFrom, state.dateTo);
  if (dates.dateFrom !== "") {
    params.set("date_from", dates.dateFrom);
  }
  if (dates.dateTo !== "") {
    params.set("date_to", dates.dateTo);
  }
  const ratings = selectedRatings(state.ratings);
  if (ratings.length < REPORT_RATING_ORDER.length) {
    params.set("rating", ratings.join(","));
  }
  if (state.cursor) {
    params.set("cursor", state.cursor);
  }
  return params.toString();
}

export function reportListStateHasFilters(state: ReportListState): boolean {
  return (
    selectedRatings(state.ratings).length < REPORT_RATING_ORDER.length ||
    CODE_PATTERN.test(state.ticker) ||
    isReportDate(state.dateFrom) ||
    isReportDate(state.dateTo)
  );
}
