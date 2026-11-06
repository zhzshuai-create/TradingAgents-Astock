import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import {
  createMemoryRouter,
  RouterProvider,
  useLocation,
} from "react-router-dom";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import type {
  ReportListResponse,
  ReportSummary,
  ReportRating,
} from "../../api/types";
import { ReportListPage } from "./ReportListPage";
import { REPORT_RATING_ORDER } from "./listParams";

const ORIGIN = "http://localhost:3000";
const REPORTS_URL = `${ORIGIN}/api/v1/reports`;
const YEAR = new Date().getFullYear();

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});
afterAll(() => server.close());

let requests: URLSearchParams[] = [];
beforeEach(() => {
  requests = [];
  sessionStorage.clear();
  document.getElementById("main-content")?.remove();
});

function report(
  overrides: Partial<ReportSummary["meta"]> = {},
): ReportSummary {
  return {
    meta: {
      report_id: "r-new",
      job_id: "job-1",
      ticker_code: "600519",
      ticker_name: "贵州茅台",
      analysis_date: "2026-10-28",
      generated_at: `${YEAR}-10-28T11:41:00`,
      generated_at_source: "job_clock",
      origin: "new",
      schema_version: "report-v1",
      content_hash: "hash-1",
      config_digest: "cfg-1",
      data_quality_status: "ok",
      chart_snapshot_status: "frozen",
      retry_of_job_id: null,
      rating: "Overweight",
      signal: "Buy",
      ...overrides,
    },
    summary_available: true,
  };
}

function legacyReport(
  overrides: Partial<ReportSummary["meta"]> = {},
): ReportSummary {
  return report({
    report_id: "r-legacy",
    job_id: null,
    ticker_code: "601318",
    ticker_name: "中国平安",
    analysis_date: "2026-10-20",
    generated_at: null,
    generated_at_source: "unknown",
    origin: "legacy_import",
    data_quality_status: "absent",
    chart_snapshot_status: "none",
    rating: "Sell",
    signal: "Sell",
    ...overrides,
  });
}

function page(
  items: ReportSummary[],
  next: string | null = null,
): ReportListResponse {
  return { items, next_cursor: next };
}

interface StubResult {
  body: unknown;
  status?: number;
}

function serveReports(handler: (params: URLSearchParams) => StubResult): void {
  server.use(
    http.get(REPORTS_URL, ({ request }) => {
      const params = new URL(request.url).searchParams;
      requests.push(params);
      const result = handler(params);
      return HttpResponse.json(
        result.body as Parameters<typeof HttpResponse.json>[0],
        { status: result.status ?? 200 },
      );
    }),
  );
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

function renderPage(initialEntry: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: "/reports", element: <ReportListPage /> },
      { path: "/reports/:reportId", element: <LocationProbe /> },
      { path: "/workbench", element: <LocationProbe /> },
    ],
    { initialEntries: [initialEntry] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

function mountScrollContainer(): HTMLElement {
  // jsdom has no layout, so scrollTop needs a writable stand-in.
  const main = document.createElement("div");
  main.id = "main-content";
  let scrollTop = 0;
  Object.defineProperty(main, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (value: number) => {
      scrollTop = value;
    },
  });
  document.body.appendChild(main);
  return main;
}

function ratingSubsetWithout(rating: ReportRating): string {
  return REPORT_RATING_ORDER.filter((item) => item !== rating).join(",");
}

