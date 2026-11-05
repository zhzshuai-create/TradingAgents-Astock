import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { readFileSync, readdirSync } from "node:fs";
import { join, sep } from "node:path";
import { createElement } from "react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { controlJob, createJob, getJob, listJobs, retryJob } from "./jobs";
import { searchStocks } from "./market";
import { getMetaOptions } from "./meta";
import { ApiError } from "./errors";
import type {
  CreateJobRequest,
  JobDetail,
  JobSummary,
  MarketEnvelope,
  MarketSearchData,
  MetaOptions,
} from "./types";
import {
  META_OPTIONS_STALE_MS,
  invalidateJobQueries,
  jobDetailQuery,
  metaOptionsQuery,
  queryKeys,
} from "../lib/query";
import { IdempotencyIntent } from "../lib/idempotency";

const ORIGIN = "http://localhost:3000";
const API = `${ORIGIN}/api/v1`;

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const JOB_SUMMARY: JobSummary = {
  job_id: "job-1",
  status: "running",
  pending_action: null,
  ticker_code: "000629",
  ticker_name: "钒钛股份",
  analysis_date: "2026-11-05",
  created_at: "2026-11-05T09:00:00+08:00",
  updated_at: "2026-11-05T09:01:00+08:00",
  started_at: "2026-11-05T09:00:01+08:00",
  finished_at: null,
  current_stage: {
    id: "market",
    name: "技术分析",
    index: 1,
    total: 12,
    status: "active",
  },
  stats: { model_calls: 1, tokens_in: 10, tokens_out: 5, elapsed_ms: 1000 },
  report_id: null,
  error: null,
  config_digest: "hash",
  graph_version: "graph-v1",
  retry_of_job_id: null,
  resume_of_job_id: null,
  resume_from_stage: null,
  allowed_actions: ["pause", "cancel"],
  links: {
    self: "/api/v1/jobs/job-1",
    events: "/api/v1/jobs/job-1/events",
    report: null,
  },
};

const JOB_DETAIL: JobDetail = {
  ...JOB_SUMMARY,
  stages: [],
  reconcile_notes: [],
};

const FORM: CreateJobRequest = {
  ticker: "000629",
  analysis_date: "2026-11-05",
  config: {
    llm_profile: "deepseek-default",
    parallel_analysts: true,
    stage_toggles: { policy: true, hot_money: true, lockup: true },
  },
};

const META: MetaOptions = {
  app_version: "0.9.0",
  server_time: "2026-11-05T09:30:00+08:00",
  default_analysis_date: "2026-11-05",
  llm_profiles: [{ id: "deepseek-default", label: "DeepSeek 默认" }],
  stage_toggles: [{ id: "policy", label: "政策分析", default: true }],
  limits: { max_active_jobs: 1, max_date_ahead_days: 0 },
  journal: { available: false, entry_url: "http://127.0.0.1:8502", reason: null },
  contract_version: "api-v1",
};

const SEARCH: MarketEnvelope<MarketSearchData> = {
  schema_version: "market-envelope-v1",
  status: "ok",
  source: "static",
  as_of: "2026-11-05T09:00:00+08:00",
  fetched_at: "2026-11-05T09:00:00+08:00",
  is_stale: false,
  stale_reason: null,
  error_code: null,
  error_message: null,
  partial: false,
  failed_blocks: [],
  data: {
    items: [{ ticker_code: "000629", ticker_name: "钒钛股份", market: "sz" }],
    truncated: false,
  },
};

function errorBody(
  code: string,
  message?: string,
  details?: Record<string, unknown>,
) {
  return {
    error: {
      code,
      ...(message === undefined ? {} : { message }),
      request_id: "req_test",
      ...(details === undefined ? {} : { details }),
    },
  };
}

async function captureError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error("expected the request to reject");
}

// WEB-04 ---------------------------------------------------------------

