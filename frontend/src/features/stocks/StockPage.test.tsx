import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
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
  useParams,
} from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type {
  FundFlowData,
  IntradayData,
  JobListResponse,
  KlineData,
  MarketEnvelope,
  ReportListResponse,
  StockNewsData,
  StockSnapshotData,
} from "../../api/types";
import { StockPage } from "./StockPage";

const ORIGIN = "http://localhost:3000";
const SNAPSHOT_URL = `${ORIGIN}/api/v1/stocks/600000/snapshot`;
const KLINE_URL = `${ORIGIN}/api/v1/stocks/600000/kline`;
const INTRADAY_URL = `${ORIGIN}/api/v1/stocks/600000/intraday`;
const NEWS_URL = `${ORIGIN}/api/v1/stocks/600000/news`;
const FUND_URL = `${ORIGIN}/api/v1/stocks/600000/fund-flow`;
const REPORTS_URL = `${ORIGIN}/api/v1/stocks/600000/reports`;
const JOBS_URL = `${ORIGIN}/api/v1/jobs`;
const META_URL = `${ORIGIN}/api/v1/meta/options`;

const AS_OF = "2026-11-05T09:30:00+08:00";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function envelope<T>(
  data: T | null,
  overrides: Partial<MarketEnvelope<T>> = {},
): MarketEnvelope<T> {
  return {
    schema_version: "market-envelope-v1",
    status: "ok",
    source: "mixed",
    as_of: AS_OF,
    fetched_at: AS_OF,
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

const SNAPSHOT: StockSnapshotData = {
  quote: {
    name: "浦发银行",
    price: 10.52,
    last_close: 10.39,
    open: 10.4,
    high: 10.6,
    low: 10.35,
    change_pct: 1.25,
    change_amt: 0.13,
    amount_wan: 86550.5,
    turnover_pct: 0.42,
    pe_ttm: 5.6,
    pb: 0.62,
    amplitude_pct: 2.4,
    float_mcap_yi: 3085.2,
    mcap_yi: 3085.2,
    limit_up: 11.43,
  },
  valuation: {
    eps_forecast: 1.86,
    pe_forward: 5.65,
    peg: 0.42,
    pe_digestion_years: 3.1,
  },
  sector_blocks: {
    industry: [{ name: "银行", change_pct: 0.8, desc: "股份制银行" }],
    concept: [{ name: "沪股通", change_pct: 0.2, desc: "" }],
    region: [{ name: "上海", change_pct: -0.1, desc: "" }],
  },
  units: { price: "元", amount: "万元", mcap: "亿元" },
};

const KLINE: KlineData = {
  adjust: "none",
  bars: [
    { date: "2026-10-29", open: 10.1, high: 10.3, low: 10.0, close: 10.2, volume: 120000, amount: 122400000 },
    { date: "2026-10-30", open: 10.2, high: 10.42, low: 10.1, close: 10.39, volume: 151000, amount: 156800000 },
    { date: "2026-11-05", open: 10.4, high: 10.6, low: 10.35, close: 10.52, volume: 168000, amount: 176500000 },
  ],
  units: { price: "元", volume: "手", amount: "元" },
};

const INTRADAY: IntradayData = {
  date: "2026-11-05",
  points: [
    { time: "09:30", price: 10.4, volume: 1000, avg_price: 10.4 },
    { time: "11:30", price: 10.5, volume: 800, avg_price: 10.45 },
    { time: "13:00", price: 10.48, volume: 900, avg_price: 10.46 },
    { time: "15:00", price: 10.52, volume: 1600, avg_price: 10.49 },
  ],
  session_gaps: [["11:30", "13:00"]],
  units: { price: "元", volume: "手", amount: "元" },
};

const NEWS: StockNewsData = {
  items: [
    {
      title: "浦发银行发布三季度报告",
      content: "详情见 https://example.com/news/1。",
      published_at: "2026-11-05T09:10:00+08:00",
      source: "eastmoney",
      url: "https://example.com/news/1",
    },
    {
      title: "<script>alert(1)</script> 不应执行",
      content: "javascript:alert(1) 只作为文本显示。",
      published_at: "2026-11-04T18:00:00+08:00",
      source: "cls",
      url: "javascript:alert(1)",
    },
  ],
  untrusted: true,
};

const FUND_FLOW: FundFlowData = {
  items: [
    { time: "09:30", main_net: 1200000, small_net: -400000, mid_net: 50000, large_net: 300000, super_net: 850000 },
    { time: "10:00", main_net: -300000, small_net: 120000, mid_net: -20000, large_net: -100000, super_net: -180000 },
  ],
};

const REPORTS: ReportListResponse = {
  items: [
    {
      meta: {
        report_id: "rpt-1",
        job_id: "job-1",
        ticker_code: "600000",
        ticker_name: "浦发银行",
        analysis_date: "2026-11-04",
        generated_at: "2026-11-04T16:20:00+08:00",
        generated_at_source: "job_clock",
        origin: "new",
        schema_version: "report-schema-v1",
        content_hash: "hash-1",
        config_digest: "cfg-1",
        data_quality_status: "ok",
        chart_snapshot_status: "none",
        retry_of_job_id: null,
        rating: "Buy",
        signal: "Buy",
      },
      summary_available: true,
    },
  ],
  next_cursor: null,
};

const META_OPTIONS = {
  app_version: "0.9.0",
  server_time: AS_OF,
  default_analysis_date: "2026-11-05",
  llm_profiles: [{ id: "deepseek-default", label: "DeepSeek 默认" }],
  stage_toggles: [{ id: "policy", label: "政策分析", default: true }],
  limits: { max_active_jobs: 1, max_date_ahead_days: 0 },
  journal: { available: false, entry_url: "http://127.0.0.1:8502", reason: "not_running" },
  contract_version: "api-v1",
};

function activeJob(jobId: string): JobListResponse {
  return {
    items: [
      {
        job_id: jobId,
        status: "running",
        pending_action: null,
        ticker_code: "600000",
        ticker_name: "浦发银行",
        analysis_date: "2026-11-05",
        created_at: AS_OF,
        updated_at: AS_OF,
        started_at: AS_OF,
        finished_at: null,
        current_stage: null,
        stats: { model_calls: 3, tokens_in: 1000, tokens_out: 800, elapsed_ms: 65000 },
        report_id: null,
        error: null,
        config_digest: "cfg-1",
        graph_version: "graph-v1",
        retry_of_job_id: null,
        resume_of_job_id: null,
        resume_from_stage: null,
        allowed_actions: ["pause", "cancel"],
        links: {
          self: `/api/v1/jobs/${jobId}`,
          events: `/api/v1/jobs/${jobId}/events`,
          report: null,
        },
      },
    ],
    next_cursor: null,
  };
}

let requests: URL[] = [];

interface ServeOptions {
  snapshot?: MarketEnvelope<StockSnapshotData>;
  snapshotStatus?: number;
  kline?: MarketEnvelope<KlineData>;
  intraday?: MarketEnvelope<IntradayData>;
  news?: MarketEnvelope<StockNewsData>;
  fundFlow?: MarketEnvelope<FundFlowData>;
  reports?: ReportListResponse;
  reportsStatus?: number;
  jobs?: JobListResponse;
}

function serveStock(options: ServeOptions = {}) {
  requests = [];
  server.use(
    http.get(SNAPSHOT_URL, ({ request }) => {
      requests.push(new URL(request.url));
      if (options.snapshotStatus !== undefined) {
        return HttpResponse.json(
          {
            error: {
              code: "invalid_request",
              message: "没有这只股票",
              details: { field: "ticker" },
            },
          },
          { status: options.snapshotStatus },
        );
      }
      return HttpResponse.json(options.snapshot ?? envelope(SNAPSHOT));
    }),
    http.get(KLINE_URL, ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(options.kline ?? envelope(KLINE));
    }),
    http.get(INTRADAY_URL, ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(options.intraday ?? envelope(INTRADAY));
    }),
    http.get(NEWS_URL, ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(options.news ?? envelope(NEWS));
    }),
    http.get(FUND_URL, ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(options.fundFlow ?? envelope(FUND_FLOW));
    }),
    http.get(REPORTS_URL, ({ request }) => {
      requests.push(new URL(request.url));
      if (options.reportsStatus !== undefined) {
        return HttpResponse.json(
          { error: { code: "internal_error", message: "失败" } },
          { status: options.reportsStatus },
        );
      }
      return HttpResponse.json(options.reports ?? REPORTS);
    }),
    http.get(JOBS_URL, ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(options.jobs ?? { items: [], next_cursor: null });
    }),
    http.get(META_URL, () => HttpResponse.json(META_OPTIONS)),
  );
}

