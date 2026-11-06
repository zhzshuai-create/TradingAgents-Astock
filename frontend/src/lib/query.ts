/** Fixed query keys and cache rules shared by every page. */

import type { QueryClient, QueryFunctionContext } from "@tanstack/react-query";

import { getJob, getStageReport, listJobs } from "../api/jobs";
import {
  getIndustryStocks,
  getMarketIndustries,
  getMarketNewsflash,
  getMarketOverview,
  getStrongStocks,
  searchStocks,
} from "../api/market";
import { getMetaOptions } from "../api/meta";
import { getReport, listReports } from "../api/reports";
import type { JobListFilters, ReportListFilters } from "../api/types";

const JOBS_ROOT = ["jobs"] as const;
const JOB_ROOT = ["job"] as const;
const REPORTS_ROOT = ["reports"] as const;
const REPORT_ROOT = ["report"] as const;

export const queryKeys = {
  jobs: (filters: JobListFilters = {}) => [JOBS_ROOT[0], filters] as const,
  job: (jobId: string) => [JOB_ROOT[0], jobId] as const,
  stageReport: (jobId: string, stageId: string) =>
    [JOB_ROOT[0], jobId, "stage", stageId] as const,
  reports: (filters: ReportListFilters = {}) =>
    [REPORTS_ROOT[0], filters] as const,
  report: (reportId: string) => [REPORT_ROOT[0], reportId] as const,
  metaOptions: ["meta", "options"] as const,
  marketSearch: (query: string) => ["market", "search", query] as const,
  marketOverview: () => ["market", "overview"] as const,
  marketIndustries: (top: number) => ["market", "industries", top] as const,
  marketConstituents: (board: string, limit: number) =>
    ["market", "constituents", board, limit] as const,
  marketStrongStocks: (date: string | null) =>
    ["market", "strong", date] as const,
  marketNewsflash: (limit: number) =>
    ["market", "newsflash", limit] as const,
  stockSnapshot: (ticker: string) => ["stock", "snapshot", ticker] as const,
  stockKline: (ticker: string, period: string, limit: number) =>
    ["stock", "kline", ticker, period, limit] as const,
  stockIntraday: (ticker: string, date: string | null) =>
    ["stock", "intraday", ticker, date] as const,
  stockNews: (ticker: string, limit: number) =>
    ["stock", "news", ticker, limit] as const,
  stockFundFlow: (ticker: string) =>
    ["stock", "fundFlow", ticker] as const,
  stockReports: (ticker: string, cursor: string | null) =>
    ["stock", "reports", ticker, cursor] as const,
};

/** meta/options may be reused for at most one minute. */
export const META_OPTIONS_STALE_MS = 60_000;

/** Contract freshness thresholds; pages use these as ``staleTime`` (D9). */
export const MARKET_STALE_MS = {
  overview: 10_000,
  northbound: 30_000,
  industries: 300_000,
  constituents: 120_000,
  strongStocks: 3_600_000,
  newsflash: 120_000,
  search: 86_400_000,
} as const;

export const STOCK_STALE_MS = {
  snapshot: 60_000,
  valuation: 14_400_000,
  sectorBlocks: 86_400_000,
  kline: 300_000,
  intradayToday: 30_000,
  intradayHistory: 3_600_000,
  news: 300_000,
  fundFlow: 60_000,
} as const;

export const jobsQuery = (filters: JobListFilters = {}) => ({
  queryKey: queryKeys.jobs(filters),
  queryFn: ({ signal }: QueryFunctionContext) => listJobs(filters, signal),
  staleTime: 0,
});

export const jobDetailQuery = (jobId: string) => ({
  queryKey: queryKeys.job(jobId),
  queryFn: ({ signal }: QueryFunctionContext) => getJob(jobId, signal),
  staleTime: 0,
});

export const stageReportQuery = (jobId: string, stageId: string) => ({
  queryKey: queryKeys.stageReport(jobId, stageId),
  queryFn: ({ signal }: QueryFunctionContext) =>
    getStageReport(jobId, stageId, signal),
  staleTime: 0,
  retry: false,
});

/** A report row is immutable; a short stale window prevents remount refetches. */
export const reportDetailQuery = (reportId: string) => ({
  queryKey: queryKeys.report(reportId),
  queryFn: ({ signal }: QueryFunctionContext) => getReport(reportId, signal),
  staleTime: 60_000,
  retry: false,
});

export const metaOptionsQuery = {
  queryKey: queryKeys.metaOptions,
  queryFn: ({ signal }: QueryFunctionContext) => getMetaOptions(signal),
  staleTime: META_OPTIONS_STALE_MS,
  gcTime: META_OPTIONS_STALE_MS,
};

export const marketSearchQuery = (query: string) => ({
  queryKey: queryKeys.marketSearch(query),
  queryFn: ({ signal }: QueryFunctionContext) => searchStocks(query, 10, signal),
  staleTime: 0,
});

/** Workbench rows are cheap to refresh, same rule as the W05 list page. */
export const recentReportsQuery = (limit = 3) => ({
  queryKey: queryKeys.reports({ limit }),
  queryFn: ({ signal }: QueryFunctionContext) => listReports({ limit }, signal),
  staleTime: 0,
});

export const marketOverviewQuery = () => ({
  queryKey: queryKeys.marketOverview(),
  queryFn: ({ signal }: QueryFunctionContext) => getMarketOverview(signal),
  staleTime: MARKET_STALE_MS.overview,
});

export const marketIndustriesQuery = (top = 20) => ({
  queryKey: queryKeys.marketIndustries(top),
  queryFn: ({ signal }: QueryFunctionContext) =>
    getMarketIndustries(top, signal),
  staleTime: MARKET_STALE_MS.industries,
});

export const marketStrongStocksQuery = (date: string | null = null) => ({
  queryKey: queryKeys.marketStrongStocks(date),
  queryFn: ({ signal }: QueryFunctionContext) => getStrongStocks(date ?? undefined, signal),
  staleTime: MARKET_STALE_MS.strongStocks,
});

export const marketConstituentsQuery = (board: string, limit = 10) => ({
  queryKey: queryKeys.marketConstituents(board, limit),
  queryFn: ({ signal }: QueryFunctionContext) =>
    getIndustryStocks(board, limit, signal),
  staleTime: MARKET_STALE_MS.constituents,
  enabled: board !== "",
});

export const marketNewsflashQuery = (limit = 30) => ({
  queryKey: queryKeys.marketNewsflash(limit),
  queryFn: ({ signal }: QueryFunctionContext) =>
    getMarketNewsflash(limit, signal),
  staleTime: MARKET_STALE_MS.newsflash,
});

/** Control actions refresh the list without touching the streamed detail. */
export async function invalidateJobList(client: QueryClient): Promise<void> {
  await client.invalidateQueries({ queryKey: JOBS_ROOT });
}

/** Every control action invalidates the list and the addressed detail. */
export async function invalidateJobQueries(
  client: QueryClient,
  jobId?: string,
): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: JOBS_ROOT }),
    jobId
      ? client.invalidateQueries({ queryKey: [JOB_ROOT[0], jobId] })
      : client.invalidateQueries({ queryKey: JOB_ROOT }),
  ]);
}