interface ErrorCase {
  status: number;
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

const ERROR_CASES: ErrorCase[] = [
  { status: 400, code: "invalid_request", message: "请求格式不正确" },
  { status: 401, code: "unauthorized", message: "未授权" },
  { status: 404, code: "job_not_found", message: "没有找到这个任务" },
  {
    status: 409,
    code: "active_conflict",
    message: "该股票今日已有进行中的分析",
    details: { active_job_id: "job-2" },
  },
  { status: 410, code: "sse_cursor_expired", message: "事件流已过期，请刷新任务页" },
  {
    status: 422,
    code: "invalid_date",
    message: "分析日期不正确",
    details: { field: "analysis_date" },
  },
  {
    status: 429,
    code: "rate_limited",
    message: "操作太频繁，请稍后再试",
    details: { retry_after_ms: 3000 },
  },
  { status: 500, code: "internal_error", message: "服务暂时不可用" },
  { status: 502, code: "upstream_error", message: "数据服务暂时不可用" },
];

describe("WEB-04 client error mapping", () => {
  it.each(ERROR_CASES)("maps HTTP $status to $code", async (testCase) => {
    server.use(
      http.get(`${API}/jobs`, () =>
        HttpResponse.json(
          errorBody(testCase.code, testCase.message, "details" in testCase ? testCase.details : undefined),
          { status: testCase.status },
        ),
      ),
    );

    const error = await captureError(listJobs());

    expect(error.code).toBe(testCase.code);
    expect(error.status).toBe(testCase.status);
    expect(error.message).toBe(testCase.message);
    expect(error.details).toEqual("details" in testCase ? testCase.details : {});
  });

  it("exposes 429 back-off and the 410 rebuild flag", async () => {
    server.use(
      http.get(`${API}/jobs`, () =>
        HttpResponse.json(
          errorBody("rate_limited", "操作太频繁，请稍后再试", {
            retry_after_ms: 2500,
          }),
          { status: 429 },
        ),
      ),
    );
    const limited = await captureError(listJobs());
    expect(limited.retryAfterMs).toBe(2500);
    expect(limited.retryAfterSeconds).toBe(3);

    server.use(
      http.get(`${API}/jobs`, () =>
        HttpResponse.json(
          errorBody("sse_cursor_expired", "事件流已过期，请刷新任务页"),
          { status: 410 },
        ),
      ),
    );
    expect((await captureError(listJobs())).needsFullPageRebuild).toBe(true);
  });

  it("never surfaces the raw response body or unsafe fields", async () => {
    server.use(
      http.get(`${API}/jobs`, () =>
        HttpResponse.json(
          {
            error: {
              code: "internal_error",
              message: 'Traceback (most recent call last): File "C:\\app\\main.py"',
              request_id: "req_test",
              details: { raw_body: "secret payload", stack: "line 42" },
            },
          },
          { status: 500 },
        ),
      ),
    );

    const error = await captureError(listJobs());
    const rendered = JSON.stringify({
      code: error.code,
      message: error.message,
      details: error.details,
    });
    expect(error.message).toBe("服务暂时不可用");
    expect(rendered).not.toContain("Traceback");
    expect(rendered).not.toContain("app\\main.py");
    expect(rendered).not.toContain("secret payload");
    expect(error.details).toEqual({});
  });

  it("turns a transport failure into a network error", async () => {
    server.use(http.get(`${API}/jobs`, () => HttpResponse.error()));
    const error = await captureError(listJobs());
    expect(error.code).toBe("network_error");
    expect(error.status).toBe(0);
    expect(error.isNetworkError).toBe(true);
    expect(error.message).toBe("网络连接失败，请检查网络后重试");
  });
});

// Request shape --------------------------------------------------------

describe("request construction", () => {
  it("sends Accept on every call and JSON plus the key on create", async () => {
    const seen: Record<string, string | null> = {};
    server.use(
      http.get(`${API}/meta/options`, ({ request }) => {
        seen.getAccept = request.headers.get("Accept");
        return HttpResponse.json(META);
      }),
      http.post(`${API}/jobs`, async ({ request }) => {
        seen.postAccept = request.headers.get("Accept");
        seen.contentType = request.headers.get("Content-Type");
        seen.key = request.headers.get("Idempotency-Key");
        seen.body = await request.text();
        return HttpResponse.json(JOB_DETAIL, { status: 201 });
      }),
    );

    await getMetaOptions();
    await createJob(FORM, "key-1");

    expect(seen.getAccept).toBe("application/json");
    expect(seen.postAccept).toBe("application/json");
    expect(seen.contentType).toBe("application/json");
    expect(seen.key).toBe("key-1");
    expect(JSON.parse(seen.body ?? "")).toEqual(FORM);
  });

  it("sends the key on retry but not on control actions", async () => {
    const seen: Array<string | null> = [];
    server.use(
      http.post(`${API}/jobs/job-1/retry`, ({ request }) => {
        seen.push(request.headers.get("Idempotency-Key"));
        return HttpResponse.json(JOB_DETAIL, { status: 201 });
      }),
      http.post(`${API}/jobs/job-1/actions`, ({ request }) => {
        seen.push(request.headers.get("Idempotency-Key"));
        return HttpResponse.json(
          {
            job_id: "job-1",
            accepted: true,
            action: "pause",
            accepted_at: "2026-11-05T09:02:00+08:00",
            expected_effect: "at_stage_boundary",
            status: "pause_requested",
          },
          { status: 202 },
        );
      }),
    );

    await retryJob("job-1", "same_config", "key-2");
    await controlJob("job-1", "pause");

    expect(seen).toEqual(["key-2", null]);
  });

  it("builds list filters into the query string", async () => {
    let url = "";
    server.use(
      http.get(`${API}/jobs`, ({ request }) => {
        url = request.url;
        return HttpResponse.json({ items: [], next_cursor: null });
      }),
    );

    await listJobs({
      status: ["running", "failed"],
      ticker: "000629",
      date_from: "2026-10-01",
      date_to: "2026-10-31",
      limit: 20,
      cursor: "abc",
    });
    expect(url).toBe(
      `${API}/jobs?status=running%2Cfailed&ticker=000629&date_from=2026-10-01&date_to=2026-10-31&limit=20&cursor=abc`,
    );

    await listJobs({ active: true, limit: 1 });
    expect(url).toBe(`${API}/jobs?active=true&limit=1`);
  });

  it("encodes ids and search queries", async () => {
    const urls: string[] = [];
    server.use(
      http.get(`${API}/jobs/:jobId`, ({ request }) => {
        urls.push(request.url);
        return HttpResponse.json(JOB_DETAIL);
      }),
      http.get(`${API}/market/search`, ({ request }) => {
        urls.push(request.url);
        return HttpResponse.json(SEARCH);
      }),
    );

    await getJob("job/1");
    const result = await searchStocks("攀钢", 10);

    expect(urls[0]).toBe(`${API}/jobs/job%2F1`);
    expect(urls[1]).toBe(
      `${API}/market/search?q=%E6%94%80%E9%92%A2&limit=10`,
    );
    expect(result.data?.items[0].ticker_code).toBe("000629");
  });
});

// Create job response ------------------------------------------------

describe("create job response envelope", () => {
  it("reports a 201 without an existing job", async () => {
    server.use(
      http.post(`${API}/jobs`, () =>
        HttpResponse.json(JOB_DETAIL, { status: 201 }),
      ),
    );

    const result = await createJob(FORM, "key-201");

    expect(result.status).toBe(201);
    expect(result.existingJobId).toBeNull();
    expect(result.replayed).toBe(false);
    expect(result.job.job_id).toBe("job-1");
  });

  it("reads the existing job and replay headers from a 200", async () => {
    server.use(
      http.post(`${API}/jobs`, () =>
        HttpResponse.json(JOB_DETAIL, {
          status: 200,
          headers: {
            "X-Existing-Job": "job-9",
            "Idempotency-Replayed": "1",
          },
        }),
      ),
    );

    const result = await createJob(FORM, "key-200");

    expect(result.status).toBe(200);
    expect(result.existingJobId).toBe("job-9");
    expect(result.replayed).toBe(true);
  });
});

// WEB-05 ---------------------------------------------------------------

describe("WEB-05 idempotency and invalidation", () => {
  it("reuses the key across a network retry and changes it after edits", async () => {
    const keys: Array<string | null> = [];
    let calls = 0;
    server.use(
      http.post(`${API}/jobs`, ({ request }) => {
        keys.push(request.headers.get("Idempotency-Key"));
        calls += 1;
        if (calls === 1) {
          return HttpResponse.error();
        }
        return HttpResponse.json(JOB_DETAIL, { status: 201 });
      }),
    );

    let generated = 0;
    const intent = new IdempotencyIntent(() => `key-${++generated}`);

    await expect(createJob(FORM, intent.keyFor(FORM))).rejects.toMatchObject({
      code: "network_error",
    });
    await createJob(FORM, intent.keyFor(FORM));
    expect(keys).toEqual(["key-1", "key-1"]);

    const edited: CreateJobRequest = {
      ...FORM,
      config: { ...FORM.config, parallel_analysts: false },
    };
    await createJob(edited, intent.keyFor(edited));
    expect(keys[2]).toBe("key-2");

    // Re-submitting the original form is a new intent after the edit.
    await createJob(FORM, intent.keyFor(FORM));
    expect(keys[3]).toBe("key-3");
  });

  it("keeps one key for identical forms even when key order changes", () => {
    let generated = 0;
    const intent = new IdempotencyIntent(() => `key-${++generated}`);
    expect(intent.keyFor({ ticker: "000629", analysis_date: "2026-11-05" })).toBe(
      "key-1",
    );
    expect(intent.keyFor({ analysis_date: "2026-11-05", ticker: "000629" })).toBe(
      "key-1",
    );
    intent.reset();
    expect(intent.keyFor({ ticker: "000629" })).toBe("key-2");
  });

  it("invalidates job list and detail after a control action", async () => {
    const client = new QueryClient();
    client.setQueryData(queryKeys.job("job-1"), JOB_DETAIL);
    client.setQueryData(queryKeys.jobs({ limit: 3 }), {
      items: [JOB_SUMMARY],
      next_cursor: null,
    });
    client.setQueryData(queryKeys.metaOptions, META);

    await invalidateJobQueries(client, "job-1");

    expect(client.getQueryState(queryKeys.job("job-1"))?.isInvalidated).toBe(true);
    expect(
      client.getQueryState(queryKeys.jobs({ limit: 3 }))?.isInvalidated,
    ).toBe(true);
    expect(
      client.getQueryState(queryKeys.metaOptions)?.isInvalidated,
    ).toBe(false);
  });

  it("uses the fixed keys and cache windows", () => {
    expect(queryKeys.jobs({ ticker: "000629" })).toEqual([
      "jobs",
      { ticker: "000629" },
    ]);
    expect(queryKeys.job("job-1")).toEqual(["job", "job-1"]);
    expect(queryKeys.metaOptions).toEqual(["meta", "options"]);
    expect(queryKeys.marketSearch("攀钢")).toEqual(["market", "search", "攀钢"]);

    expect(metaOptionsQuery.queryKey).toEqual(["meta", "options"]);
    expect(META_OPTIONS_STALE_MS).toBe(60_000);
    expect(metaOptionsQuery.staleTime).toBe(60_000);
    expect(jobDetailQuery("job-1").staleTime).toBe(0);
  });
});

// URL ownership ---------------------------------------------------------

describe("URL ownership", () => {
  it("keeps fetch and raw /api/v1 paths inside src/api", () => {
    const src = join(process.cwd(), "src");
    const files = readdirSync(src, { recursive: true })
      .map(String)
      .filter((name) => /\.(?:ts|tsx)$/.test(name))
      .filter((name) => !/\.test\.(?:ts|tsx)$/.test(name));

    const offenders: string[] = [];
    for (const name of files) {
      const rel = name.split(sep).join("/");
      const text = readFileSync(join(src, name), "utf8");
      if (rel !== "api/client.ts" && /\bfetch\s*\(/.test(text)) {
        offenders.push(`${rel} calls fetch`);
      }
      if (!rel.startsWith("api/") && text.includes("/api/v1")) {
        offenders.push(`${rel} hard-codes an API path`);
      }
    }

    expect(offenders).toEqual([]);
  });
});

// WEB-06 ---------------------------------------------------------------

const NULLABLE_SUMMARY: JobSummary = {
  ...JOB_SUMMARY,
  status: "queued",
  ticker_name: null,
  started_at: null,
  current_stage: null,
  report_id: null,
  error: null,
  retry_of_job_id: null,
  resume_of_job_id: null,
  resume_from_stage: null,
  allowed_actions: [],
  links: {
    self: "/api/v1/jobs/job-1",
    events: "/api/v1/jobs/job-1/events",
    report: null,
  },
  reconcile_notes: undefined,
};

function JobRow({ job }: { job: JobSummary }) {
  return createElement(
    "p",
    { "data-testid": "job-row" },
    `${job.ticker_name ?? job.ticker_code} · ${
      job.current_stage?.name ?? "未开始"
    } · ${job.report_id ?? "无报告"} · ${job.error?.message ?? "无错误"}`,
  );
}

describe("WEB-06 nullable fields", () => {
  it("renders a job whose optional fields are all null", async () => {
    server.use(
      http.get(`${API}/jobs`, () =>
        HttpResponse.json({ items: [NULLABLE_SUMMARY], next_cursor: null }),
      ),
    );

    const page = await listJobs();
    expect(page.next_cursor).toBeNull();
    expect(page.items[0].ticker_name).toBeNull();

    render(createElement(JobRow, { job: page.items[0] }));
    expect(screen.getByTestId("job-row")).toHaveTextContent(
      "000629 · 未开始 · 无报告 · 无错误",
    );
  });

  it("renders a job with a name, active stage and error", () => {
    render(
      createElement(JobRow, {
        job: {
          ...NULLABLE_SUMMARY,
          status: "failed",
          ticker_name: "钒钛股份",
          current_stage: {
            id: "news",
            name: "新闻舆情",
            index: 3,
            total: 12,
            status: "active",
          },
          report_id: "report-1",
          error: { code: "upstream_timeout", message: "数据服务响应超时" },
        },
      }),
    );
    expect(screen.getByTestId("job-row")).toHaveTextContent(
      "钒钛股份 · 新闻舆情 · report-1 · 数据服务响应超时",
    );
  });

  it("tolerates a meta response with a null journal reason", async () => {
    server.use(
      http.get(`${API}/meta/options`, () =>
        HttpResponse.json({ ...META, journal: { ...META.journal, reason: null } }),
      ),
    );
    const options = await getMetaOptions();
    expect(options.journal.reason).toBeNull();
    expect(options.llm_profiles[0].label).toBe("DeepSeek 默认");
  });

  it("tolerates an error response without details", async () => {
    server.use(
      http.get(`${API}/jobs`, () =>
        HttpResponse.json(
          { error: { code: "active_conflict", message: "冲突" } },
          { status: 409 },
        ),
      ),
    );
    const error = await captureError(listJobs());
    expect(error.details).toEqual({});
    expect(error.message).toBe("冲突");
  });
});
