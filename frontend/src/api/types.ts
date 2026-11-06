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

export type JobSseEventType =
  | "snapshot"
  | "stage_changed"
  | "stats"
  | "status_changed"
  | "report_ready"
  | "error";

export interface SseEnvelope<TType extends JobSseEventType, TPayload> {
  seq: number;
  job_id: string;
  type: TType;
  at: string;
  payload: TPayload;
}

export interface SnapshotPayload {
  job: JobDetail;
  last_seq: number;
}

/** sse-events-v1.md 3.1: `started` is the wire name for the active state. */
export interface StageChangedPayload {
  stage_id: StageId;
  stage_name: string;
  stage_status: "started" | "done" | "failed" | "skipped";
  index: number;
  total: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface StatusChangedPayload {
  from: JobStatus;
  to: JobStatus;
  reason: "user" | "worker" | "reconcile";
  detail: string | null;
  pending_action: PendingAction;
  error: JobError | null;
}

export interface ReportReadyPayload {
  report_id: string;
  content_hash: string;
  rating: string | null;
  signal: string | null;
  url: string;
}

export interface SseErrorPayload {
  code: string;
  message: string;
  request_id: string;
  fatal: boolean;
}

export type JobSseEvent =
  | SseEnvelope<"snapshot", SnapshotPayload>
  | SseEnvelope<"stage_changed", StageChangedPayload>
  | SseEnvelope<"stats", JobStats>
  | SseEnvelope<"status_changed", StatusChangedPayload>
  | SseEnvelope<"report_ready", ReportReadyPayload>
  | SseEnvelope<"error", SseErrorPayload>;

/** api-v1.md 1.10: one stage's markdown output, read on demand. */
export interface StageReport {
  job_id: string;
  stage_id: StageId;
  stage_name: string;
  index: number;
  status: StageStatus;
  markdown: string | null;
  truncated: boolean;
  full_length: number;
  updated_at: string | null;
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

export type ReportRating =
  | "Buy"
  | "Overweight"
  | "Hold"
  | "Underweight"
  | "Sell"
  | "unknown";

export type ReportSignal = "Buy" | "Hold" | "Sell" | "unknown";

export type ReportOrigin = "new" | "legacy_import";

export type ReportGeneratedAtSource = "job_clock" | "import_clock" | "unknown";

export type ReportDataQuality = "ok" | "degraded" | "absent";

export type ReportChartSnapshot = "frozen" | "refetch_needed" | "none";

/** report-schema-v1 section 2; field names stay snake_case. */
export interface ReportMeta {
  report_id: string;
  job_id: string | null;
  ticker_code: string;
  ticker_name: string | null;
  analysis_date: string;
  generated_at: string | null;
  generated_at_source: ReportGeneratedAtSource;
  origin: ReportOrigin;
  schema_version: string;
  content_hash: string;
  config_digest: string | null;
  data_quality_status: ReportDataQuality;
  chart_snapshot_status: ReportChartSnapshot;
  retry_of_job_id: string | null;
  rating: ReportRating;
  signal: ReportSignal;
  signal_legacy?: string | null;
  price_target?: number | null;
  stop_reference?: string | null;
  time_horizon?: string | null;
}

/** api-v1.md 2.1: the whole ReportDTO minus sections. */
export interface ReportSummary {
  meta: ReportMeta;
  summary_available: true;
}

/** report-schema-v1 section 3; parts_ref points at an identical section. */
export interface ReportSection {
  id: string;
  title: string;
  body: string;
  parts?: Record<string, string>;
  parts_ref?: Record<string, string>;
  legacy_aliases?: Record<string, string>;
}

/** api-v1.md 2.2: the frozen ReportDTO. */
export interface ReportDetail {
  meta: ReportMeta;
  sections: Record<string, ReportSection>;
}

export interface ReportListResponse {
  items: ReportSummary[];
  next_cursor: string | null;
}

export interface ReportListFilters {
  ticker?: string;
  date_from?: string;
  date_to?: string;
  rating?: ReportRating[];
  limit?: number;
  cursor?: string;
}

/** api-v1.md 2.4-2.5: export job states. */
export type ExportState = "queued" | "rendering" | "ready" | "failed";

export interface ExportError {
  code: string;
  message: string;
}

/** api-v1.md 2.5 status object; `download_url` is null until ready. */
export interface ExportStatus {
  export_id: string;
  report_id: string;
  status: ExportState;
  download_url: string | null;
  error: ExportError | null;
  created_at: string;
  ready_at: string | null;
  exporter_version: string;
}

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

export type MarketSession = "pre_open" | "trading" | "lunch_break" | "closed";

export type KlinePeriod = "day" | "week" | "month";

/** api-v1.md 3.5: indices are fixed to the three A-share benchmarks. */
export interface MarketIndex {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  change_amt: number;
}

export interface NorthboundPoint {
  time: string;
  hgt_yi: number;
  sgt_yi: number;
}

export interface NorthboundLatest {
  hgt_yi: number;
  sgt_yi: number;
}

export interface NorthboundData {
  points: NorthboundPoint[];
  latest: NorthboundLatest | null;
}

/** api-v1.md 3.5: northbound is null when that block failed. */
export interface MarketOverviewData {
  market_session: MarketSession;
  indices: MarketIndex[];
  northbound: NorthboundData | null;
}

export interface MarketIndustryRow {
  rank: number;
  name: string;
  code: string;
  change_pct: number;
  up_count: number;
  down_count: number;
  leader: string;
  leader_change: number;
}

/** api-v1.md 3.6: bottom mirrors top with the opposite sort. */
export interface MarketIndustriesData {
  top: MarketIndustryRow[];
  bottom: MarketIndustryRow[];
  total: number;
}

/** Suspended stocks legitimately report null price and change. */
export interface MarketConstituent {
  code: string;
  name: string;
  price: number | null;
  change_pct: number | null;
}

export interface MarketConstituentsData {
  items: MarketConstituent[];
}

export interface StrongStockItem {
  ticker_code: string;
  name: string;
  reason: string;
  market: MarketId;
  change_pct: number;
  change_amt: number;
  close: number;
  turnover_pct: number;
}

export interface MarketStrongStocksData {
  items: StrongStockItem[];
}

export interface NewsflashItem {
  title: string;
  content: string;
  published_at: string;
}

export interface MarketNewsflashData {
  items: NewsflashItem[];
  untrusted: true;
}

/** api-v1.md 3.2: mirrors the legacy tencent_quote keys exactly. */
export interface StockQuote {
  name: string;
  price: number;
  last_close: number;
  open: number;
  high: number;
  low: number;
  change_pct: number;
  change_amt: number;
  amount_wan: number;
  turnover_pct: number;
  pe_ttm: number;
  pb: number;
  amplitude_pct: number;
  float_mcap_yi: number;
  mcap_yi: number;
  limit_up: number;
}

/** Every field is null when the provider cannot compute it (no zero proxy). */
export interface StockValuation {
  eps_forecast: number | null;
  pe_forward: number | null;
  peg: number | null;
  pe_digestion_years: number | null;
}

export interface SectorBlockItem {
  name: string;
  change_pct: number;
  desc: string;
}

export interface SectorBlocks {
  industry: SectorBlockItem[];
  concept: SectorBlockItem[];
  region: SectorBlockItem[];
}

export interface StockSnapshotUnits {
  price: "元";
  amount: "万元";
  mcap: "亿元";
}

/** A failed block is null while its siblings still render. */
export interface StockSnapshotData {
  quote: StockQuote | null;
  valuation: StockValuation | null;
  sector_blocks: SectorBlocks | null;
  units: StockSnapshotUnits;
}

export interface KlineBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  /** Unavailable amount is null, never 0. */
  amount: number | null;
}

export interface KlineUnits {
  price: "元";
  volume: "手";
  amount: "元";
}

export interface KlineData {
  adjust: "none";
  bars: KlineBar[];
  units: KlineUnits;
}

export interface IntradayPoint {
  time: string;
  price: number;
  volume: number;
  avg_price: number | null;
}

export interface IntradayData {
  date: string;
  points: IntradayPoint[];
  session_gaps: [string, string][];
  units: KlineUnits;
}

export interface StockNewsItem {
  title: string;
  content: string;
  published_at: string;
  source: string;
  url: string;
}

export interface StockNewsData {
  items: StockNewsItem[];
  untrusted: true;
}

export interface FundFlowItem {
  time: string;
  main_net: number;
  small_net: number;
  mid_net: number;
  large_net: number;
  super_net: number;
}

export interface FundFlowData {
  items: FundFlowItem[];
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
