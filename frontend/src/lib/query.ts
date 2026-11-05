/** Fixed query keys and cache rules shared by every page. */

import type { QueryClient, QueryFunctionContext } from "@tanstack/react-query";

import { getJob, getStageReport, listJobs } from "../api/jobs";
import { searchStocks } from "../api/market";
import { getMetaOptions } from "../api/meta";
import type { JobListFilters } from "../api/types";

const JOBS_ROOT = ["jobs"] as const;
const JOB_ROOT = ["job"] as const;

export const queryKeys = {
  jobs: (filters: JobListFilters = {}) => [JOBS_ROOT[0], filters] as const,
  job: (jobId: string) => [JOB_ROOT[0], jobId] as const,
  stageReport: (jobId: string, stageId: string) =>
    [JOB_ROOT[0], jobId, "stage", stageId] as const,
  metaOptions: ["meta", "options"] as const,
  marketSearch: (query: string) => ["market", "search", query] as const,
};

/** meta/options may be reused for at most one minute. */
export const META_OPTIONS_STALE_MS = 60_000;

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
