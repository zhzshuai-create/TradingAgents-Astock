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
} from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

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
const CONSTITUENTS_URL = `${ORIGIN}/api/v1/market/industries/BK0475/stocks`;

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

const OVERVIEW: MarketOverviewData = {
  market_session: "trading",
  indices: [
    { code: "000001", name: "上证指数", price: 4012.34, change_pct: 0.42, change_amt: 16.8 },
    { code: "399001", name: "深证成指", price: 13210.5, change_pct: -0.31, change_amt: -41.2 },
    { code: "399006", name: "创业板指", price: 2810.2, change_pct: 1.12, change_amt: 31.1 },
  ],
  northbound: null,
};

const INDUSTRIES: MarketIndustriesData = {
  top: [
    { rank: 1, name: "半导体", code: "BK0475", change_pct: 3.21, up_count: 40, down_count: 2, leader: "中芯国际", leader_change: 8.1 },
    { rank: 2, name: "算力", code: "BK1036", change_pct: 2.84, up_count: 30, down_count: 3, leader: "中际旭创", leader_change: 7.2 },
  ],
  bottom: [
    { rank: 3, name: "煤炭", code: "BK0476", change_pct: -1.42, up_count: 1, down_count: 34, leader: "中国神华", leader_change: 0.4 },
  ],
  total: 3,
};

const CONSTITUENTS: MarketConstituentsData = {
  items: [
    { code: "600000", name: "浦发银行", price: 10.52, change_pct: 1.25 },
    { code: "600015", name: "华夏银行", price: null, change_pct: null },
  ],
};

const STRONG: MarketStrongStocksData = {
  items: [
    { ticker_code: "600519", name: "贵州茅台", reason: "白酒领涨", market: "sh", change_pct: 9.98, change_amt: 156.2, close: 1720.0, turnover_pct: 3.4 },
    { ticker_code: "300750", name: "宁德时代", reason: "储能", market: "sz", change_pct: 6.2, change_amt: 11.1, close: 190.2, turnover_pct: 1.2 },
    { ticker_code: "000858", name: "五粮液", reason: "白酒领涨", market: "sz", change_pct: 4.5, change_amt: 8.1, close: 188.6, turnover_pct: 2.2 },
  ],
};

const NEWS: MarketNewsflashData = {
  items: [
    {
      title: "央行公开市场操作",
      content: "今日开展 1000 亿元逆回购，详情见 https://example.com/news/1。",
      published_at: "2026-11-05T10:05:00+08:00",
    },
    {
      title: "海外市场",
      content: "<script>alert(1)</script> javascript:alert(1)",
      published_at: "2026-11-05T09:58:00+08:00",
    },
  ],
  untrusted: true,
};

let requests: URL[] = [];

