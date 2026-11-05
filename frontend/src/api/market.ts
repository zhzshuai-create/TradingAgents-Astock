/** Market data endpoints (api-v1.md section 3). */

import { apiRequest } from "./client";
import type { MarketEnvelope, MarketSearchData } from "./types";

export function searchStocks(
  query: string,
  limit?: number,
  signal?: AbortSignal,
): Promise<MarketEnvelope<MarketSearchData>> {
  const params = new URLSearchParams({ q: query });
  if (typeof limit === "number") {
    params.set("limit", String(limit));
  }
  return apiRequest<MarketEnvelope<MarketSearchData>>(
    `/api/v1/market/search?${params.toString()}`,
    { signal },
  );
}
