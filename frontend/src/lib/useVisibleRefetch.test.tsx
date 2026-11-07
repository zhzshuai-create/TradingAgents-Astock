import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setPreferences } from "./preferences";
import {
  HIDDEN_POLL_MS,
  REFRESH_INTERVALS,
  usePageVisible,
  usePolling,
  useVisibleRefetch,
} from "./useVisibleRefetch";
import { REFRESH_DEBOUNCE_MS, useDebouncedRefresh } from "./useDebouncedRefresh";

const PROBE_SCOPE = ["probe"] as const;

function setVisibility(value: "visible" | "hidden") {
  act(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => value,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

function restoreVisibility() {
  delete (document as { visibilityState?: unknown }).visibilityState;
}

beforeEach(() => {
  restoreVisibility();
});

afterEach(() => {
  restoreVisibility();
  localStorage.clear();
});

describe("REF-01 contract interval table", () => {
  it("polls at the contract stale_after values", () => {
    expect(REFRESH_INTERVALS.market.overview).toBe(10_000);
    expect(REFRESH_INTERVALS.market.newsflash).toBe(120_000);
    expect(REFRESH_INTERVALS.market.industries).toBe(300_000);
    expect(REFRESH_INTERVALS.stock.snapshot).toBe(60_000);
    expect(REFRESH_INTERVALS.stock.intradayToday).toBe(30_000);
  });

  it("degrades hidden tabs to one beat per minute but never below stale_after", () => {
    setVisibility("visible");
    const visible = renderHook(() => usePolling(REFRESH_INTERVALS.market.overview));
    expect(visible.result.current).toEqual({
      refetchInterval: 10_000,
      refetchIntervalInBackground: true,
    });

    setVisibility("hidden");
    expect(visible.result.current.refetchInterval).toBe(HIDDEN_POLL_MS);

    const slow = renderHook(() => usePolling(REFRESH_INTERVALS.market.industries));
    expect(slow.result.current.refetchInterval).toBe(300_000);

    const off = renderHook(() => usePolling(false));
    expect(off.result.current.refetchInterval).toBe(false);
  });
});

describe("REF-02 return to foreground", () => {
  it("refetches every active query under the page scope once", async () => {
    let calls = 0;
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: Infinity } },
    });

    function Page() {
      useVisibleRefetch(PROBE_SCOPE);
      const query = useQuery({
        queryKey: ["probe", "overview"],
        queryFn: async () => {
          calls += 1;
          return calls;
        },
      });
      const visible = usePageVisible();
      return (
        <span data-testid="probe" data-visible={String(visible)}>
          {query.data}
        </span>
      );
    }

    render(
      <QueryClientProvider client={client}>
        <Page />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("1"));
    expect(screen.getByTestId("probe")).toHaveAttribute("data-visible", "true");

    setVisibility("hidden");
    expect(screen.getByTestId("probe")).toHaveAttribute("data-visible", "false");
    expect(calls).toBe(1);

    setVisibility("visible");
    await waitFor(() => expect(calls).toBe(2));
  });
});

describe("P5-REF refresh profiles", () => {
  it("standard keeps the contract interval, relaxed doubles, manual stops", () => {
    setVisibility("visible");
    const hook = renderHook(() => usePolling(REFRESH_INTERVALS.market.overview));
    expect(hook.result.current.refetchInterval).toBe(10_000);

    act(() => {
      setPreferences({ refresh: "relaxed" });
    });
    expect(hook.result.current.refetchInterval).toBe(20_000);

    act(() => {
      setPreferences({ refresh: "manual" });
    });
    expect(hook.result.current).toEqual({
      refetchInterval: false,
      refetchIntervalInBackground: false,
    });

    act(() => {
      setPreferences({ refresh: "standard" });
    });
    expect(hook.result.current.refetchInterval).toBe(10_000);
  });

  it("hidden tabs never poll faster than one minute in any profile", () => {
    setVisibility("visible");
    const fast = renderHook(() => usePolling(REFRESH_INTERVALS.market.overview));
    const slow = renderHook(() =>
      usePolling(REFRESH_INTERVALS.market.industries),
    );

    act(() => {
      setPreferences({ refresh: "relaxed" });
    });
    setVisibility("hidden");
    expect(fast.result.current.refetchInterval).toBe(HIDDEN_POLL_MS);
    expect(slow.result.current.refetchInterval).toBe(600_000);

    act(() => {
      setPreferences({ refresh: "manual" });
    });
    expect(fast.result.current.refetchInterval).toBe(false);
    expect(slow.result.current.refetchInterval).toBe(false);
    expect(fast.result.current.refetchIntervalInBackground).toBe(false);
  });

  it("manual skips the foreground refetch but keeps refreshNow", async () => {
    act(() => {
      setPreferences({ refresh: "manual" });
    });
    let calls = 0;
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: Infinity } },
    });

    const { result } = renderHook(
      () => {
        const refetch = useVisibleRefetch(PROBE_SCOPE);
        const query = useQuery({
          queryKey: ["probe", "manual"],
          queryFn: async () => {
            calls += 1;
            return calls;
          },
        });
        return { refetch, data: query.data };
      },
      {
        wrapper: ({ children }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );
    await waitFor(() => expect(result.current.data).toBe(1));

    setVisibility("hidden");
    setVisibility("visible");
    await act(async () => {
      await Promise.resolve();
    });
    expect(calls).toBe(1);

    await act(async () => {
      await result.current.refetch.refreshNow();
    });
    await waitFor(() => expect(result.current.data).toBe(2));
  });
});

describe("REF-03 manual refresh debounce", () => {
  it("collapses a burst of clicks into one refresh after the window", async () => {
    vi.useFakeTimers();
    try {
      const refresh = vi.fn();
      const { result } = renderHook(() => useDebouncedRefresh(refresh));

      act(() => {
        result.current();
        result.current();
        result.current();
      });
      expect(refresh).not.toHaveBeenCalled();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(REFRESH_DEBOUNCE_MS);
      });
      expect(refresh).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(REFRESH_DEBOUNCE_MS * 2);
      });
      expect(refresh).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("drops a pending refresh when the page unmounts", async () => {
    vi.useFakeTimers();
    try {
      const refresh = vi.fn();
      const { result, unmount } = renderHook(() => useDebouncedRefresh(refresh));
      act(() => {
        result.current();
      });
      unmount();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(REFRESH_DEBOUNCE_MS * 2);
      });
      expect(refresh).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});
