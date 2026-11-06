import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import {
  createMemoryRouter,
  RouterProvider,
  useLocation,
} from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import type {
  JobSummary,
  MarketEnvelope,
  MarketIndustriesData,
  MarketOverviewData,
  MarketStrongStocksData,
  MetaOptions,
  ReportMeta,
  ReportSummary,
} from "../../api/types";
import { relativeTime } from "../../lib/jobStatus";
import { WorkbenchPage } from "./WorkbenchPage";

const ORIGIN = "http://localhost:3000";
const JOBS_URL = `${ORIGIN}/api/v1/jobs`;
const META_URL = `${ORIGIN}/api/v1/meta/options`;
const SEARCH_URL = `${ORIGIN}/api/v1/market/search`;
const REPORTS_URL = `${ORIGIN}/api/v1/reports`;
const OVERVIEW_URL = `${ORIGIN}/api/v1/market/overview`;
const INDUSTRIES_URL = `${ORIGIN}/api/v1/market/industries`;
const STRONG_URL = `${ORIGIN}/api/v1/market/strong-stocks`;

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

const SEARCH_EMPTY = {
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
  data: { items: [], truncated: false },
};

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function envelope<T>(
  data: T,
  overrides: Partial<MarketEnvelope<T>> = {},
): MarketEnvelope<T> {
  return {
    schema_version: "market-envelope-v1",
    status: "ok",
    source: "mixed",
    as_of: "2026-11-05T09:30:00+08:00",
    fetched_at: "2026-11-05T09:30:00+08:00",
    is_stale: false,
    stale_reason: null,
    error_code: null,
    error_message: null,
    partial: false,
    failed_blocks: [],
    data,
    ...overrides,
  };
}

const OVERVIEW = envelope<MarketOverviewData>({
  market_session: "closed",
  indices: [
    { code: "000001", name: "上证指数", price: 4012.34, change_pct: 0.42, change_amt: 16.8 },
    { code: "399001", name: "深证成指", price: 13210.5, change_pct: -0.31, change_amt: -41.2 },
    { code: "399006", name: "创业板指", price: 2810.2, change_pct: 1.12, change_amt: 31.1 },
  ],
  northbound: null,
});

const INDUSTRIES = envelope<MarketIndustriesData>({
  top: [
    { rank: 1, name: "半导体", code: "BK0475", change_pct: 3.21, up_count: 40, down_count: 2, leader: "中芯国际", leader_change: 8.1 },
    { rank: 2, name: "算力", code: "BK1036", change_pct: 2.84, up_count: 30, down_count: 3, leader: "中际旭创", leader_change: 7.2 },
    { rank: 3, name: "稀土", code: "BK0578", change_pct: 2.11, up_count: 20, down_count: 4, leader: "北方稀土", leader_change: 5.4 },
  ],
  bottom: [],
  total: 30,
});

const STRONG = envelope<MarketStrongStocksData>({
  items: [
    { ticker_code: "300750", name: "宁德时代", reason: "储能", market: "sz", change_pct: 6.2, change_amt: 11.1, close: 190.2, turnover_pct: 1.2 },
    { ticker_code: "600519", name: "贵州茅台", reason: "白酒", market: "sh", change_pct: 4.1, change_amt: 60.2, close: 1520.0, turnover_pct: 0.6 },
    { ticker_code: "300308", name: "中际旭创", reason: "算力", market: "sz", change_pct: 3.8, change_amt: 5.4, close: 148.3, turnover_pct: 2.1 },
  ],
});

function report(id: string, overrides: Partial<ReportMeta> = {}): ReportSummary {
  return {
    meta: {
      report_id: id,
      job_id: "job-3",
      ticker_code: "000629",
      ticker_name: "钒钛股份",
      analysis_date: "2026-11-05",
      generated_at: "2026-11-05T09:04:00+08:00",
      generated_at_source: "job_clock",
      origin: "new",
      schema_version: "report-v1",
      content_hash: `hash-${id}`,
      config_digest: null,
      data_quality_status: "ok",
      chart_snapshot_status: "frozen",
      retry_of_job_id: null,
      rating: "Hold",
      signal: "Hold",
      ...overrides,
    },
    summary_available: true,
  };
}

function job(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    job_id: "job-3",
    status: "running",
    pending_action: null,
    ticker_code: "000629",
    ticker_name: "钒钛股份",
    analysis_date: "2026-11-05",
    created_at: "2026-11-05T09:03:00+08:00",
    updated_at: "2026-11-05T09:04:00+08:00",
    started_at: "2026-11-05T09:03:01+08:00",
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
      self: "/api/v1/jobs/job-3",
      events: "/api/v1/jobs/job-3/events",
      report: null,
    },
    ...overrides,
  };
}

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname}
      {location.search}
    </output>
  );
}

interface ApiState {
  active: JobSummary[];
  recent: JobSummary[];
  posts: number;
  limits: (string | null)[];
  reports?: ReportSummary[];
  overview?: MarketEnvelope<MarketOverviewData>;
  industries?: MarketEnvelope<MarketIndustriesData>;
  strong?: MarketEnvelope<MarketStrongStocksData>;
  requests?: string[];
}

