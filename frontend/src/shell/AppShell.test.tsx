import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routes } from "../routes";
import { SIDEBAR_STORAGE_KEY } from "./AppShell";
import { THEME_STORAGE_KEY } from "./useTheme";

vi.mock("../api/jobs", () => ({
  listJobs: vi.fn(async () => ({ items: [], next_cursor: null })),
  getJob: vi.fn(async () => ({
    job_id: "job-1",
    status: "running",
    pending_action: null,
    ticker_code: "600519",
    ticker_name: "贵州茅台",
    analysis_date: "2026-11-05",
    created_at: "2026-11-05T09:03:00+08:00",
    updated_at: "2026-11-05T09:04:00+08:00",
    started_at: "2026-11-05T09:03:01+08:00",
    finished_at: null,
    current_stage: null,
    stages: Array.from({ length: 12 }, (_, index) => ({
      id: `stage-${index + 1}`,
      name: `阶段 ${index + 1}`,
      index: index + 1,
      status: "pending",
      started_at: null,
      finished_at: null,
      duration_ms: null,
    })),
    stats: { model_calls: 0, tokens_in: 0, tokens_out: 0, elapsed_ms: 0 },
    report_id: null,
    error: null,
    config_digest: "hash",
    graph_version: "graph-v1",
    retry_of_job_id: null,
    resume_of_job_id: null,
    resume_from_stage: null,
    allowed_actions: [],
    links: {
      self: "/api/v1/jobs/job-1",
      events: "/api/v1/jobs/job-1/events",
      report: null,
    },
    reconcile_notes: [],
  })),
  getStageReport: vi.fn(),
  createJob: vi.fn(),
  controlJob: vi.fn(),
  retryJob: vi.fn(),
}));

vi.mock("../api/meta", () => ({
  getMetaOptions: vi.fn(async () => ({})),
}));

vi.mock("../api/reports", () => ({
  listReports: vi.fn(async () => ({ items: [], next_cursor: null })),
  getReport: vi.fn(async () => ({
    meta: {
      report_id: "report-1",
      job_id: "job-1",
      ticker_code: "600519",
      ticker_name: "贵州茅台",
      analysis_date: "2026-11-05",
      generated_at: "2026-11-05T09:04:00+08:00",
      generated_at_source: "job_clock",
      origin: "new",
      schema_version: "report-v1",
      content_hash: "hash-1",
      config_digest: "hash",
      data_quality_status: "ok",
      chart_snapshot_status: "frozen",
      retry_of_job_id: null,
      rating: "Overweight",
      signal: "Buy",
      price_target: null,
      stop_reference: null,
      time_horizon: null,
    },
    sections: {
      "sec-decision": {
        id: "sec-decision",
        title: "最终交易决策",
        body: "正文",
      },
    },
  })),
}));

vi.mock("../api/sse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/sse")>();
  return {
    ...actual,
    streamJobEvents: vi.fn(
      (_jobId: string, options: { signal: AbortSignal }) =>
        new Promise<void>((resolve) => {
          options.signal.addEventListener("abort", () => resolve(), {
            once: true,
          });
        }),
    ),
  };
});

vi.mock("../api/market", () => ({
  searchStocks: vi.fn(async () => ({
    schema_version: "market-envelope-v1",
    status: "ok",
    source: "static",
    as_of: null,
    fetched_at: "2026-11-05T09:00:00+08:00",
    is_stale: false,
    stale_reason: null,
    error_code: null,
    error_message: null,
    partial: false,
    failed_blocks: [],
    data: { items: [], truncated: false },
  })),
}));

function renderAt(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

const ROUTES = [
  ["/workbench", "page-workbench", "工作台"],
  ["/market", "page-market", "市场"],
  ["/stocks/600519", "page-stock", "600519 股票工作区"],
  ["/jobs", "page-jobs", "任务"],
  ["/jobs/job-1", "page-job-detail", "贵州茅台"],
  ["/reports", "page-reports", "报告"],
  ["/reports/report-1", "page-report-detail", "贵州茅台"],
  ["/journal", "page-journal", "交易日志"],
  ["/settings", "page-settings", "设置"],
] as const;

describe("WEB-03 routes", () => {
  it.each(ROUTES)("renders %s", async (path, testId, heading) => {
    renderAt(path);
    const region = await screen.findByTestId(testId);
    expect(
      await within(region).findByRole("heading", { level: 1 }),
    ).toHaveTextContent(heading);
  });

  it("redirects the root to the workbench", async () => {
    renderAt("/");
    expect(await screen.findByTestId("page-workbench")).toBeInTheDocument();
  });

  it("renders 404 with two working exits", async () => {
    renderAt("/no-such-page");
    expect(await screen.findByTestId("not-found")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "页面不存在" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "回工作台" })).toHaveAttribute(
      "href",
      "/workbench",
    );
    expect(screen.getByRole("link", { name: "回任务列表" })).toHaveAttribute(
      "href",
      "/jobs",
    );
  });

  it("does not auto redirect away from an unknown route", () => {
    const router = renderAt("/no-such-page");
    expect(router.state.location.pathname).toBe("/no-such-page");
  });
});