describe("LIB-01 report list filters", () => {
  it("asks for the first page with limit 20 and no filters by default", async () => {
    serveReports(() => ({ body: page([report()]) }));
    renderPage("/reports");

    await screen.findByTestId("report-row");
    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    const params = requests[0];
    expect(params.get("limit")).toBe("20");
    expect(params.has("ticker")).toBe(false);
    expect(params.has("date_from")).toBe(false);
    expect(params.has("date_to")).toBe(false);
    expect(params.has("rating")).toBe(false);
  });

  it("rebuilds every control and the request from a deep link", async () => {
    serveReports(() => ({ body: page([report()]) }));
    const router = renderPage(
      "/reports?ticker=000629&date_from=2026-10-01&date_to=2026-10-31&rating=Buy,Sell",
    );

    await screen.findByTestId("report-row");
    await waitFor(() =>
      expect(router.state.location.search).toBe(
        "?ticker=000629&date_from=2026-10-01&date_to=2026-10-31&rating=Buy,Sell",
      ),
    );
    const params = requests[0];
    expect(params.get("ticker")).toBe("000629");
    expect(params.get("date_from")).toBe("2026-10-01");
    expect(params.get("date_to")).toBe("2026-10-31");
    expect(params.get("rating")).toBe("Buy,Sell");
    expect(screen.getByLabelText("股票代码")).toHaveValue("000629");
    expect(screen.getByLabelText("开始日期")).toHaveValue("2026-10-01");
    expect(screen.getByLabelText("结束日期")).toHaveValue("2026-10-31");
    expect(screen.getByRole("checkbox", { name: "买入" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "卖出" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "中性" })).not.toBeChecked();
  });

  it("writes a comma list for a rating subset and omits it when all return", async () => {
    serveReports(() => ({ body: page([report()]) }));
    const router = renderPage("/reports");

    await screen.findByTestId("report-row");
    fireEvent.click(screen.getByRole("checkbox", { name: "买入" }));

    const expected = ratingSubsetWithout("Buy");
    await waitFor(() =>
      expect(requests.at(-1)?.get("rating")).toBe(expected),
    );
    await waitFor(() =>
      expect(router.state.location.search).toBe(
        `?rating=${encodeURIComponent(expected)}`,
      ),
    );

    const before = requests.length;
    fireEvent.click(screen.getByRole("checkbox", { name: "买入" }));
    await waitFor(() => expect(requests.length).toBeGreaterThan(before));
    expect(requests.at(-1)?.has("rating")).toBe(false);
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });

  it("refuses to clear the last selected rating", async () => {
    serveReports(() => ({ body: page([report()]) }));
    const router = renderPage("/reports?rating=Buy");

    await screen.findByTestId("report-row");
    const buy = screen.getByRole("checkbox", { name: "买入" });
    fireEvent.click(buy);

    await waitFor(() =>
      expect(router.state.location.search).toBe("?rating=Buy"),
    );
    expect(buy).toBeChecked();
  });

  it("resets filters, fields and the request together", async () => {
    serveReports(() => ({ body: page([report()]) }));
    const router = renderPage(
      "/reports?ticker=000629&date_from=2026-10-01&rating=Buy",
    );

    await screen.findByTestId("report-row");
    fireEvent.click(screen.getByRole("button", { name: "重置" }));

    await waitFor(() => expect(router.state.location.search).toBe(""));
    await waitFor(() => expect(requests.at(-1)?.has("ticker")).toBe(false));
    expect(requests.at(-1)?.has("rating")).toBe(false);
    expect(requests.at(-1)?.has("date_from")).toBe(false);
    expect(screen.getByLabelText("股票代码")).toHaveValue("");
  });

  it("drops malformed deep-link values instead of sending them", async () => {
    serveReports(() => ({ body: page([report()]) }));
    const router = renderPage(
      "/reports?ticker=12&date_from=2026-02-30&date_to=2026-01-01&rating=bogus,Hold",
    );

    await screen.findByTestId("report-row");
    await waitFor(() =>
      expect(router.state.location.search).toBe(
        "?date_to=2026-01-01&rating=Hold",
      ),
    );
    const params = requests[0];
    expect(params.has("ticker")).toBe(false);
    expect(params.has("date_from")).toBe(false);
    // The invalid start date is dropped; the valid end date can stand alone.
    expect(params.get("date_to")).toBe("2026-01-01");
    expect(params.get("rating")).toBe("Hold");
  });
});