function useApi(state: ApiState): void {
  server.use(
    http.get(JOBS_URL, ({ request }) => {
      state.requests?.push(request.url);
      const url = new URL(request.url);
      if (url.searchParams.get("active") === "true") {
        return HttpResponse.json({ items: state.active, next_cursor: null });
      }
      state.limits.push(url.searchParams.get("limit"));
      return HttpResponse.json({ items: state.recent, next_cursor: null });
    }),
    http.get(REPORTS_URL, ({ request }) => {
      state.requests?.push(request.url);
      return HttpResponse.json({
        items: state.reports ?? [],
        next_cursor: null,
      });
    }),
    http.get(OVERVIEW_URL, ({ request }) => {
      state.requests?.push(request.url);
      return HttpResponse.json(state.overview ?? OVERVIEW);
    }),
    http.get(INDUSTRIES_URL, ({ request }) => {
      state.requests?.push(request.url);
      return HttpResponse.json(state.industries ?? INDUSTRIES);
    }),
    http.get(STRONG_URL, ({ request }) => {
      state.requests?.push(request.url);
      return HttpResponse.json(state.strong ?? STRONG);
    }),
    http.get(META_URL, () => HttpResponse.json(META)),
    http.get(SEARCH_URL, () => HttpResponse.json(SEARCH_EMPTY)),
    http.post(JOBS_URL, () => {
      state.posts += 1;
      return HttpResponse.json({}, { status: 201 });
    }),
  );
}