function StockRoute() {
  const { ticker = "" } = useParams();
  return (
    <>
      <StockPage ticker={ticker} />
      <LocationProbe />
    </>
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

function renderStock(entry = "/stocks/600000") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(
    [
      { path: "/stocks/:ticker", element: <StockRoute /> },
      { path: "/jobs/:jobId", element: <LocationProbe /> },
      { path: "/jobs", element: <LocationProbe /> },
      { path: "/reports", element: <LocationProbe /> },
      { path: "/reports/:reportId", element: <LocationProbe /> },
    ],
    { initialEntries: [entry] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { client, router };
}

describe("W07-01 stock header", () => {
  it("shows identity, market, price, source and data time", async () => {
    serveStock();
    renderStock();
    await screen.findByTestId("stock-header");
    const header = screen.getByTestId("stock-header");
    await within(header).findByText("浦发银行");
    const text = header.textContent ?? "";
    expect(text).toContain("600000");
    expect(text).toContain("沪市");
    expect(text).toContain("10.52");
    expect(text).toContain("+1.25%");
    expect(text).toContain("来源 多源");
    expect(text).toContain("数据时间");
    expect(screen.getByTestId("stock-primary-action")).toHaveTextContent(
      "分析这只股票",
    );
  });

  it("keeps data visible under a stale banner with the reason", async () => {
    serveStock({
      snapshot: envelope(SNAPSHOT, {
        status: "stale",
        is_stale: true,
        stale_reason: "ttl_exceeded",
      }),
    });
    renderStock();
    const banner = await screen.findByTestId("stale-banner");
    expect(banner).toHaveTextContent("数据可能已过期");
    expect(banner).toHaveTextContent("超过新鲜度阈值");
    expect(screen.getByTestId("stock-price")).toHaveTextContent("10.52");
  });
});

describe("W07-02 primary action", () => {
  it("opens the launcher prefilled when no job is active", async () => {
    serveStock();
    renderStock();
    await screen.findByTestId("stock-primary-action");
    fireEvent.click(screen.getByTestId("stock-primary-action"));
    const dialog = await screen.findByRole("dialog", { name: "分析启动器" });
    expect(await within(dialog).findByText("600000")).toBeInTheDocument();
    expect(within(dialog).getByText("浦发银行")).toBeInTheDocument();
  });

  it("jumps to the active job instead of launching", async () => {
    serveStock({ jobs: activeJob("job-9") });
    renderStock();
    const button = await screen.findByTestId("stock-primary-action");
    await waitFor(() =>
      expect(button).toHaveTextContent("查看进行中任务"),
    );
    fireEvent.click(button);
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/jobs/job-9"),
    );
    expect(
      requests.some((url) => url.searchParams.get("ticker") === "600000"),
    ).toBe(true);
  });
});

describe("W07-03 valuation tab", () => {
  it("renders quote fields, consensus estimates, blocks and fund flow", async () => {
    serveStock();
    renderStock();
    const tab = await screen.findByTestId("stock-valuation");
    expect(tab).toHaveTextContent("1.86");
    expect(tab).toHaveTextContent("5.65");
    expect(tab).toHaveTextContent("0.42");
    expect(tab).toHaveTextContent("3.10");
    expect(screen.getAllByTestId("sector-group")).toHaveLength(3);
    expect(tab).toHaveTextContent("银行");
    expect(await screen.findByTestId("fund-flow-table")).toBeInTheDocument();
    expect(screen.getAllByTestId("fund-flow-row")).toHaveLength(2);
    expect(tab).toHaveTextContent("主力净额");
  });

  it("renders dashes and a note when valuation is unavailable", async () => {
    serveStock({
      snapshot: envelope({
        ...SNAPSHOT,
        valuation: null,
        sector_blocks: null,
      }),
    });
    renderStock();
    await screen.findByTestId("stock-valuation");
    const fields = screen.getAllByTestId("valuation-field");
    const missing = fields.filter((field) => field.dataset.missing === "true");
    expect(missing).toHaveLength(4);
    expect(missing.every((field) => field.textContent === "—")).toBe(true);
    expect(screen.getByTestId("valuation-note")).toHaveTextContent("不可得");
    expect(screen.getByTestId("sector-note")).toHaveTextContent("板块数据不可得");
  });
});

describe("W07-04 K-line tab", () => {
  it("follows the period query and refetches on change", async () => {
    serveStock();
    renderStock("/stocks/600000?tab=kline&period=week");
    const chart = await screen.findByTestId("kline-chart");
    expect(chart).toHaveAttribute("data-period", "week");
    expect(requests.some((url) => url.searchParams.get("period") === "week")).toBe(
      true,
    );
    expect(screen.getByTestId("kline-meta")).toHaveTextContent("不复权");
    fireEvent.click(screen.getByTestId("kline-period-day"));
    await waitFor(() =>
      expect(screen.getByTestId("kline-chart")).toHaveAttribute(
        "data-period",
        "day",
      ),
    );
    await waitFor(() =>
      expect(
        requests.some((url) => url.searchParams.get("period") === "day"),
      ).toBe(true),
    );
    expect(screen.getByTestId("location").textContent).toBe(
      "/stocks/600000?tab=kline",
    );
  });
});

describe("W07-05 intraday tab", () => {
  it("defaults to the latest day and writes the chosen date to the query", async () => {
    serveStock();
    renderStock("/stocks/600000?tab=intraday");
    await screen.findByTestId("intraday-chart");
    const input = screen.getByLabelText("分时日期");
    expect(input).toHaveValue("");
    expect(
      requests.some((url) => url.searchParams.has("date") === false),
    ).toBe(true);
    fireEvent.change(input, { target: { value: "2026-10-01" } });
    await waitFor(() =>
      expect(
        requests.some((url) => url.searchParams.get("date") === "2026-10-01"),
      ).toBe(true),
    );
    expect(screen.getByTestId("location").textContent).toBe(
      "/stocks/600000?tab=intraday&date=2026-10-01",
    );
  });

  it("uses the retention copy when a dated request is empty", async () => {
    serveStock({
      intraday: envelope<IntradayData>(null, { status: "empty" }),
    });
    renderStock("/stocks/600000?tab=intraday&date=2026-10-01");
    expect(
      await screen.findByText("该日期没有分时数据"),
    ).toBeInTheDocument();
  });
});

describe("W07-06 news tab", () => {
  it("renders plain text and only links http(s) URLs", async () => {
    serveStock();
    renderStock("/stocks/600000?tab=news");
    const items = await screen.findAllByTestId("stock-news-item");
    expect(items).toHaveLength(2);
    const list = screen.getByTestId("stock-news");
    expect(list).toHaveTextContent("<script>alert(1)</script>");
    expect(list.querySelector("script")).toBeNull();
    expect(list.querySelector('a[href^="javascript:"]')).toBeNull();
    const link = within(list).getByTestId("stock-news-link");
    expect(link).toHaveAttribute("href", "https://example.com/news/1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});

describe("W07-07 reports tab", () => {
  it("lists reports and opens the reader", async () => {
    serveStock();
    renderStock("/stocks/600000?tab=reports");
    const rows = await screen.findAllByTestId("stock-report-row");
    expect(rows).toHaveLength(1);
    const link = within(rows[0]).getByRole("link", { name: /2026-11-04/ });
    expect(link).toHaveAttribute("href", "/reports/rpt-1");
    fireEvent.click(link);
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/reports/rpt-1"),
    );
  });

  it("shows an empty state and an error state", async () => {
    serveStock({ reports: { items: [], next_cursor: null } });
    renderStock("/stocks/600000?tab=reports");
    expect(
      await screen.findByText("还没有这只股票的报告"),
    ).toBeInTheDocument();
  });

  it("shows a retryable error when the report list fails", async () => {
    serveStock({ reportsStatus: 500 });
    renderStock("/stocks/600000?tab=reports");
    expect(await screen.findByTestId("data-state-error")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });
});

describe("W07-08 deep links", () => {
  it("restores tab, period and date from the query", async () => {
    serveStock();
    renderStock("/stocks/600000?tab=intraday&period=week&date=2026-10-01");
    await screen.findByTestId("intraday-chart");
    expect(screen.getByLabelText("分时日期")).toHaveValue("2026-10-01");
    expect(
      screen
        .getAllByTestId("stock-tab")
        .find((tab) => tab.getAttribute("aria-selected") === "true")?.dataset
        .tab,
    ).toBe("intraday");
  });

  it("falls back to defaults without rewriting the path", async () => {
    serveStock();
    const { router } = renderStock(
      "/stocks/600000?tab=bad&period=bad&date=2026-13-01",
    );
    await screen.findByTestId("stock-valuation");
    const active = screen
      .getAllByTestId("stock-tab")
      .find((tab) => tab.getAttribute("aria-selected") === "true");
    expect(active?.dataset.tab).toBe("valuation");
    expect(router.state.location.pathname).toBe("/stocks/600000");
    fireEvent.click(screen.getByRole("tab", { name: "K 线" }));
    await waitFor(() =>
      expect(screen.getByTestId("location").textContent).toBe(
        "/stocks/600000?tab=kline",
      ),
    );
  });
});

describe("W07-09 invalid tickers", () => {
  it("renders the 400 page when the name table has no such code", async () => {
    serveStock({ snapshotStatus: 400 });
    renderStock();
    const page = await screen.findByTestId("invalid-ticker");
    expect(page).toHaveTextContent("没有这只股票");
    expect(page).toHaveTextContent("不在本地名称表中");
    expect(within(page).getByRole("link", { name: "回市场" })).toHaveAttribute(
      "href",
      "/market",
    );
  });
});

describe("W07-10 partial snapshot", () => {
  it("keeps the quote and names the failed block", async () => {
    serveStock({
      snapshot: envelope(
        { ...SNAPSHOT, valuation: null, sector_blocks: null },
        { partial: true, failed_blocks: ["valuation"] },
      ),
    });
    renderStock();
    const header = await screen.findByTestId("stock-header");
    await within(header).findByTestId("stock-price");
    expect(screen.getByTestId("partial-notice")).toHaveTextContent(
      "部分数据不可用",
    );
    expect(screen.getByTestId("partial-blocks")).toHaveTextContent("估值");
    expect(screen.getByTestId("stock-price")).toHaveTextContent("10.52");
  });
});

function snapshotCalls(): number {
  return requests.filter(
    (url) => url.pathname === "/api/v1/stocks/600000/snapshot",
  ).length;
}

function fundFlowCalls(): number {
  return requests.filter(
    (url) => url.pathname === "/api/v1/stocks/600000/fund-flow",
  ).length;
}

function setVisibility(value: "visible" | "hidden") {
  act(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => value,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

afterEach(() => {
  delete (document as { visibilityState?: unknown }).visibilityState;
});

describe("REF-01 stock polling", () => {
  it("polls the snapshot and fund flow at 60 s and the K line at 5 min", async () => {
    serveStock();
    const { client } = renderStock();
    await screen.findByTestId("stock-valuation");
    const intervalOf = (queryKey: unknown[]) =>
      client
        .getQueryCache()
        .find({ queryKey })?.observers[0]?.options.refetchInterval;

    expect(intervalOf(["stock", "snapshot", "600000"])).toBe(60_000);
    expect(intervalOf(["stock", "fundFlow", "600000"])).toBe(60_000);

    fireEvent.click(screen.getByRole("tab", { name: "K 线" }));
    await waitFor(() =>
      expect(intervalOf(["stock", "kline", "600000", "day", 120])).toBe(
        300_000,
      ),
    );
  });
});

describe("REF-02 stock hidden tab", () => {
  it("refetches the workspace at once when the tab returns", async () => {
    serveStock();
    renderStock();
    await screen.findByTestId("stock-valuation");
    const before = snapshotCalls();
    const flows = fundFlowCalls();

    setVisibility("hidden");
    expect(snapshotCalls()).toBe(before);

    setVisibility("visible");
    await waitFor(() => expect(snapshotCalls()).toBe(before + 1));
    await waitFor(() => expect(fundFlowCalls()).toBe(flows + 1));
  });
});

describe("REF-03 stock manual refresh", () => {
  it("sends one refresh group for a burst of clicks", async () => {
    serveStock();
    renderStock();
    await screen.findByTestId("stock-valuation");
    const before = snapshotCalls();
    const flows = fundFlowCalls();

    const button = screen.getByTestId("stock-refresh");
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(snapshotCalls()).toBe(before);

    await waitFor(() => expect(snapshotCalls()).toBe(before + 1), {
      timeout: 2000,
    });
    expect(fundFlowCalls()).toBe(flows + 1);
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(snapshotCalls()).toBe(before + 1);
  });
});

describe("P5-07 screen reader semantics", () => {
  it("SR-06 labels the fund flow table and its columns", async () => {
    serveStock();
    renderStock();

    const table = await screen.findByTestId("fund-flow-table");
    expect(table).toHaveAccessibleName("资金流明细");
    expect(table.querySelector("caption")).toHaveTextContent("资金流明细");
    expect(table.querySelectorAll("thead th[scope='col']")).toHaveLength(6);
    for (const cell of Array.from(table.querySelectorAll("th"))) {
      expect(cell).toHaveAttribute("scope");
    }
  });

  it("SR-04 announces a finished manual refresh", async () => {
    serveStock();
    renderStock();
    await screen.findByTestId("stock-valuation");

    const status = screen.getByTestId("stock-refresh-status");
    expect(status).toHaveAttribute("role", "status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status.textContent).toBe("");

    fireEvent.click(screen.getByTestId("stock-refresh"));
    await waitFor(
      () => {
        expect(status.textContent).toMatch(/已刷新，时间 \d{2}:\d{2}:\d{2}/);
      },
      { timeout: 2000 },
    );
    expect(
      within(screen.getByTestId("page-stock")).getAllByRole("status"),
    ).toHaveLength(1);
  });
});

describe("REF-04 stock leaving the page", () => {
  it("clears the poll timer when the workspace unmounts", async () => {
    serveStock();
    const { router } = renderStock();
    await screen.findByTestId("stock-valuation");
    await act(async () => {
      await router.navigate("/jobs");
    });
    expect(screen.queryByTestId("page-stock")).toBeNull();
    const settled = snapshotCalls();

    vi.useFakeTimers();
    try {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(70_000);
      });
    } finally {
      vi.useRealTimers();
    }
    expect(snapshotCalls()).toBe(settled);
  });
});

describe("CTX-03 stock to jobs", () => {
  it("links the workspace into reports and the ticker-filtered job list", async () => {
    serveStock();
    renderStock();
    await screen.findByTestId("stock-header");
    expect(
      screen.getByRole("link", { name: "查看最新报告" }),
    ).toHaveAttribute("href", "/reports?ticker=600000");
    const jobs = screen.getByRole("link", { name: "查看该股票任务" });
    expect(jobs).toHaveAttribute("href", "/jobs?ticker=600000");
    fireEvent.click(jobs);
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/jobs?ticker=600000",
      ),
    );
  });
});