function serveMarket(
  options: {
    overview?: MarketEnvelope<MarketOverviewData>;
    industries?: MarketEnvelope<MarketIndustriesData>;
    strong?: MarketEnvelope<MarketStrongStocksData>;
    news?: MarketEnvelope<MarketNewsflashData>;
    constituents?: MarketEnvelope<MarketConstituentsData>;
    overviewStatus?: number;
  } = {},
) {
  requests = [];
  server.use(
    http.get(OVERVIEW_URL, () => {
      requests.push(new URL(OVERVIEW_URL));
      if (options.overviewStatus !== undefined) {
        return HttpResponse.json(
          { error: { code: "internal_error", message: "失败" } },
          { status: options.overviewStatus },
        );
      }
      return HttpResponse.json(options.overview ?? envelope(OVERVIEW));
    }),
    http.get(INDUSTRIES_URL, ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(options.industries ?? envelope(INDUSTRIES));
    }),
    http.get(STRONG_URL, ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(options.strong ?? envelope(STRONG));
    }),
    http.get(NEWS_URL, ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(options.news ?? envelope(NEWS));
    }),
    http.get(CONSTITUENTS_URL, ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(
        options.constituents ?? envelope(CONSTITUENTS),
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

function renderMarket(entry = "/market") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(
    [
      { path: "/market", element: <MarketPage /> },
      { path: "/stocks/:ticker", element: <LocationProbe /> },
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

function section(name: string): HTMLElement {
  return screen.getByRole("region", { name });
}

function overviewCalls(): number {
  return requests.filter(
    (url) => url.pathname === "/api/v1/market/overview",
  ).length;
}

function industriesCalls(): number {
  return requests.filter(
    (url) => url.pathname === "/api/v1/market/industries",
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

describe("W08-01 session bar and index cards", () => {
  it("renders the session, source, update time and three indices", async () => {
    serveMarket();
    renderMarket();
    expect(await screen.findByText("交易中")).toBeInTheDocument();
    expect(screen.getByTestId("market-session")).toHaveTextContent("最近更新");
    expect(screen.getByTestId("market-session")).toHaveTextContent("来源 多源");
    const cards = await screen.findAllByTestId("index-card");
    expect(cards).toHaveLength(3);
    expect(within(cards[0]).getByText("上证指数")).toBeInTheDocument();
    expect(within(cards[0]).getByText("4012.34")).toBeInTheDocument();
    expect(within(cards[0]).getByText("+0.42%")).toBeInTheDocument();
    expect(within(cards[1]).getByText("-0.31%")).toBeInTheDocument();
  });
});

describe("W08-02 industry table", () => {
  it("shows top and bottom rows with leader and breadth", async () => {
    serveMarket();
    renderMarket();
    await screen.findByTestId("industry-table");
    expect(screen.getAllByTestId("industry-row")).toHaveLength(3);
    const banyu = screen.getByRole("button", { name: "半导体" });
    const row = banyu.closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("+3.21%")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("中芯国际")).toBeInTheDocument();
    expect(screen.getByText("涨幅末位")).toBeInTheDocument();
    expect(
      screen.getAllByTestId("industry-row").filter((item) => item.dataset.variant === "bottom"),
    ).toHaveLength(1);
  });
});

describe("W08-03 constituent drawer drill-down", () => {
  it("opens the drawer from a row and links to the stock valuation tab", async () => {
    serveMarket();
    renderMarket();
    fireEvent.click(await screen.findByRole("button", { name: "半导体" }));
    const drawer = await screen.findByRole("dialog", { name: /半导体/ });
    expect(await within(drawer).findAllByTestId("constituent-row")).toHaveLength(2);
    expect(within(drawer).getByText("浦发银行")).toBeInTheDocument();
    const link = within(drawer).getByRole("link", { name: /浦发银行/ });
    expect(link).toHaveAttribute("href", "/stocks/600000?tab=valuation");
    fireEvent.click(link);
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/stocks/600000?tab=valuation",
      ),
    );
  });
});

describe("W08-04 strong stocks", () => {
  it("renders the table, aggregates themes and filters in place", async () => {
    serveMarket();
    renderMarket();
    await screen.findByTestId("strong-table");
    expect(screen.getAllByTestId("strong-row")).toHaveLength(3);
    const chips = screen.getAllByTestId("theme-chip");
    expect(chips.map((chip) => chip.textContent)).toEqual([
      "全部",
      "白酒领涨",
      "储能",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "白酒领涨" }));
    await waitFor(() =>
      expect(screen.getAllByTestId("strong-row")).toHaveLength(2),
    );
    expect(screen.getByText("五粮液")).toBeInTheDocument();
    expect(screen.queryByText("宁德时代")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "全部" }));
    await waitFor(() =>
      expect(screen.getAllByTestId("strong-row")).toHaveLength(3),
    );
  });

  it("uses the non-trading copy for an empty strong block", async () => {
    serveMarket({
      strong: envelope<MarketStrongStocksData>(null, { status: "empty" }),
    });
    renderMarket();
    expect(
      await within(section("强势股")).findByText("非交易日或盘后未更新"),
    ).toBeInTheDocument();
  });
});

