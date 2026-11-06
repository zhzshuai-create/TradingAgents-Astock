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
  MarketEnvelope,
  MarketIndustriesData,
  MarketOverviewData,
  MarketStrongStocksData,
} from "../../api/types";
import { MarketSummary } from "./MarketSummary";

const ORIGIN = "http://localhost:3000";
const OVERVIEW_URL = `${ORIGIN}/api/v1/market/overview`;
const INDUSTRIES_URL = `${ORIGIN}/api/v1/market/industries`;
const STRONG_URL = `${ORIGIN}/api/v1/market/strong-stocks`;

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

const OVERVIEW_DATA: MarketOverviewData = {
  market_session: "closed",
  indices: [
    { code: "000001", name: "上证指数", price: 4012.34, change_pct: 0.42, change_amt: 16.8 },
    { code: "399001", name: "深证成指", price: 13210.5, change_pct: -0.31, change_amt: -41.2 },
    { code: "399006", name: "创业板指", price: 2810.2, change_pct: 1.12, change_amt: 31.1 },
  ],
  northbound: null,
};

const INDUSTRIES_DATA: MarketIndustriesData = {
  top: [
    { rank: 1, name: "半导体", code: "BK0475", change_pct: 3.21, up_count: 40, down_count: 2, leader: "中芯国际", leader_change: 8.1 },
    { rank: 2, name: "算力", code: "BK1036", change_pct: 2.84, up_count: 30, down_count: 3, leader: "中际旭创", leader_change: 7.2 },
    { rank: 3, name: "稀土", code: "BK0578", change_pct: 2.11, up_count: 20, down_count: 4, leader: "北方稀土", leader_change: 5.4 },
  ],
  bottom: [],
  total: 30,
};

const STRONG_DATA: MarketStrongStocksData = {
  items: [
    { ticker_code: "300750", name: "宁德时代", reason: "储能", market: "sz", change_pct: 6.2, change_amt: 11.1, close: 190.2, turnover_pct: 1.2 },
    { ticker_code: "600519", name: "贵州茅台", reason: "白酒", market: "sh", change_pct: 4.1, change_amt: 60.2, close: 1520.0, turnover_pct: 0.6 },
    { ticker_code: "300308", name: "中际旭创", reason: "算力", market: "sz", change_pct: 3.8, change_amt: 5.4, close: 148.3, turnover_pct: 2.1 },
  ],
};

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname}
      {location.search}
    </output>
  );
}

function renderSummary() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(
    [
      { path: "/", element: <MarketSummary /> },
      { path: "/stocks/:ticker", element: <LocationProbe /> },
      { path: "/market", element: <LocationProbe /> },
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

function serveMarket(
  options: {
    overview?: MarketEnvelope<MarketOverviewData>;
    industries?: MarketEnvelope<MarketIndustriesData>;
    strong?: MarketEnvelope<MarketStrongStocksData>;
  } = {},
) {
  server.use(
    http.get(OVERVIEW_URL, () =>
      HttpResponse.json(options.overview ?? envelope(OVERVIEW_DATA)),
    ),
    http.get(INDUSTRIES_URL, () =>
      HttpResponse.json(options.industries ?? envelope(INDUSTRIES_DATA)),
    ),
    http.get(STRONG_URL, () =>
      HttpResponse.json(options.strong ?? envelope(STRONG_DATA)),
    ),
  );
}

describe("WB-02 market summary", () => {
  it("renders three indices, three industries and three strong stocks", async () => {
    serveMarket();
    const router = renderSummary();

    const indices = screen.getByTestId("summary-indices");
    await waitFor(() => expect(within(indices).getAllByTestId("summary-index")).toHaveLength(3));
    expect(within(indices).getByText("上证指数")).toBeInTheDocument();
    expect(within(indices).getByText("+0.42%")).toBeInTheDocument();
    expect(within(indices).getByText("-0.31%")).toBeInTheDocument();
    expect(within(indices).getByText("已收盘")).toBeInTheDocument();

    const industries = screen.getByTestId("summary-industries");
    expect(within(industries).getAllByTestId("summary-industry")).toHaveLength(3);
    expect(within(industries).getByText("半导体")).toBeInTheDocument();

    const strong = screen.getByTestId("summary-strong");
    const links = within(strong).getAllByTestId("summary-strong-stock");
    expect(links).toHaveLength(3);
    expect(links[0]).toHaveAttribute("href", "/stocks/300750");

    fireEvent.click(links[0]);
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/stocks/300750"),
    );
  });

  it("links the header to the full market page", async () => {
    serveMarket();
    const router = renderSummary();

    const link = screen.getByRole("link", { name: "查看市场" });
    expect(link).toHaveAttribute("href", "/market");
    fireEvent.click(link);
    await waitFor(() => expect(router.state.location.pathname).toBe("/market"));
  });

  it("shows the stale banner with the contract reason", async () => {
    serveMarket({
      overview: envelope(OVERVIEW_DATA, {
        status: "stale",
        is_stale: true,
        stale_reason: "ttl_exceeded",
      }),
    });
    renderSummary();

    const indices = screen.getByTestId("summary-indices");
    expect(await within(indices).findByText("数据可能已过期")).toBeInTheDocument();
    expect(within(indices).getByText("超过新鲜度阈值")).toBeInTheDocument();
    expect(within(indices).getByTestId("stale-banner")).toBeInTheDocument();
  });

  it("keeps the data visible when only one block failed", async () => {
    serveMarket({
      overview: envelope(OVERVIEW_DATA, {
        partial: true,
        failed_blocks: ["northbound"],
      }),
    });
    renderSummary();

    const indices = screen.getByTestId("summary-indices");
    expect(await within(indices).findByText("部分数据不可用")).toBeInTheDocument();
    expect(within(indices).getByTestId("partial-blocks")).toHaveTextContent("北向");
    expect(within(indices).getByText("上证指数")).toBeInTheDocument();
  });

  it("uses the empty state for a block without data", async () => {
    serveMarket({
      industries: envelope<MarketIndustriesData>(null, { status: "empty" }),
    });
    renderSummary();

    const industries = screen.getByTestId("summary-industries");
    expect(await within(industries).findByText("暂无数据")).toBeInTheDocument();
  });

  it("shows an error and retries only the failed block", async () => {
    let overviewCalls = 0;
    let strongCalls = 0;
    server.use(
      http.get(OVERVIEW_URL, () => {
        overviewCalls += 1;
        return HttpResponse.json(optionsErrorEnvelope());
      }),
      http.get(INDUSTRIES_URL, () => HttpResponse.json(envelope(INDUSTRIES_DATA))),
      http.get(STRONG_URL, () => {
        strongCalls += 1;
        return HttpResponse.json(envelope(STRONG_DATA));
      }),
    );
    renderSummary();

    const indices = screen.getByTestId("summary-indices");
    expect(await within(indices).findByText("数据源请求失败")).toBeInTheDocument();
    expect(overviewCalls).toBe(1);
    expect(strongCalls).toBe(1);

    fireEvent.click(within(indices).getByRole("button", { name: "重试" }));
    await waitFor(() => expect(overviewCalls).toBe(2));
    expect(strongCalls).toBe(1);
  });
});

function optionsErrorEnvelope(): MarketEnvelope<never> {
  return {
    schema_version: "market-envelope-v1",
    status: "error",
    source: "mixed",
    as_of: null,
    fetched_at: "2026-11-05T09:30:00+08:00",
    is_stale: false,
    stale_reason: null,
    error_code: "upstream_timeout",
    error_message: "timeout",
    partial: false,
    failed_blocks: [],
    data: null,
  };
}