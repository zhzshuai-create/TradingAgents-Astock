import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import {
  createMemoryRouter,
  RouterProvider,
  useLocation,
  useParams,
} from "react-router-dom";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
} from "vitest";

import type {
  FundFlowData,
  JobListResponse,
  KlineData,
  MarketEnvelope,
  StockSnapshotData,
} from "../../api/types";
import { StockPage } from "./StockPage";

const ORIGIN = "http://localhost:3000";
const SNAPSHOT_URL = `${ORIGIN}/api/v1/stocks/600000/snapshot`;
const KLINE_URL = `${ORIGIN}/api/v1/stocks/600000/kline`;
const FUND_URL = `${ORIGIN}/api/v1/stocks/600000/fund-flow`;
const JOBS_URL = `${ORIGIN}/api/v1/jobs`;
const META_URL = `${ORIGIN}/api/v1/meta/options`;
const AS_OF = "2026-11-05T09:30:00+08:00";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function envelope<T>(data: T | null): MarketEnvelope<T> {
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

const FUND_FLOW: FundFlowData = {
  items: [
    { time: "09:30", main_net: 1200000, small_net: -400000, mid_net: 50000, large_net: 300000, super_net: 850000 },
  ],
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

function serveStock(jobs: JobListResponse = { items: [], next_cursor: null }) {
  server.use(
    http.get(SNAPSHOT_URL, () => HttpResponse.json(envelope(SNAPSHOT))),
    http.get(KLINE_URL, () => HttpResponse.json(envelope(KLINE))),
    http.get(FUND_URL, () => HttpResponse.json(envelope(FUND_FLOW))),
    http.get(JOBS_URL, () => HttpResponse.json(jobs)),
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

function renderMobile(entry = "/stocks/600000") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(
    [
      { path: "/stocks/:ticker", element: <StockRoute /> },
      { path: "/jobs/:jobId", element: <LocationProbe /> },
      { path: "/jobs", element: <LocationProbe /> },
      { path: "/reports", element: <LocationProbe /> },
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

/** jsdom has no media queries; useIsMobile reads matchMedia on mount. */
let restoreViewport: () => void = () => {};

beforeEach(() => {
  const original = Object.getOwnPropertyDescriptor(window, "matchMedia");
  const list = {
    matches: true,
    media: "(max-width: 767px)",
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  };
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: () => list,
  });
  restoreViewport = () => {
    if (original === undefined) {
      delete (window as unknown as Record<string, unknown>).matchMedia;
    } else {
      Object.defineProperty(window, "matchMedia", original);
    }
  };
});

afterEach(() => {
  restoreViewport();
});

describe("W07M mobile stock workspace", () => {
  it("W07M-01/02 scrolls the tabs inside their own container and docks the primary action", async () => {
    serveStock();
    renderMobile();
    await screen.findByTestId("stock-price");

    const tabs = screen.getByTestId("stock-tabs");
    expect(tabs).toHaveAttribute("data-scroll", "x");
    expect(within(tabs).getAllByRole("tab")).toHaveLength(5);

    const bar = screen.getByTestId("stock-action-bar");
    const button = within(bar).getByTestId("stock-primary-action");
    expect(button.textContent).toBe("分析这只股票");
    // The desktop header no longer carries a second primary button.
    expect(screen.getAllByTestId("stock-primary-action")).toHaveLength(1);
    const header = screen.getByTestId("stock-header");
    expect(within(header).queryByTestId("stock-primary-action")).toBeNull();
    expect(within(header).getByRole("link", { name: "查看最新报告" })).toBeTruthy();

    fireEvent.click(button);
    const dialog = await screen.findByRole("dialog", { name: "分析启动器" });
    expect(dialog.textContent).toContain("600000");
    expect(dialog.textContent).toContain("浦发银行");
  });

  it("W07M-02 an active job swaps the docked button for the job link", async () => {
    serveStock(activeJob("job-9"));
    const router = renderMobile();
    const bar = await screen.findByTestId("stock-action-bar");
    await waitFor(() =>
      expect(within(bar).getByTestId("stock-primary-action").textContent).toBe(
        "查看进行中任务",
      ),
    );

    fireEvent.click(within(bar).getByTestId("stock-primary-action"));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/jobs/job-9"),
    );
  });

  it("W07M-03 keeps the chart in a scroll container, switches periods by button and drops wheel zoom", async () => {
    serveStock();
    const router = renderMobile("/stocks/600000?tab=kline");
    const chart = await screen.findByTestId("kline-chart");

    const scroll = within(chart).getByTestId("kline-scroll");
    expect(scroll).toHaveAttribute("data-scroll", "x");
    expect(screen.getByTestId("kline-hint")).toHaveAttribute("data-mobile", "true");
    expect(screen.getByTestId("kline-hint").textContent).toContain("周期按钮");

    const windowBefore = screen.getByTestId("kline-window").getAttribute("data-count");
    fireEvent.wheel(screen.getByRole("img", { name: /K 线/ }), { deltaY: -120 });
    expect(screen.getByTestId("kline-window").getAttribute("data-count")).toBe(
      windowBefore,
    );

    const week = screen.getByTestId("kline-period-week");
    expect(week).toBeTruthy();
    fireEvent.click(week);
    await waitFor(() =>
      expect(router.state.location.search).toContain("period=week"),
    );
  });
});
