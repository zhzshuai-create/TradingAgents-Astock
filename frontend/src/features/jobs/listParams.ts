/** URL query <-> filter state <-> GET /jobs parameters (api-v1.md 1.4). */

import type { JobListFilters, JobStatus } from "../../api/types";

export const PAGE_LIMIT = 20;

/** Contract order; the checkbox list and the comma list both follow it. */
export const JOB_STATUS_ORDER: readonly JobStatus[] = [
  "queued",
  "running",
  "pause_requested",
  "paused",
  "cancel_requested",
  "cancelled",
  "succeeded",
  "failed",
  "interrupted",
];

export interface JobListState {
  statuses: JobStatus[];
  ticker: string;
  dateFrom: string;
  dateTo: string;
  activeOnly: boolean;
  /** Opaque server cursor; never parsed or built by the client. */
  cursor: string | null;
}

const CODE_PATTERN = /^\d{6}$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function isAnalysisDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}

export function normalizeDateRange(
  from: string,
  to: string,
): { dateFrom: string; dateTo: string } {
  const dateFrom = isAnalysisDate(from) ? from : "";
  const dateTo = isAnalysisDate(to) ? to : "";
  if (dateFrom !== "" && dateTo !== "" && dateFrom > dateTo) {
    return { dateFrom: "", dateTo: "" };
  }
  return { dateFrom, dateTo };
}

function parseStatuses(raw: string | null): JobStatus[] {
  if (raw === null || raw.trim() === "") {
    return [...JOB_STATUS_ORDER];
  }
  const wanted = new Set(raw.split(",").map((value) => value.trim()));
  const picked = JOB_STATUS_ORDER.filter((status) => wanted.has(status));
  // Unknown values are dropped; nothing valid left means "all".
  if (picked.length === 0 || picked.length === JOB_STATUS_ORDER.length) {
    return [...JOB_STATUS_ORDER];
  }
  return picked;
}

function selectedStatuses(statuses: JobStatus[]): JobStatus[] {
  const picked = JOB_STATUS_ORDER.filter((status) => statuses.includes(status));
  return picked.length === 0 ? [...JOB_STATUS_ORDER] : picked;
}

export function parseJobListSearch(search: string): JobListState {
  const params = new URLSearchParams(search);
  const ticker = (params.get("ticker") ?? "").trim();
  const dates = normalizeDateRange(
    params.get("date_from") ?? "",
    params.get("date_to") ?? "",
  );
  const active = params.get("active");

  return {
    statuses: parseStatuses(params.get("status")),
    ticker: CODE_PATTERN.test(ticker) ? ticker : "",
    dateFrom: dates.dateFrom,
    dateTo: dates.dateTo,
    activeOnly: active === "1" || active === "true",
    cursor: params.get("cursor") || null,
  };
}

/** Request parameters only; the cursor is added by the page per page. */
export function toJobListFilters(state: JobListState): JobListFilters {
  const filters: JobListFilters = { limit: PAGE_LIMIT };
  const statuses = selectedStatuses(state.statuses);
  if (state.activeOnly) {
    filters.active = true;
  } else if (statuses.length < JOB_STATUS_ORDER.length) {
    filters.status = statuses;
  }
  if (CODE_PATTERN.test(state.ticker)) {
    filters.ticker = state.ticker;
  }
  const dates = normalizeDateRange(state.dateFrom, state.dateTo);
  if (dates.dateFrom !== "") {
    filters.date_from = dates.dateFrom;
  }
  if (dates.dateTo !== "") {
    filters.date_to = dates.dateTo;
  }
  return filters;
}

/** Canonical query string without the leading "?"; "" is the default view. */
export function toJobListSearch(state: JobListState): string {
  const params = new URLSearchParams();
  const statuses = selectedStatuses(state.statuses);
  if (statuses.length < JOB_STATUS_ORDER.length) {
    params.set("status", statuses.join(","));
  }
  if (CODE_PATTERN.test(state.ticker)) {
    params.set("ticker", state.ticker);
  }
  const dates = normalizeDateRange(state.dateFrom, state.dateTo);
  if (dates.dateFrom !== "") {
    params.set("date_from", dates.dateFrom);
  }
  if (dates.dateTo !== "") {
    params.set("date_to", dates.dateTo);
  }
  if (state.activeOnly) {
    params.set("active", "true");
  }
  if (state.cursor) {
    params.set("cursor", state.cursor);
  }
  return params.toString();
}

export function listStateHasFilters(state: JobListState): boolean {
  return (
    selectedStatuses(state.statuses).length < JOB_STATUS_ORDER.length ||
    CODE_PATTERN.test(state.ticker) ||
    isAnalysisDate(state.dateFrom) ||
    isAnalysisDate(state.dateTo) ||
    state.activeOnly
  );
}
