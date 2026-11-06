/** Report endpoints from api-v1.md section 2.1 (P3-04 reads the list only). */

import { apiRequest } from "./client";
import type { ReportListFilters, ReportListResponse } from "./types";

function listPath(filters: ReportListFilters): string {
  const params = new URLSearchParams();
  if (filters.ticker) {
    params.set("ticker", filters.ticker);
  }
  if (filters.date_from) {
    params.set("date_from", filters.date_from);
  }
  if (filters.date_to) {
    params.set("date_to", filters.date_to);
  }
  if (filters.rating && filters.rating.length > 0) {
    params.set("rating", filters.rating.join(","));
  }
  if (typeof filters.limit === "number") {
    params.set("limit", String(filters.limit));
  }
  if (filters.cursor) {
    params.set("cursor", filters.cursor);
  }
  const query = params.toString();
  return `/api/v1/reports${query ? `?${query}` : ""}`;
}

export function listReports(
  filters: ReportListFilters = {},
  signal?: AbortSignal,
): Promise<ReportListResponse> {
  return apiRequest<ReportListResponse>(listPath(filters), { signal });
}