describe("WEB-03 active navigation", () => {
  it("marks the sidebar item for a job detail page", () => {
    renderAt("/jobs/job-1");
    const sidebar = screen.getByRole("complementary", { name: "主导航" });
    expect(within(sidebar).getByRole("link", { name: "任务" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      within(sidebar).getByRole("link", { name: "工作台" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("marks the sidebar item for a report detail page", () => {
    renderAt("/reports/report-1");
    const sidebar = screen.getByRole("complementary", { name: "主导航" });
    expect(within(sidebar).getByRole("link", { name: "报告" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("keeps the market item active inside a stock workspace", () => {
    renderAt("/stocks/600519");
    const sidebar = screen.getByRole("complementary", { name: "主导航" });
    expect(within(sidebar).getByRole("link", { name: "市场" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("marks the bottom navigation item", () => {
    renderAt("/reports/report-1");
    const mobileNav = screen.getByTestId("mobile-nav");
    const link = within(mobileNav).getByText("报告").closest("a");
    expect(link).toHaveAttribute("aria-current", "page");
    expect(
      within(mobileNav).getByText("工作台").closest("a"),
    ).not.toHaveAttribute("aria-current");
  });

  it("marks the more button for secondary routes", () => {
    renderAt("/journal");
    const mobileNav = screen.getByTestId("mobile-nav");
    const more = within(mobileNav).getByText("更多").closest("button");
    expect(more).toHaveAttribute("aria-current", "page");
  });
});

describe("WEB-03 invalid ticker", () => {
  it.each(["/stocks/abc", "/stocks/12345", "/stocks/60051a", "/stocks"])(
    "renders 400 for %s",
    async (path) => {
      renderAt(path);
      const region = await screen.findByTestId("invalid-ticker");
      expect(within(region).getByRole("heading", { level: 1 })).toHaveTextContent(
        "没有这只股票",
      );
      expect(within(region).getByLabelText("搜索股票")).toBeInTheDocument();
      expect(within(region).getByRole("link", { name: "回市场" })).toHaveAttribute(
        "href",
        "/market",
      );
    },
  );

  it("opens the launcher from the workbench search box", async () => {
    const router = renderAt("/workbench");
    const input = screen.getByLabelText("搜索股票");
    fireEvent.change(input, {
      target: { value: "600519" },
    });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    const dialog = await screen.findByRole("dialog", { name: "分析启动器" });
    expect(within(dialog).getByText("600519")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/workbench");
    expect(router.state.location.search).toBe("?launch=1&ticker=600519");
  });

  it("opens the stock page from another page's search box", async () => {
    renderAt("/market");
    const input = screen.getByLabelText("搜索股票");
    fireEvent.change(input, {
      target: { value: "600519" },
    });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    expect(await screen.findByTestId("page-stock")).toHaveTextContent(
      "600519 股票工作区",
    );
  });
});

describe("WEB-03 shell controls", () => {
  it("collapses and expands the sidebar, persisting the choice", () => {
    renderAt("/workbench");
    fireEvent.click(screen.getByRole("button", { name: "收起侧栏" }));
    expect(
      screen.getByRole("button", { name: "展开侧栏" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "展开侧栏" }));
    expect(
      screen.getByRole("button", { name: "收起侧栏" }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("toggles the theme and persists it", () => {
    renderAt("/workbench");
    fireEvent.click(
      screen.getAllByRole("button", { name: "切换到深色主题" })[0],
    );
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(
      screen.getAllByRole("button", { name: "切换到浅色主题" }).length,
    ).toBeGreaterThan(0);
  });

  it("opens the more drawer with secondary navigation and legacy entry", () => {
    renderAt("/workbench");
    fireEvent.click(
      within(screen.getByTestId("mobile-nav")).getByText("更多").closest("button")!,
    );
    const drawer = screen.getByRole("dialog", { name: "更多" });
    expect(within(drawer).getByRole("link", { name: "交易日志" })).toHaveAttribute(
      "href",
      "/journal",
    );
    expect(within(drawer).getByRole("link", { name: "设置" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(within(drawer).getByRole("link", { name: "旧版入口" })).toHaveAttribute(
      "href",
      "http://localhost:8501",
    );
  });

  it("closes the more drawer after navigating", async () => {
    renderAt("/workbench");
    fireEvent.click(
      within(screen.getByTestId("mobile-nav")).getByText("更多").closest("button")!,
    );
    const drawer = screen.getByRole("dialog", { name: "更多" });
    fireEvent.click(within(drawer).getByRole("link", { name: "设置" }));
    expect(await screen.findByTestId("page-settings")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "更多" })).not.toBeInTheDocument();
    });
  });
});
