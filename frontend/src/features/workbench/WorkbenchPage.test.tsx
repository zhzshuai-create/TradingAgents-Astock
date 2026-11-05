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

import type { JobSummary } from "../../api/types";
import { relativeTime } from "../../lib/jobStatus";
import { WorkbenchPage } from "./WorkbenchPage";

const ORIGIN = "http://localhost:3000";
const JOBS_URL = `${ORIGIN}/api/v1/jobs`;

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

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
}

function useApi(state: ApiState): void {
  server.use(
    http.get(JOBS_URL, ({ request }) => {
      const url = new URL(request.url);
      if (url.searchParams.get("active") === "true") {
        return HttpResponse.json({ items: state.active, next_cursor: null });
      }
      state.limits.push(url.searchParams.get("limit"));
      return HttpResponse.json({ items: state.recent, next_cursor: null });
    }),
    http.post(JOBS_URL, () => {
      state.posts += 1;
      return HttpResponse.json({}, { status: 201 });
    }),
  );
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(
    [
      { path: "/workbench", element: <WorkbenchPage /> },
      { path: "/jobs", element: <LocationProbe /> },
      { path: "/jobs/:jobId", element: <LocationProbe /> },
    ],
    { initialEntries: ["/workbench"] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("WEB-08 workbench home", () => {
  it("renders the hero, recent jobs and later-phase placeholders", async () => {
    const state: ApiState = { active: [], recent: [], posts: 0, limits: [] };
    useApi(state);
    renderPage();

    expect(screen.getByTestId("page-workbench")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "工作台" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("搜索要分析的股票")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始分析" })).toBeInTheDocument();
    expect(await screen.findByText("报告库将在 P3 开放。")).toBeInTheDocument();
    expect(
      screen.getByText("指数、行业与强势股将在 P4 接入。"),
    ).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: "知道了" }));
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

  it("opens the launcher from the hero search without creating a job", async () => {
    const state: ApiState = { active: [], recent: [], posts: 0, limits: [] };
    useApi(state);
    const router = renderPage();

    const input = screen.getByLabelText("搜索要分析的股票");
    fireEvent.change(input, { target: { value: "600519" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    expect(
      await screen.findByRole("dialog", { name: "分析启动器" }),
    ).toHaveTextContent("已选择股票 600519");
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
