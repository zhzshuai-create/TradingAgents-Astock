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

import type { ReportMeta, ReportSummary } from "../../api/types";
import { RecentReports } from "./RecentReports";

const ORIGIN = "http://localhost:3000";
const REPORTS_URL = `${ORIGIN}/api/v1/reports`;

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function report(id: string, overrides: Partial<ReportMeta> = {}): ReportSummary {
  return {
    meta: {
      report_id: id,
      job_id: "job-1",
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

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname}
      {location.search}
    </output>
  );
}

function renderReports() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(
    [
      { path: "/", element: <RecentReports /> },
      { path: "/reports/:reportId", element: <LocationProbe /> },
      { path: "/stocks/:ticker", element: <LocationProbe /> },
    ],
    { initialEntries: ["/"] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

function serve(items: ReportSummary[], limits: (string | null)[] = []) {
  server.use(
    http.get(REPORTS_URL, ({ request }) => {
      limits.push(new URL(request.url).searchParams.get("limit"));
      return HttpResponse.json({ items, next_cursor: null });
    }),
  );
}

describe("WB-01 recent reports", () => {
  it("shows at most three rows with stock, date, rating and generated time", async () => {
    const limits: (string | null)[] = [];
    serve(
      [
        report("r-1"),
        report("r-2", {
          ticker_code: "600519",
          ticker_name: "贵州茅台",
          rating: "Buy",
        }),
        report("r-3", {
          ticker_code: "300750",
          ticker_name: "宁德时代",
          rating: "Sell",
          generated_at: null,
          generated_at_source: "unknown",
        }),
        report("r-4", { ticker_code: "002594", ticker_name: "比亚迪" }),
      ],
      limits,
    );
    renderReports();

    const rows = await screen.findAllByTestId("recent-report");
    expect(rows).toHaveLength(3);
    expect(limits).toEqual(["3"]);

    expect(within(rows[0]).getByText("钒钛股份")).toBeInTheDocument();
    expect(within(rows[0]).getByText("000629")).toBeInTheDocument();
    expect(within(rows[0]).getByText("2026-11-05")).toBeInTheDocument();
    expect(within(rows[0]).getByText("中性")).toBeInTheDocument();
    expect(within(rows[0]).getByText(/11-05 09:04/)).toBeInTheDocument();

    expect(within(rows[1]).getByText("买入")).toBeInTheDocument();
    expect(within(rows[2]).getByText("卖出")).toBeInTheDocument();
    expect(within(rows[2]).getByText("生成时间未知")).toBeInTheDocument();
    expect(screen.queryByText("比亚迪")).not.toBeInTheDocument();
  });

  it("opens the reader from a report row", async () => {
    serve([report("r-1")]);
    const router = renderReports();

    const row = await screen.findByTestId("recent-report");
    fireEvent.click(within(row).getByText("钒钛股份"));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/reports/r-1"),
    );
  });

  it("derives the recently researched tickers without duplicates", async () => {
    serve([
      report("r-1"),
      report("r-2"),
      report("r-3", {
        ticker_code: "600519",
        ticker_name: "贵州茅台",
      }),
    ]);
    renderReports();

    const chips = await screen.findAllByTestId("recent-report-ticker");
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveTextContent("钒钛股份");
    expect(chips[0]).toHaveAttribute("href", "/stocks/000629");
    expect(chips[1]).toHaveAttribute("href", "/stocks/600519");
  });

  it("shows the empty state and no ticker block without reports", async () => {
    serve([]);
    renderReports();

    expect(await screen.findByText("还没有报告")).toBeInTheDocument();
    expect(screen.queryByTestId("recent-report-tickers")).not.toBeInTheDocument();
  });

  it("shows the error state and refetches once per retry click", async () => {
    let calls = 0;
    server.use(
      http.get(REPORTS_URL, () => {
        calls += 1;
        return HttpResponse.json({ code: "internal_error" }, { status: 500 });
      }),
    );
    renderReports();

    expect(await screen.findByText("数据源请求失败")).toBeInTheDocument();
    expect(calls).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(calls).toBe(2));
  });

  it("collapses on mobile until the toggle is pressed", async () => {
    serve([report("r-1")]);
    renderReports();

    const toggle = await screen.findByText("展开");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "recent-reports-body");

    fireEvent.click(toggle);
    expect(screen.getByText("收起")).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByTestId("recent-report")).toBeInTheDocument();
  });

  it("keeps the All reports link on the list page", async () => {
    serve([report("r-1")]);
    renderReports();

    expect(await screen.findByRole("link", { name: "查看全部" })).toHaveAttribute(
      "href",
      "/reports",
    );
  });
});