describe("LIB-02 pagination and return context", () => {
  it("loads more with the server cursor and resets it when a filter changes", async () => {
    serveReports((params) => {
      if (params.get("cursor") === "c2") {
        return { body: page([legacyReport()]) };
      }
      return { body: page([report()], "c2") };
    });
    const router = renderPage("/reports");

    await screen.findByTestId("report-row");
    const before = requests.length;
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }));

    await waitFor(() =>
      expect(screen.getAllByTestId("report-row")).toHaveLength(2),
    );
    await waitFor(() =>
      expect(router.state.location.search).toBe("?cursor=c2"),
    );
    expect(requests.length).toBeGreaterThan(before);
    expect(requests.at(-1)?.get("cursor")).toBe("c2");

    fireEvent.click(screen.getByRole("checkbox", { name: "买入" }));
    await waitFor(() => {
      const params = requests.at(-1);
      expect(params?.has("cursor")).toBe(false);
      expect(params?.has("rating")).toBe(true);
    });
    expect(router.state.location.search).not.toContain("cursor=");
  });

  it("keeps filters and every loaded page after visiting a report", async () => {
    const first = Array.from({ length: 20 }, (_, index) =>
      report({ report_id: `r-${index}` }),
    );
    serveReports((params) =>
      params.get("cursor") === "c1"
        ? { body: page([report({ report_id: "r-20" })]) }
        : { body: page(first, "c1") },
    );
    const router = renderPage("/reports?rating=Buy&ticker=000629");

    await waitFor(() =>
      expect(screen.getAllByTestId("report-row")).toHaveLength(20),
    );
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }));
    await waitFor(() =>
      expect(screen.getAllByTestId("report-row")).toHaveLength(21),
    );

    await router.navigate("/reports/r-0");
    await screen.findByTestId("location");
    await router.navigate(-1);

    await waitFor(() =>
      expect(screen.getAllByTestId("report-row")).toHaveLength(21),
    );
    expect(router.state.location.search).toContain("rating=Buy");
    expect(router.state.location.search).toContain("ticker=000629");
    expect(router.state.location.search).toContain("cursor=c1");
    // The stale refetch must rebuild both pages, not collapse onto the cursor.
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(screen.getAllByTestId("report-row")).toHaveLength(21);
  });

  it("rebuilds every loaded page from a cursor deep link", async () => {
    const first = Array.from({ length: 20 }, (_, index) =>
      report({ report_id: `r-${index}` }),
    );
    serveReports((params) =>
      params.get("cursor") === "c1"
        ? { body: page([report({ report_id: "r-20" })]) }
        : { body: page(first, "c1") },
    );
    renderPage("/reports?rating=Buy&cursor=c1");

    await waitFor(() =>
      expect(screen.getAllByTestId("report-row")).toHaveLength(21),
    );
    expect(requests.map((params) => params.get("cursor"))).toEqual([
      null,
      "c1",
    ]);
  });

  it("restores the saved scroll position once and clears the key", async () => {
    serveReports(() => ({ body: page([report()]) }));
    const main = mountScrollContainer();
    sessionStorage.setItem("ta:reports-scroll:/reports?rating=Buy", "900");

    renderPage("/reports?rating=Buy");

    await screen.findByTestId("report-row");
    await waitFor(() => expect(main.scrollTop).toBe(900));
    expect(
      sessionStorage.getItem("ta:reports-scroll:/reports?rating=Buy"),
    ).toBeNull();
  });

  it("saves the scroll position when a navigation starts", async () => {
    serveReports(() => ({ body: page([report()]) }));
    const main = mountScrollContainer();
    const router = renderPage("/reports");

    await screen.findByTestId("report-row");
    main.scrollTop = 640;
    document.body.click();
    expect(sessionStorage.getItem("ta:reports-scroll:/reports")).toBe("640");

    await router.navigate("/workbench");
  });
});

