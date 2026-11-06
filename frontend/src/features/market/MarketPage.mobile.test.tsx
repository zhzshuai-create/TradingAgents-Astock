import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import {
  createMemoryRouter,
  RouterProvider,
  useLocation,
} from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import type {
  MarketConstituentsData,
  MarketEnvelope,
  MarketIndustriesData,
  MarketNewsflashData,
  MarketOverviewData,
  MarketStrongStocksData,
} from "../../api/types";
import { MarketPage } from "./MarketPage";

const ORIGIN = "http://localhost:3000";
const OVERVIEW_URL = `${ORIGIN}/api/v1/market/overview`;
const INDUSTRIES_URL = `${ORIGIN}/api/v1/market/industries`;
const STRONG_URL = `${ORIGIN}/api/v1/market/strong-stocks`;
const NEWS_URL = `${ORIGIN}/api/v1/market/newsflash`;
const CONSTITUENTS_URL = `${ORIGIN}/api/v1/market/industries/BK1000/stocks`;

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
  ],
  northbound: null,
};

const INDUSTRIES_DATA: MarketIndustriesData = {
  top: [
    { rank: 1, name: "半导体", code: "BK1000", change_pct: 3.21, up_count: 40, down_count: 2, leader: "中芯国际", leader_change: 8.1 },
    { rank: 2, name: "算力", code: "BK1001", change_pct: 2.84, up_count: 30, down_count: 3, leader: "中际旭创", leader_change: 7.2 },
  ],
  bottom: [
    { rank: 30, name: "煤炭", code: "BK1030", change_pct: -1.5, up_count: 2, down_count: 40, leader: "中国神华", leader_change: -2.1 },
  ],
  total: 30,
};

const CONSTITUENTS_DATA: MarketConstituentsData = {
  items: [
    { code: "600000", name: "浦发银行", price: 10.2, change_pct: 1.2 },
    { code: "600001", name: "邯郸钢铁", price: null, change_pct: -0.8 },
  ],
};

const STRONG_DATA: MarketStrongStocksData = {
  items: [
    { ticker_code: "300750", name: "宁德时代", reason: "储能", market: "sz", change_pct: 6.2, change_amt: 11.1, close: 190.2, turnover_pct: 1.2 },
    { ticker_code: "300308", name: "中际旭创", reason: "算力", market: "sz", change_pct: 3.8, change_amt: 5.4, close: 148.3, turnover_pct: 2.1 },
  ],
};

const NEWS_DATA: MarketNewsflashData = {
  items: [
    {
      published_at: "2026-11-05T09:28:00+08:00",
      title: "央行公开市场净投放 2000 亿元",
      content: "",
    },
  ],
  untrusted: true,
};

function serveMarket() {
  server.use(
    http.get(OVERVIEW_URL, () => HttpResponse.json(envelope(OVERVIEW_DATA))),
    http.get(INDUSTRIES_URL, () => HttpResponse.json(envelope(INDUSTRIES_DATA))),
    http.get(STRONG_URL, () => HttpResponse.json(envelope(STRONG_DATA))),
    http.get(NEWS_URL, () => HttpResponse.json(envelope(NEWS_DATA))),
    http.get(CONSTITUENTS_URL, () =>
      HttpResponse.json(envelope(CONSTITUENTS_DATA)),
    ),
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

function renderMobile(initialEntry = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(
    [
      { path: "/", element: <MarketPage /> },
      { path: "/stocks/:ticker", element: <LocationProbe /> },
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

describe("W08M mobile market", () => {
  it("W08M-01/02 renders a horizontal index strip and cards instead of tables", async () => {
    serveMarket();
    renderMobile();

    const strip = await screen.findByTestId("index-strip");
    expect(within(strip).getAllByTestId("index-card")).toHaveLength(2);
    expect(screen.queryByTestId("market-indices")).toBeNull();

    const cards = await screen.findByTestId("industry-cards");
    expect(within(cards).getAllByTestId("industry-card")).toHaveLength(3);
    expect(cards.querySelectorAll('[data-testid="industry-card"][data-variant="bottom"]')).toHaveLength(1);
    expect(cards.textContent).toContain("中芯国际");

    expect(await screen.findAllByTestId("strong-card")).toHaveLength(2);
    expect(screen.queryByTestId("industry-table")).toBeNull();
    expect(screen.queryByTestId("strong-table")).toBeNull();
    expect(document.querySelector("table")).toBeNull();
  });

  it("W08M-02 filters strong cards by theme and keeps the query in sync", async () => {
    serveMarket();
    const router = renderMobile();

    const chips = await screen.findByTestId("theme-chips");
    expect(within(chips).getAllByTestId("theme-chip")).toHaveLength(3);
    fireEvent.click(within(chips).getByRole("button", { name: "算力" }));

    await waitFor(() => expect(screen.getAllByTestId("strong-card")).toHaveLength(1));
    expect(router.state.location.search).toContain("theme=");

    fireEvent.click(screen.getByRole("button", { name: "全部" }));
    await waitFor(() => expect(screen.getAllByTestId("strong-card")).toHaveLength(2));
    expect(router.state.location.search).not.toContain("theme=");
  });

  it("W08M-03 opens the full-screen board, drills with tab=valuation and closes", async () => {
    serveMarket();
    const router = renderMobile();

    const firstCard = (await screen.findAllByTestId("industry-card"))[0];
    fireEvent.click(firstCard);

    const dialog = await screen.findByRole("dialog", { name: /半导体 · 成分股/ });
    expect(router.state.location.search).toContain("board=BK1000");
    const rows = await within(dialog).findAllByTestId("board-stock-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("href", "/stocks/600000?tab=valuation");
    expect(firstCard).toHaveAttribute("data-active", "true");

    fireEvent.click(within(dialog).getByRole("button", { name: "关闭成分股" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(router.state.location.search).not.toContain("board=");

    fireEvent.click((await screen.findAllByTestId("industry-card"))[0]);
    const reopened = await screen.findByRole("dialog", { name: /半导体 · 成分股/ });
    fireEvent.click((await within(reopened).findAllByTestId("board-stock-row"))[0]);
    await waitFor(() => expect(router.state.location.pathname).toBe("/stocks/600000"));
    expect(router.state.location.search).toBe("?tab=valuation");
  });
});