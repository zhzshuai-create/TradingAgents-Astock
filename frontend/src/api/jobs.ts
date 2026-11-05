/** Job endpoints from api-v1.md section 1. */

import { apiRequest } from "./client";
import type {
  ControlAction,
  ControlResponse,
  CreateJobRequest,
  JobDetail,
  JobListFilters,
  JobListResponse,
  RetryMode,
} from "./types";

function listPath(filters: JobListFilters): string {
  const params = new URLSearchParams();
  if (filters.active === true) {
    params.set("active", "true");
  } else if (filters.status && filters.status.length > 0) {
    params.set("status", filters.status.join(","));
  }
  if (filters.ticker) {
    params.set("ticker", filters.ticker);
  }
  if (filters.date_from) {
    params.set("date_from", filters.date_from);
  }
  if (filters.date_to) {
    params.set("date_to", filters.date_to);
  }
  if (typeof filters.limit === "number") {
    params.set("limit", String(filters.limit));
  }
  if (filters.cursor) {
    params.set("cursor", filters.cursor);
  }
  const query = params.toString();
  return `/api/v1/jobs${query ? `?${query}` : ""}`;
}

export function listJobs(
  filters: JobListFilters = {},
  signal?: AbortSignal,
): Promise<JobListResponse> {
  return apiRequest<JobListResponse>(listPath(filters), { signal });
}

export function getJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobDetail> {
  return apiRequest<JobDetail>(`/api/v1/jobs/${encodeURIComponent(jobId)}`, {
    signal,
  });
}

export function createJob(
  payload: CreateJobRequest,
  idempotencyKey: string,
): Promise<JobDetail> {
  return apiRequest<JobDetail>("/api/v1/jobs", {
    method: "POST",
    body: payload,
    idempotencyKey,
  });
}

export function controlJob(
  jobId: string,
  action: ControlAction,
): Promise<ControlResponse> {
  return apiRequest<ControlResponse>(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/actions`,
    { method: "POST", body: { action } },
  );
}

export function retryJob(
  jobId: string,
  mode: RetryMode,
  idempotencyKey: string,
): Promise<JobDetail> {
  return apiRequest<JobDetail>(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/retry`,
    { method: "POST", body: { mode }, idempotencyKey },
  );
}
