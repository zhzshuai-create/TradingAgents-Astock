/** Job endpoints from api-v1.md section 1. */

import { apiRequest, apiRequestEnvelope } from "./client";
import type {
  ControlAction,
  ControlResponse,
  CreateJobRequest,
  JobDetail,
  JobListFilters,
  JobListResponse,
  RetryMode,
  StageReport,
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

export function getStageReport(
  jobId: string,
  stageId: string,
  signal?: AbortSignal,
): Promise<StageReport> {
  return apiRequest<StageReport>(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/stages/${encodeURIComponent(stageId)}`,
    { signal },
  );
}

export interface CreateJobResult {
  job: JobDetail;
  status: number;
  /** Only from X-Existing-Job; never inferred from the job id. */
  existingJobId: string | null;
  /** Idempotency-Replayed: 1 means this was the same intent replayed. */
  replayed: boolean;
}

export async function createJob(
  payload: CreateJobRequest,
  idempotencyKey: string,
): Promise<CreateJobResult> {
  const envelope = await apiRequestEnvelope<JobDetail>("/api/v1/jobs", {
    method: "POST",
    body: payload,
    idempotencyKey,
  });
  return {
    job: envelope.data,
    status: envelope.status,
    existingJobId: envelope.headers.get("X-Existing-Job"),
    replayed: envelope.headers.get("Idempotency-Replayed") === "1",
  };
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
