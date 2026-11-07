/** One polling implementation for every page (p4-backlog D9, P4-11). */

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";

import { MARKET_STALE_MS, STOCK_STALE_MS } from "./query";

/** While the tab is hidden every poll drops to at most one beat per minute. */
export const HIDDEN_POLL_MS = 60_000;

/**
 * The only poll interval table: it reuses the contract ``stale_after`` values
 * so a page can never poll faster than the server promises fresh data.
 * ``stockReports`` is absent on purpose: the contract sets no staleness for it.
 */
export const REFRESH_INTERVALS = {
  market: {
    overview: MARKET_STALE_MS.overview,
    industries: MARKET_STALE_MS.industries,
    strongStocks: MARKET_STALE_MS.strongStocks,
    newsflash: MARKET_STALE_MS.newsflash,
  },
  stock: {
    snapshot: STOCK_STALE_MS.snapshot,
    kline: STOCK_STALE_MS.kline,
    intradayToday: STOCK_STALE_MS.intradayToday,
    intradayHistory: STOCK_STALE_MS.intradayHistory,
    news: STOCK_STALE_MS.news,
    fundFlow: STOCK_STALE_MS.fundFlow,
  },
} as const;

const VISIBILITY_EVENT = "visibilitychange";
const subscribers = new Set<() => void>();
let listening = false;

function readVisible(): boolean {
  return (
    typeof document === "undefined" || document.visibilityState !== "hidden"
  );
}

function notify(): void {
  for (const subscriber of subscribers) {
    subscriber();
  }
}

/** The listener is attached once per module and shared by every hook caller. */
function subscribe(callback: () => void): () => void {
  subscribers.add(callback);
  if (!listening && typeof document !== "undefined") {
    listening = true;
    document.addEventListener(VISIBILITY_EVENT, notify);
  }
  return () => {
    subscribers.delete(callback);
  };
}

export function usePageVisible(): boolean {
  return useSyncExternalStore(subscribe, readVisible, () => true);
}

export interface PollingOptions {
  refetchInterval: number | false;
  refetchIntervalInBackground: boolean;
}

/**
 * Interval for one query. Hidden tabs keep the timer alive (TanStack pauses
 * background intervals by default) but never poll faster than one minute.
 */
export function usePolling(interval: number | false): PollingOptions {
  const visible = usePageVisible();
  if (interval === false) {
    return { refetchInterval: false, refetchIntervalInBackground: false };
  }
  return {
    refetchInterval: visible ? interval : Math.max(interval, HIDDEN_POLL_MS),
    refetchIntervalInBackground: true,
  };
}

export interface VisibleRefetch {
  /** Refetch every active query under ``scope`` once. */
  refreshNow: () => Promise<void>;
}

/**
 * Page-level half of the pair: a hidden -> visible transition refetches every
 * active query under ``scope`` at once. ``scope`` must be a stable constant so
 * the listener is not re-bound on every render.
 */
export function useVisibleRefetch(
  scope: readonly unknown[],
): VisibleRefetch {
  const client = useQueryClient();
  const visible = usePageVisible();
  const wasHidden = useRef(false);

  useEffect(() => {
    if (!visible) {
      wasHidden.current = true;
      return;
    }
    if (!wasHidden.current) {
      return;
    }
    wasHidden.current = false;
    void client.invalidateQueries({
      queryKey: scope,
      refetchType: "active",
    });
  }, [client, scope, visible]);

  const refreshNow = useCallback(
    () =>
      client
        .invalidateQueries({ queryKey: scope, refetchType: "active" })
        .then(() => undefined),
    [client, scope],
  );

  return { refreshNow };
}
