/**
 * One error type for the whole app (error-codes-v1.md).
 *
 * The displayed text is either the server's safe message or a local fallback;
 * response bodies, exception text and stack traces never reach the UI.
 */

export const NETWORK_ERROR_MESSAGE = "网络连接失败，请检查网络后重试";
export const UNKNOWN_ERROR_MESSAGE = "请求失败，请稍后重试";
export const INVALID_RESPONSE_MESSAGE = "服务返回了无法识别的数据";

export const CODE_MESSAGES: Record<string, string> = {
  invalid_request: "请求格式不正确",
  idempotency_key_required: "缺少幂等键",
  method_not_allowed: "不支持该请求方法",
  job_not_found: "没有找到这个任务",
  report_not_found: "没有找到这份报告",
  export_not_found: "没有找到这个导出任务",
  stage_not_found: "没有找到这个阶段",
  sse_cursor_expired: "事件流已过期，请刷新任务页",
  idempotency_mismatch: "该请求与之前的提交不一致",
  active_conflict: "该股票今日已有进行中的分析",
  illegal_transition: "当前状态不支持这个操作",
  resume_fingerprint_mismatch: "配置已变化，无法从检查点继续",
  export_not_ready: "导出尚未完成",
  write_mode_legacy: "当前由旧版发起分析，请到旧版入口开始分析",
  ticker_unresolved: "找不到这只股票",
  ticker_ambiguous: "匹配到多只股票，请选择一只",
  invalid_date: "分析日期不正确",
  config_unknown_key: "不支持的配置项",
  config_invalid_value: "配置取值不支持",
  rate_limited: "操作太频繁，请稍后再试",
  internal_error: "服务暂时不可用",
  not_implemented: "该功能尚未开放",
  upstream_error: "数据服务暂时不可用",
  upstream_timeout: "数据服务响应超时",
  unauthorized: "未授权",
};

/** details keys the contract allows (error-codes-v1.md section 1). */
const DETAIL_KEYS = new Set([
  "job_id",
  "report_id",
  "export_id",
  "active_job_id",
  "field",
  "allowed_values",
  "candidates",
  "from",
  "to",
  "rule",
  "retry_after_ms",
]);

const STATUS_FALLBACK_CODE: Record<number, string> = {
  400: "invalid_request",
  401: "unauthorized",
  410: "sse_cursor_expired",
  429: "rate_limited",
  500: "internal_error",
  502: "upstream_error",
  504: "upstream_timeout",
};

const UNSAFE_MESSAGE = [
  /Traceback \(most recent call last\)/i,
  /\bFile\s+"/,
  /\bline\s+\d+/i,
  /[A-Za-z]:\\/,
  /\/(?:home|Users)\//,
  /\bsk-[A-Za-z0-9]/,
  /\b(?:api_key|authorization|token=)/i,
];

const MAX_MESSAGE_LENGTH = 200;

export interface ApiErrorInit {
  code: string;
  message: string;
  status: number;
  details?: Record<string, unknown>;
  requestId?: string | null;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(init: ApiErrorInit) {
    super(init.message);
    this.name = "ApiError";
    this.code = init.code;
    this.status = init.status;
    this.details = init.details ?? {};
    this.requestId = init.requestId ?? null;
  }

  /** 429 back-off in milliseconds, straight from details.retry_after_ms. */
  get retryAfterMs(): number | null {
    const value = this.details.retry_after_ms;
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
      return null;
    }
    return Math.ceil(value);
  }

  /** Same value in whole seconds, for "请等待 N 秒" copy. */
  get retryAfterSeconds(): number | null {
    const ms = this.retryAfterMs;
    return ms === null ? null : Math.ceil(ms / 1000);
  }

  /** 410 means the page state cannot be patched; rebuild it from GET. */
  get needsFullPageRebuild(): boolean {
    return this.status === 410 || this.code === "sse_cursor_expired";
  }

  get isNetworkError(): boolean {
    return this.code === "network_error";
  }
}

export function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

function safeText(raw: unknown): string | null {
  if (typeof raw !== "string") {
    return null;
  }
  const text = raw.trim();
  if (!text || text.length > MAX_MESSAGE_LENGTH) {
    return null;
  }
  if (UNSAFE_MESSAGE.some((pattern) => pattern.test(text))) {
    return null;
  }
  return text;
}

function pickDetails(raw: unknown): Record<string, unknown> {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return {};
  }
  const details: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (DETAIL_KEYS.has(key)) {
      details[key] = value;
    }
  }
  return details;
}

type ErrorBody = {
  error?: {
    code?: unknown;
    message?: unknown;
    request_id?: unknown;
    details?: unknown;
  };
};

/**
 * Normalises any non-2xx response into ApiError.
 *
 * Order: server message (when safe) -> local copy for the code -> generic copy.
 * A code the client does not know still keeps its machine value; only the text
 * falls back.
 */
export function toApiError(status: number, payload: unknown): ApiError {
  const body = (typeof payload === "object" && payload !== null
    ? payload
    : {}) as ErrorBody;
  const envelope = body.error ?? {};
  const rawCode = typeof envelope.code === "string" ? envelope.code.trim() : "";
  const code = rawCode || STATUS_FALLBACK_CODE[status] || "unknown_error";
  const message =
    safeText(envelope.message) ??
    CODE_MESSAGES[code] ??
    (status >= 500 ? CODE_MESSAGES.internal_error : UNKNOWN_ERROR_MESSAGE);
  return new ApiError({
    code,
    message,
    status,
    details: pickDetails(envelope.details),
    requestId: typeof envelope.request_id === "string" ? envelope.request_id : null,
  });
}

export function networkError(): ApiError {
  return new ApiError({
    code: "network_error",
    message: NETWORK_ERROR_MESSAGE,
    status: 0,
  });
}

export function invalidResponseError(status: number): ApiError {
  return new ApiError({
    code: "invalid_response",
    message: INVALID_RESPONSE_MESSAGE,
    status,
  });
}

/** Copy for a thrown value without ever echoing the value itself. */
export function displayErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return UNKNOWN_ERROR_MESSAGE;
}
