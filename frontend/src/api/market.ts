/** Market and stock endpoints (api-v1.md section 3, frozen through v1). */

import { apiRequest } from "./client";
import type {
  FundFlowData,
  IntradayData,
  KlineData,
  KlinePeriod,
  MarketConstituentsData,
  MarketEnvelope,
  MarketIndustriesData,
  MarketNewsflashData,
  MarketOverviewData,
  MarketSearchData,
  MarketStrongStocksData,
  ReportListResponse,
  StockNewsData,
  StockSnapshotData,
} from "./types";

function withQuery(path: string, params: URLSearchParams): string {
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

function stockPath(ticker: string, suffix: string): string {
  return `/api/v1/stocks/${encodeURIComponent(ticker)}/${suffix}`;
}

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

export function getMarketOverview(
  signal?: AbortSignal,
): Promise<MarketEnvelope<MarketOverviewData>> {
  return apiRequest<MarketEnvelope<MarketOverviewData>>(
    "/api/v1/market/overview",
    { signal },
  );
}

export function getMarketIndustries(
  top?: number,
  signal?: AbortSignal,
): Promise<MarketEnvelope<MarketIndustriesData>> {
  const params = new URLSearchParams();
  if (typeof top === "number") {
    params.set("top", String(top));
  }
  return apiRequest<MarketEnvelope<MarketIndustriesData>>(
    withQuery("/api/v1/market/industries", params),
    { signal },
  );
}

export function getIndustryStocks(
  boardCode: string,
  limit?: number,
  signal?: AbortSignal,
): Promise<MarketEnvelope<MarketConstituentsData>> {
  const params = new URLSearchParams();
  if (typeof limit === "number") {
    params.set("limit", String(limit));
  }
  const path = `/api/v1/market/industries/${encodeURIComponent(boardCode)}/stocks`;
  return apiRequest<MarketEnvelope<MarketConstituentsData>>(
    withQuery(path, params),
    { signal },
  );
}

export function getStrongStocks(
  date?: string,
  signal?: AbortSignal,
): Promise<MarketEnvelope<MarketStrongStocksData>> {
  const params = new URLSearchParams();
  if (date) {
    params.set("date", date);
  }
  return apiRequest<MarketEnvelope<MarketStrongStocksData>>(
    withQuery("/api/v1/market/strong-stocks", params),
    { signal },
  );
}

export function getMarketNewsflash(
  limit?: number,
  signal?: AbortSignal,
): Promise<MarketEnvelope<MarketNewsflashData>> {
  const params = new URLSearchParams();
  if (typeof limit === "number") {
    params.set("limit", String(limit));
  }
  return apiRequest<MarketEnvelope<MarketNewsflashData>>(
    withQuery("/api/v1/market/newsflash", params),
    { signal },
  );
}

export function getStockSnapshot(
  ticker: string,
  signal?: AbortSignal,
): Promise<MarketEnvelope<StockSnapshotData>> {
  return apiRequest<MarketEnvelope<StockSnapshotData>>(
    stockPath(ticker, "snapshot"),
    { signal },
  );
}

export function getStockKline(
  ticker: string,
  period: KlinePeriod = "day",
  limit?: number,
  signal?: AbortSignal,
): Promise<MarketEnvelope<KlineData>> {
  const params = new URLSearchParams({ period });
  if (typeof limit === "number") {
    params.set("limit", String(limit));
  }
  return apiRequest<MarketEnvelope<KlineData>>(
    withQuery(stockPath(ticker, "kline"), params),
    { signal },
  );
}

export function getStockIntraday(
  ticker: string,
  date?: string,
  signal?: AbortSignal,
): Promise<MarketEnvelope<IntradayData>> {
  const params = new URLSearchParams();
  if (date) {
    params.set("date", date);
  }
  return apiRequest<MarketEnvelope<IntradayData>>(
    withQuery(stockPath(ticker, "intraday"), params),
    { signal },
  );
}

export function getStockNews(
  ticker: string,
  limit?: number,
  signal?: AbortSignal,
): Promise<MarketEnvelope<StockNewsData>> {
  const params = new URLSearchParams();
  if (typeof limit === "number") {
    params.set("limit", String(limit));
  }
  return apiRequest<MarketEnvelope<StockNewsData>>(
    withQuery(stockPath(ticker, "news"), params),
    { signal },
  );
}

export function getStockFundFlow(
  ticker: string,
  signal?: AbortSignal,
): Promise<MarketEnvelope<FundFlowData>> {
  return apiRequest<MarketEnvelope<FundFlowData>>(
    stockPath(ticker, "fund-flow"),
    { signal },
  );
}

export function getStockReports(
  ticker: string,
  filters: { limit?: number; cursor?: string } = {},
  signal?: AbortSignal,
): Promise<ReportListResponse> {
  const params = new URLSearchParams();
  if (typeof filters.limit === "number") {
    params.set("limit", String(filters.limit));
  }
  if (filters.cursor) {
    params.set("cursor", filters.cursor);
  }
  return apiRequest<ReportListResponse>(
    withQuery(stockPath(ticker, "reports"), params),
    { signal },
  );
}
