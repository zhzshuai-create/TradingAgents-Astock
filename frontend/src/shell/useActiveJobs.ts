/** `GET /jobs?active=true` polled every 10 seconds for the top bar. */

import { useQuery, type QueryFunctionContext } from "@tanstack/react-query";

import { listJobs } from "../api/jobs";
import type { JobListFilters, JobStatus, JobSummary } from "../api/types";
import { queryKeys } from "../lib/query";

export const ACTIVE_JOBS_FILTER: JobListFilters = { active: true, limit: 100 };
export const ACTIVE_JOBS_REFETCH_MS = 10_000;

/** The five non-terminal statuses (api-v1.md 1.4). */
export const ACTIVE_JOB_STATUSES: readonly JobStatus[] = [
  "queued",
  "running",
  "pause_requested",
  "paused",
  "cancel_requested",
];

export function activeJobsQueryOptions() {
  return {
    queryKey: queryKeys.jobs(ACTIVE_JOBS_FILTER),
    queryFn: ({ signal }: QueryFunctionContext) =>
      listJobs(ACTIVE_JOBS_FILTER, signal),
    staleTime: 0,
    refetchInterval: ACTIVE_JOBS_REFETCH_MS,
    retry: false,
  };
}

export interface ActiveJobsState {
  jobs: JobSummary[];
  job: JobSummary | null;
  extra: number;
}

export function useActiveJobs(): ActiveJobsState {
  const { data } = useQuery(activeJobsQueryOptions());
  // The server filters too; this guards against a response cached before a
  // job reached a terminal state.
  const jobs = (data?.items ?? []).filter((job) =>
    ACTIVE_JOB_STATUSES.includes(job.status),
  );
  return {
    jobs,
    job: jobs[0] ?? null,
    extra: Math.max(0, jobs.length - 1),
  };
}
