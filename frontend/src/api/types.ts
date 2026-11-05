/** Frozen response shapes from api-v1.md. Field names stay snake_case. */

export type JobStatus =
  | "queued"
  | "running"
  | "pause_requested"
  | "paused"
  | "cancel_requested"
  | "cancelled"
  | "succeeded"
  | "failed"
  | "interrupted";

export type PendingAction = "pause" | "cancel" | null;

export type StageId =
  | "market"
  | "social"
  | "news"
  | "fundamentals"
  | "policy"
  | "hot_money"
  | "lockup"
  | "quality_gate"
  | "debate"
  | "trader"
  | "risk"
  | "pm";

export type StageStatus = "pending" | "active" | "done" | "failed" | "skipped";

export type AllowedAction =
  | "pause"
  | "resume"
  | "cancel"
  | "retry"
  | "reanalyze"
  | "resume_from_checkpoint";

export interface JobStage {
  id: StageId;
  name: string;
  index: number;
  status: StageStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface CurrentStage {
  id: StageId;
  name: string;
  index: number;
  total: number;
  status: StageStatus;
}

export interface JobStats {
  model_calls: number;
  tokens_in: number;
  tokens_out: number;
  elapsed_ms: number;
}

export interface JobError {
  code: string;
  message: string;
}

export interface JobLinks {
  self: string;
  events: string;
  report: string | null;
}

export interface ReconcileNote {
  code: string;
  message: string;
  at: string;
}

export interface JobSummary {
  job_id: string;
  status: JobStatus;
  pending_action: PendingAction;
  ticker_code: string;
  ticker_name: string | null;
  analysis_date: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  current_stage: CurrentStage | null;
  stats: JobStats;
  report_id: string | null;
  error: JobError | null;
  config_digest: string;
  graph_version: string;
  retry_of_job_id: string | null;
  resume_of_job_id: string | null;
  resume_from_stage: StageId | null;
  allowed_actions: AllowedAction[];
  links: JobLinks;
  /** Detail-only in the contract; the list happens to include it too. */
  reconcile_notes?: ReconcileNote[];
}

export interface JobDetail extends JobSummary {
  stages: JobStage[];
  reconcile_notes: ReconcileNote[];
}

export interface JobListResponse {
  items: JobSummary[];
  next_cursor: string | null;
}

export interface JobListFilters {
  status?: JobStatus[];
  ticker?: string;
  date_from?: string;
  date_to?: string;
  active?: boolean;
  limit?: number;
  cursor?: string;
}

export interface JobConfig {
  llm_profile: string;
  parallel_analysts: boolean;
  stage_toggles: Record<string, boolean>;
}

export interface CreateJobRequest {
  ticker: string;
  analysis_date: string;
  config: JobConfig;
}

export type RetryMode = "same_config" | "resume_from_checkpoint";

export type ControlAction = "pause" | "resume" | "cancel";

export interface ControlAccepted {
  job_id: string;
  accepted: true;
  action: ControlAction;
  accepted_at: string;
  expected_effect: "at_stage_boundary";
  status: JobStatus;
}

export interface ControlRejected {
  job_id: string;
  accepted: false;
  reason: string;
  status: JobStatus;
}

export type ControlResponse = ControlAccepted | ControlRejected;

export interface MetaProfile {
  id: string;
  label: string;
}

export interface MetaStageToggle {
  id: string;
  label: string;
  default: boolean;
}

export type JournalReason = "not_running" | "not_installed" | "probe_failed";

export interface JournalStatus {
  available: boolean;
  entry_url: string;
  reason: JournalReason | null;
}

export interface MetaOptions {
  app_version: string;
  server_time: string;
  default_analysis_date: string;
  llm_profiles: MetaProfile[];
  stage_toggles: MetaStageToggle[];
  limits: {
    max_active_jobs: number;
    max_date_ahead_days: number;
  };
  journal: JournalStatus;
  contract_version: string;
}

export type MarketStatus = "ok" | "empty" | "stale" | "error";

export type MarketId = "sh" | "sz" | "bj";

export interface MarketSearchItem {
  ticker_code: string;
  ticker_name: string;
  market: MarketId;
}

export interface MarketSearchData {
  items: MarketSearchItem[];
  truncated: boolean;
}

export type StaleReason =
  | "ttl_exceeded"
  | "trading_day_mismatch"
  | "upstream_fallback";

export interface MarketEnvelope<T> {
  schema_version: string;
  status: MarketStatus;
  source: string;
  as_of: string | null;
  fetched_at: string;
  is_stale: boolean;
  stale_reason: StaleReason | null;
  error_code: string | null;
  error_message: string | null;
  partial: boolean;
  failed_blocks: string[];
  /** Only multi-block endpoints carry it; search omits it. */
  blocks?: Record<string, unknown>;
  data: T | null;
}