describe("W08-05 newsflash", () => {
  it("keeps text inert and only links http(s) URLs", async () => {
    serveMarket();
    renderMarket();
    const list = await screen.findByTestId("newsflash-list");
    expect(within(list).getAllByTestId("newsflash-item")).toHaveLength(2);
    expect(within(list).getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
    expect(list.querySelector("script")).toBeNull();
    expect(list.querySelector('a[href^="javascript:"]')).toBeNull();
    const link = within(list).getByTestId("newsflash-link");
    expect(link).toHaveAttribute("href", "https://example.com/news/1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});

describe("W08-06 states", () => {
  it("shows the stale banner and keeps the data visible", async () => {
    serveMarket({
      overview: envelope(OVERVIEW, {
        status: "stale",
        is_stale: true,
        stale_reason: "ttl_exceeded",
      }),
    });
    renderMarket();
    const region = section("市场概览");
    expect(await within(region).findByTestId("stale-banner")).toHaveTextContent(
      "超过新鲜度阈值",
    );
    expect(within(region).getAllByTestId("index-card")).toHaveLength(3);
  });

  it("marks a partial block and still renders rows", async () => {
    serveMarket({
      industries: envelope(INDUSTRIES, {
        partial: true,
        failed_blocks: ["top"],
      }),
    });
    renderMarket();
    const region = section("行业排名");
    expect(await within(region).findByTestId("partial-notice")).toHaveTextContent(
      "部分数据不可用",
    );
    expect(within(region).getAllByTestId("industry-row").length).toBeGreaterThan(0);
  });

  it("retries only the failed overview block", async () => {
    serveMarket({ overviewStatus: 500 });
    renderMarket();
    const region = section("市场概览");
    fireEvent.click(await within(region).findByRole("button", { name: "重试" }));
    await waitFor(() => {
      const overviewCalls = requests.filter(
        (url) => url.pathname === "/api/v1/market/overview",
      );
      expect(overviewCalls.length).toBeGreaterThanOrEqual(2);
    });
    const industryCalls = requests.filter(
      (url) => url.pathname === "/api/v1/market/industries",
    );
    expect(industryCalls).toHaveLength(1);
  });
});

describe("W08-07 query state", () => {
  it("falls back on illegal values and writes valid controls to the query", async () => {
    serveMarket();
    const { router } = renderMarket(
      "/market?top=999&date=2026-13-01&board=bad&theme=none",
    );
    await screen.findByTestId("industry-table");
    expect(screen.getByLabelText("显示条数")).toHaveValue("20");
    expect(screen.getByLabelText("强势股日期")).toHaveValue("");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getAllByTestId("strong-row")).toHaveLength(3);

    fireEvent.change(screen.getByLabelText("显示条数"), {
      target: { value: "10" },
    });
    await waitFor(() => expect(router.state.location.search).toContain("top=10"));
    fireEvent.change(screen.getByLabelText("强势股日期"), {
      target: { value: "2026-11-04" },
    });
    await waitFor(() =>
      expect(router.state.location.search).toContain("date=2026-11-04"),
    );
    expect(router.state.location.pathname).toBe("/market");
  });
});
describe("REF-01 visible polling", () => {
  it("polls every block at its contract threshold", async () => {
    serveMarket();
    const { client } = renderMarket();
    await screen.findByTestId("industry-table");
    const cache = client.getQueryCache();
    const intervalOf = (queryKey: unknown[]) =>
      cache.find({ queryKey })?.observers[0]?.options.refetchInterval;

    expect(intervalOf(["market", "overview"])).toBe(10_000);
    expect(intervalOf(["market", "industries", 20])).toBe(300_000);
    expect(intervalOf(["market", "strong", null])).toBe(3_600_000);
    expect(intervalOf(["market", "newsflash", 30])).toBe(120_000);
  });
});

describe("REF-02 hidden tab", () => {
  it("drops to one minute and refetches at once on return", async () => {
    serveMarket();
    const { client } = renderMarket();
    await screen.findByTestId("industry-table");
    const overviewKey = ["market", "overview"];
    const intervalOf = () =>
      client
        .getQueryCache()
        .find({ queryKey: overviewKey })?.observers[0]?.options
        .refetchInterval;
    expect(intervalOf()).toBe(10_000);

    setVisibility("hidden");
    await waitFor(() => expect(intervalOf()).toBe(60_000));
    expect(overviewCalls()).toBe(1);

    const before = overviewCalls();
    setVisibility("visible");
    await waitFor(() => expect(intervalOf()).toBe(10_000));
    await waitFor(() => expect(overviewCalls()).toBe(before + 1));
  });
});

describe("REF-03 manual refresh", () => {
  it("sends exactly one group for a burst of clicks", async () => {
    serveMarket();
    renderMarket();
    await screen.findByTestId("industry-table");
    const overviewBefore = overviewCalls();
    const industriesBefore = industriesCalls();

    const button = screen.getByTestId("market-refresh");
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(overviewCalls()).toBe(overviewBefore);

    await waitFor(() => expect(overviewCalls()).toBe(overviewBefore + 1), {
      timeout: 2000,
    });
    expect(industriesCalls()).toBe(industriesBefore + 1);
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(overviewCalls()).toBe(overviewBefore + 1);
    expect(industriesCalls()).toBe(industriesBefore + 1);
  });
});

describe("P5-07 screen reader semantics", () => {
  it("SR-06 labels both tables and marks each row header", async () => {
    serveMarket();
    renderMarket();

    const industry = await screen.findByTestId("industry-table");
    expect(industry).toHaveAccessibleName("行业排名");
    expect(industry.querySelector("caption")).toHaveTextContent("行业排名");
    const industryHeaders = industry.querySelectorAll("tbody th[scope='row']");
    expect(industryHeaders).toHaveLength(3);
    expect(industryHeaders[0]).toHaveTextContent("半导体");
    for (const cell of Array.from(industry.querySelectorAll("th"))) {
      expect(cell).toHaveAttribute("scope");
    }

    const strong = await screen.findByTestId("strong-table");
    expect(strong).toHaveAccessibleName("强势股");
    expect(strong.querySelector("caption")).toHaveTextContent("强势股");
    expect(strong.querySelectorAll("tbody th[scope='row']")).toHaveLength(3);
    for (const cell of Array.from(strong.querySelectorAll("th"))) {
      expect(cell).toHaveAttribute("scope");
    }
  });

  it("SR-04 announces a finished manual refresh and nothing else", async () => {
    serveMarket();
    renderMarket();
    await screen.findByTestId("industry-table");

    const status = screen.getByTestId("market-refresh-status");
    expect(status).toHaveAttribute("role", "status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status.textContent).toBe("");

    fireEvent.click(screen.getByTestId("market-refresh"));
    await waitFor(
      () => {
        expect(status.textContent).toMatch(/已刷新，时间 \d{2}:\d{2}:\d{2}/);
      },
      { timeout: 2000 },
    );
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });
});

describe("REF-04 leaving the page", () => {
  it("clears the poll timer when the route unmounts", async () => {
    serveMarket();
    const { router } = renderMarket();
    await screen.findByTestId("industry-table");
    await act(async () => {
      await router.navigate("/stocks/600000");
    });
    expect(screen.queryByTestId("page-market")).toBeNull();
    const settled = overviewCalls();

    vi.useFakeTimers();
    try {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(70_000);
      });
    } finally {
      vi.useRealTimers();
    }
    expect(overviewCalls()).toBe(settled);
  });
});

describe("CTX-01 market to stock and back", () => {
  it("restores industry, topN and date from the query", async () => {
    serveMarket();
    const { router } = renderMarket("/market?top=10&date=2026-11-04");
    await screen.findByTestId("industry-table");
    fireEvent.click(screen.getByRole("button", { name: "半导体" }));
    const drawer = await screen.findByRole("dialog", { name: /半导体/ });
    fireEvent.click(
      await within(drawer).findByRole("link", { name: /浦发银行/ }),
    );
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/stocks/600000"),
    );
    expect(router.state.location.search).toBe("?tab=valuation");

    await act(async () => {
      await router.navigate(-1);
    });
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/market"),
    );
    const search = router.state.location.search;
    expect(search).toContain("top=10");
    expect(search).toContain("date=2026-11-04");
    expect(search).toContain("board=BK0475");
    expect(
      await screen.findByRole("dialog", { name: /半导体/ }),
    ).toBeInTheDocument();
  });
});