describe("LIB-03 report rows", () => {
  it("marks legacy imports and unknown generation time without reordering", async () => {
    serveReports(() => ({
      body: page([
        report(),
        legacyReport({
          report_id: "r-old",
          ticker_code: "600519",
          ticker_name: "贵州茅台",
          analysis_date: "2026-10-28",
        }),
      ]),
    }));
    renderPage("/reports");

    const table = await screen.findByTestId("report-table");
    const rows = within(table).getAllByTestId("report-row");
    expect(rows).toHaveLength(2);

    expect(within(rows[0]).getByText("增持")).toBeInTheDocument();
    expect(within(rows[0]).getByText("AI 分析")).toBeInTheDocument();
    expect(within(rows[0]).getByText("10-28 11:41")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Buy")).toBeInTheDocument();
    expect(within(rows[0]).getByText("有")).toBeInTheDocument();

    expect(within(rows[1]).getByText("卖出")).toBeInTheDocument();
    expect(within(rows[1]).getByText("历史导入")).toBeInTheDocument();
    expect(
      within(rows[1]).getByText("生成时间未知"),
    ).toBeInTheDocument();
    expect(within(rows[1]).getByText("Sell")).toBeInTheDocument();

    const links = within(table).getAllByRole("link", { name: "贵州茅台" });
    expect(links[0]).toHaveAttribute("href", "/reports/r-new");
    expect(links[1]).toHaveAttribute("href", "/reports/r-old");
    expect(within(rows[0]).getAllByText("2026-10-28")).toHaveLength(1);
    expect(within(rows[1]).getAllByText("2026-10-28")).toHaveLength(1);
  });

  it("falls back to the ticker code when the name is missing", async () => {
    serveReports(() => ({ body: page([report({ ticker_name: null })]) }));
    renderPage("/reports");

    const table = await screen.findByTestId("report-table");
    expect(within(table).getByRole("link", { name: "600519" })).toHaveAttribute(
      "href",
      "/reports/r-new",
    );
  });

  it("renders the same row as a mobile card", async () => {
    serveReports(() => ({ body: page([legacyReport()]) }));
    renderPage("/reports");

    const cards = await screen.findByTestId("report-cards");
    const card = within(cards).getByTestId("report-card");
    expect(card).toHaveAttribute("href", "/reports/r-legacy");
    expect(within(card).getByText("卖出")).toBeInTheDocument();
    expect(within(card).getByText("中国平安")).toBeInTheDocument();
    expect(within(card).getByText("历史导入 · 生成时间未知")).toBeInTheDocument();
    expect(within(card).getByText("信号 Sell")).toBeInTheDocument();
  });
});

describe("LIB-04 report list states", () => {
  it("offers the first analysis when the library is empty", async () => {
    serveReports(() => ({ body: page([]) }));
    const router = renderPage("/reports");

    expect(await screen.findByText("还没有报告")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "开始一次分析" }));

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/workbench"),
    );
    expect(router.state.location.search).toBe("?launch=1");
  });

  it("clears the filters when the filtered list is empty", async () => {
    serveReports(() => ({ body: page([]) }));
    const router = renderPage("/reports?rating=Buy&ticker=000629");

    expect(
      await screen.findByText("没有符合条件的报告"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "清空筛选" }));

    await waitFor(() => expect(router.state.location.search).toBe(""));
    await waitFor(() => expect(requests.at(-1)?.has("rating")).toBe(false));
  });

  it("keeps the URL and offers retry when the first page fails", async () => {
    let calls = 0;
    serveReports(() => {
      calls += 1;
      if (calls === 1) {
        return {
          status: 500,
          body: {
            error: { code: "internal_error", message: "服务暂时不可用" },
          },
        };
      }
      return { body: page([report()]) };
    });
    const router = renderPage("/reports?rating=Buy");

    expect(await screen.findByText("服务暂时不可用")).toBeInTheDocument();
    expect(router.state.location.search).toBe("?rating=Buy");

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByTestId("report-row")).toBeInTheDocument();
    expect(router.state.location.search).toBe("?rating=Buy");
    expect(calls).toBe(2);
  });

  it("keeps loaded rows when loading more fails and retries the same cursor", async () => {
    let nextPageCalls = 0;
    serveReports((params) => {
      if (params.get("cursor") === "c2") {
        nextPageCalls += 1;
        if (nextPageCalls === 1) {
          return {
            status: 500,
            body: {
              error: { code: "internal_error", message: "服务暂时不可用" },
            },
          };
        }
        return { body: page([legacyReport()]) };
      }
      return { body: page([report()], "c2") };
    });
    renderPage("/reports");

    await screen.findByTestId("report-row");
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }));
    expect(
      await screen.findByText("加载更多失败，已加载的报告仍然保留。"),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("report-row")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() =>
      expect(screen.getAllByTestId("report-row")).toHaveLength(2),
    );
    expect(nextPageCalls).toBe(2);
    expect(
      requests.filter((params) => params.get("cursor") === "c2"),
    ).toHaveLength(2);
  });
});

describe("LIB-06 zero side effects", () => {
  it("only sends GET requests to /api/v1/reports", async () => {
    serveReports(() => ({ body: page([report()]) }));
    const spy = vi.spyOn(globalThis, "fetch");
    renderPage("/reports?rating=Buy");

    await screen.findByTestId("report-row");
    const calls = spy.mock.calls.map(([input, init]) => ({
      url: String(input),
      method: init?.method ?? "GET",
    }));
    expect(calls.length).toBeGreaterThan(0);
    for (const call of calls) {
      expect(call.method).toBe("GET");
      expect(call.url.startsWith(`${REPORTS_URL}?`)).toBe(true);
      expect(call.url).not.toContain("/market");
      expect(call.url).not.toContain("/jobs");
      expect(call.url).not.toContain("/exports");
    }
  });
});