function renderPage(entry = "/workbench") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(
    [
      { path: "/workbench", element: <WorkbenchPage /> },
      { path: "/jobs", element: <LocationProbe /> },
      { path: "/jobs/:jobId", element: <LocationProbe /> },
    ],
    { initialEntries: [entry] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("WEB-08 workbench home", () => {
  it("renders the hero, recent jobs, recent reports and market summary", async () => {
    const state: ApiState = {
      active: [],
      recent: [],
      posts: 0,
      limits: [],
      reports: [report("r-1"), report("r-2", { ticker_code: "600519", ticker_name: "贵州茅台", rating: "Buy" })],
    };
    useApi(state);
    renderPage();

    expect(screen.getByTestId("page-workbench")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "工作台" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("搜索要分析的股票")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始分析" })).toBeInTheDocument();

    const rows = await screen.findAllByTestId("recent-report");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("钒钛股份")).toBeInTheDocument();
    expect(within(rows[0]).getByText("2026-11-05")).toBeInTheDocument();
    expect(within(rows[0]).getByText("中性")).toBeInTheDocument();
    expect(within(rows[0]).getByText(/11-05 09:04/)).toBeInTheDocument();

    expect(await screen.findAllByTestId("summary-index")).toHaveLength(3);
    expect(screen.getByText("上证指数")).toBeInTheDocument();
    expect(screen.getByText("半导体")).toBeInTheDocument();
    expect(screen.getAllByTestId("summary-strong-stock")[0]).toHaveAttribute(
      "href",
      "/stocks/300750",
    );
    expect(screen.getByRole("link", { name: "查看市场" })).toHaveAttribute(
      "href",
      "/market",
    );
    expect(screen.queryByText(/将在 P3|将在 P4|报告库将在/)).not.toBeInTheDocument();
  });

  it("opens the workbench with read-only GET requests only", async () => {
    const state: ApiState = {
      active: [],
      recent: [job()],
      posts: 0,
      limits: [],
      reports: [report("r-1")],
      requests: [],
    };
    useApi(state);
    renderPage();

    await screen.findByTestId("recent-report");
    await screen.findAllByTestId("summary-index");
    await waitFor(() => expect(state.requests).not.toHaveLength(0));

    const allowed = [
      "/api/v1/jobs",
      "/api/v1/reports",
      "/api/v1/market/overview",
      "/api/v1/market/industries",
      "/api/v1/market/strong-stocks",
    ];
    const paths = (state.requests ?? []).map((url) => new URL(url).pathname);
    expect(paths.filter((path) => !allowed.includes(path))).toEqual([]);
    expect(paths).toContain("/api/v1/reports");
    expect(paths).toContain("/api/v1/market/overview");
    expect(state.posts).toBe(0);
  });

  it("leaves no blank block when no job is active", async () => {
    const state: ApiState = { active: [], recent: [job()], posts: 0, limits: [] };
    useApi(state);
    renderPage();

    await screen.findByTestId("recent-job");
    await waitFor(() =>
      expect(screen.queryByTestId("active-job-bar")).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("workbench-primary")).toBeVisible();
  });

  it("shows the active job as a clickable card", async () => {
    const state: ApiState = {
      active: [
        job(),
        job({ job_id: "job-2", created_at: "2026-11-05T09:02:00+08:00" }),
      ],
      recent: [job()],
      posts: 0,
      limits: [],
    };
    useApi(state);
    const router = renderPage();

    const card = await screen.findByTestId("workbench-active-card");
    expect(within(card).getByText("钒钛股份")).toBeInTheDocument();
    expect(within(card).getByText("技术分析 1/12")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "还有 1 个" })).toHaveAttribute(
      "href",
      "/jobs?active=true",
    );

    fireEvent.click(within(card).getByText("查看"));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/jobs/job-3"),
    );
  });

  it("asks the recent list for exactly three rows", async () => {
    const state: ApiState = { active: [], recent: [job()], posts: 0, limits: [] };
    useApi(state);
    renderPage();

    await screen.findByTestId("recent-job");
    await waitFor(() => expect(state.limits).toContain("3"));
  });

  it("offers the first analysis from the empty state without creating", async () => {
    const state: ApiState = { active: [], recent: [], posts: 0, limits: [] };
    useApi(state);
    const router = renderPage();

    fireEvent.click(
      await screen.findByRole("button", { name: "开始第一次分析" }),
    );
    expect(
      await screen.findByRole("dialog", { name: "分析启动器" }),
    ).toBeInTheDocument();
    expect(router.state.location.search).toBe("?launch=1");
    expect(await screen.findByLabelText("分析日期")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(router.state.location.search).toBe("");
    expect(state.posts).toBe(0);
  });

  it("shows error and reanalyze actions for a failed job", async () => {
    const state: ApiState = {
      active: [],
      recent: [
        job({
          status: "failed",
          current_stage: null,
          error: { code: "model_error", message: "模型调用失败" },
        }),
      ],
      posts: 0,
      limits: [],
    };
    useApi(state);
    renderPage();

    const row = await screen.findByTestId("recent-job");
    expect(within(row).getByText("失败")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "查看错误" })).toHaveAttribute(
      "href",
      "/jobs/job-3",
    );
    expect(within(row).getByRole("link", { name: "重新分析" })).toHaveAttribute(
      "href",
      "/workbench?launch=1&ticker=000629",
    );
  });

  it("labels an interrupted job as waiting for a person, never running", async () => {
    const state: ApiState = {
      active: [],
      recent: [job({ status: "interrupted" })],
      posts: 0,
      limits: [],
    };
    useApi(state);
    renderPage();

    const row = await screen.findByTestId("recent-job");
    expect(within(row).getByText("等待人工处理")).toBeInTheDocument();
    expect(within(row).queryByText("进行中")).not.toBeInTheDocument();
    expect(within(row).queryByText("运行中")).not.toBeInTheDocument();
  });

  it("prefills the ticker and date from a legacy report link", async () => {
    const state: ApiState = { active: [], recent: [], posts: 0, limits: [] };
    useApi(state);
    renderPage("/workbench?launch=1&ticker=000629&date=2026-10-20");

    const date = (await screen.findByLabelText("分析日期")) as HTMLInputElement;
    await waitFor(() => expect(date.value).toBe("2026-10-20"));
    expect(screen.getByText("000629")).toBeInTheDocument();
    expect(state.posts).toBe(0);
  });

  it("ignores a malformed date link and keeps the server default", async () => {
    const state: ApiState = { active: [], recent: [], posts: 0, limits: [] };
    useApi(state);
    renderPage("/workbench?launch=1&ticker=000629&date=not-a-date");

    const date = (await screen.findByLabelText("分析日期")) as HTMLInputElement;
    await waitFor(() => expect(date.value).toBe("2026-11-05"));
  });

  it("opens the launcher from the hero search without creating a job", async () => {
    const state: ApiState = { active: [], recent: [], posts: 0, limits: [] };
    useApi(state);
    const router = renderPage();

    const input = screen.getByLabelText("搜索要分析的股票");
    fireEvent.change(input, { target: { value: "600519" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(
      await screen.findByRole("dialog", { name: "分析启动器" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("600519")).toBeInTheDocument();
    expect(router.state.location.search).toBe("?launch=1&ticker=600519");
    expect(state.posts).toBe(0);
  });

  it("navigates a recent row to the job detail", async () => {
    const state: ApiState = { active: [], recent: [job()], posts: 0, limits: [] };
    useApi(state);
    const router = renderPage();

    fireEvent.click(await screen.findByText("钒钛股份"));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/jobs/job-3"),
    );
  });
});

describe("WEB-08 relative time", () => {
  const now = new Date("2026-11-05T11:00:00+08:00").getTime();

  it.each([
    ["2026-11-05T10:59:30+08:00", "刚刚"],
    ["2026-11-05T10:45:00+08:00", "15 分钟前"],
    ["2026-11-05T09:00:00+08:00", "2 小时前"],
    ["2026-11-03T11:00:00+08:00", "2 天前"],
  ])("renders %s as %s", (iso, expected) => {
    expect(relativeTime(iso, now)).toBe(expected);
  });

  it("drops an unparsable timestamp instead of showing NaN", () => {
    expect(relativeTime("not-a-date", now)).toBe("");
  });
});
