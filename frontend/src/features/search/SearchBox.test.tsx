import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import {
  createMemoryRouter,
  RouterProvider,
  useLocation,
} from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import type { MarketEnvelope, MarketSearchData } from "../../api/types";
import { SearchBox } from "./SearchBox";
import { SEARCH_DEBOUNCE_MS, SEARCH_LIMIT } from "./useStockSearch";

const ORIGIN = "http://localhost:3000";
const SEARCH_URL = `${ORIGIN}/api/v1/market/search`;

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function envelope(
  items: MarketSearchData["items"],
  status: MarketEnvelope<MarketSearchData>["status"] = "ok",
): MarketEnvelope<MarketSearchData> {
  return {
    schema_version: "market-envelope-v1",
    status,
    source: "static",
    as_of: "2026-11-05T09:00:00+08:00",
    fetched_at: "2026-11-05T09:00:00+08:00",
    is_stale: false,
    stale_reason: null,
    error_code: null,
    error_message: null,
    partial: false,
    failed_blocks: [],
    data: {
      items,
      truncated: false,
    },
  };
}

const ITEMS: MarketSearchData["items"] = [
  { ticker_code: "000629", ticker_name: "钒钛股份", market: "sz" },
  { ticker_code: "600519", ticker_name: "贵州茅台", market: "sh" },
];

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">{`${location.pathname}${location.search}`}</output>
  );
}

function renderAt(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(
    [
      { path: "/market", element: <SearchBox /> },
      {
        path: "/workbench",
        element: (
          <>
            <SearchBox />
            <LocationProbe />
          </>
        ),
      },
      { path: "/stocks/:ticker", element: <LocationProbe /> },
    ],
    { initialEntries: [path] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

function input() {
  return screen.getByLabelText("搜索股票");
}

describe("WEB-07 stock search", () => {
  it("debounces rapid typing into one request with limit 10", async () => {
    const calls: { q: string; limit: string | null }[] = [];
    server.use(
      http.get(SEARCH_URL, ({ request }) => {
        const params = new URL(request.url).searchParams;
        calls.push({ q: params.get("q") ?? "", limit: params.get("limit") });
        return HttpResponse.json(envelope(ITEMS));
      }),
    );

    renderAt("/market");
    const field = input();
    for (const value of ["6", "60", "600", "6005", "60051", "600519"]) {
      fireEvent.change(field, { target: { value } });
    }

    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0]).toEqual({ q: "600519", limit: String(SEARCH_LIMIT) });

    await new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS + 150));
    expect(calls.length).toBe(1);
  });

  it("selects with the keyboard and executes on Enter", async () => {
    const user = userEvent.setup();
    server.use(
      http.get(SEARCH_URL, () => HttpResponse.json(envelope(ITEMS))),
    );

    const router = renderAt("/market");
    await user.type(input(), "股份");

    const options = await screen.findAllByRole("option");
    expect(options).toHaveLength(2);

    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    expect(options[1]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(input(), { key: "Enter" });
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/stocks/600519"),
    );
    expect(router.state.location.search).toBe("");
  });

  it("wraps with ArrowUp and Enter chooses the highlighted item", async () => {
    const user = userEvent.setup();
    server.use(
      http.get(SEARCH_URL, () => HttpResponse.json(envelope(ITEMS))),
    );

    const router = renderAt("/market");
    await user.type(input(), "股份");
    await screen.findAllByRole("option");

    fireEvent.keyDown(input(), { key: "ArrowUp" });
    const options = screen.getAllByRole("option");
    expect(options[1]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(input(), { key: "Enter" });
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/stocks/600519"),
    );
  });

  it("shows the empty copy when nothing matches", async () => {
    const user = userEvent.setup();
    server.use(
      http.get(SEARCH_URL, () => HttpResponse.json(envelope([]))),
    );

    renderAt("/market");
    await user.type(input(), "999999");

    expect(
      await screen.findByText("没有找到，检查代码或名称"),
    ).toBeInTheDocument();
  });

  it("shows a retry button after a failed request and recovers", async () => {
    const user = userEvent.setup();
    let calls = 0;
    server.use(
      http.get(SEARCH_URL, () => {
        calls += 1;
        if (calls === 1) {
          return HttpResponse.json(
            {
              error: {
                code: "internal_error",
                message: "服务暂时不可用",
                request_id: "req_search",
              },
            },
            { status: 500 },
          );
        }
        return HttpResponse.json(envelope(ITEMS));
      }),
    );

    renderAt("/market");
    await user.type(input(), "股份");

    expect(await screen.findByText("服务暂时不可用")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText("钒钛股份")).toBeInTheDocument();
    expect(calls).toBe(2);
  });

  it("opens the launcher from the workbench instead of the stock page", async () => {
    server.use(
      http.get(SEARCH_URL, () => HttpResponse.json(envelope([]))),
    );

    const router = renderAt("/workbench");
    fireEvent.change(input(), { target: { value: "600519" } });
    fireEvent.submit(screen.getByRole("search"));

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/workbench?launch=1&ticker=600519",
      ),
    );
    expect(router.state.location.pathname).toBe("/workbench");
  });

  it("falls back to the first result when Enter has no selection", async () => {
    const user = userEvent.setup();
    server.use(
      http.get(SEARCH_URL, () => HttpResponse.json(envelope(ITEMS))),
    );

    const router = renderAt("/market");
    await user.type(input(), "股份");
    await screen.findAllByRole("option");

    fireEvent.keyDown(input(), { key: "Enter" });
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/stocks/000629"),
    );
  });

  it("selects a result with the mouse", async () => {
    const user = userEvent.setup();
    server.use(
      http.get(SEARCH_URL, () => HttpResponse.json(envelope(ITEMS))),
    );

    const router = renderAt("/market");
    await user.type(input(), "股份");
    const options = await screen.findAllByRole("option");

    fireEvent.mouseDown(options[1]);
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/stocks/600519"),
    );
  });
});
