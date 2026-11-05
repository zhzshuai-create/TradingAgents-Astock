/** 250ms debounced stock search (api-v1.md 3.1). */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { displayErrorMessage } from "../../api/errors";
import { searchStocks } from "../../api/market";
import type { MarketSearchItem } from "../../api/types";
import { queryKeys } from "../../lib/query";

export const SEARCH_DEBOUNCE_MS = 250;
export const SEARCH_LIMIT = 10;
export const SEARCH_MIN_CHARS = 1;

function useDebouncedValue(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    if (value.trim() === "") {
      setDebounced("");
      return;
    }
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}

export interface StockSearchState {
  /** The query whose results are in `items`. */
  query: string;
  items: MarketSearchItem[];
  isLoading: boolean;
  error: string | null;
  truncated: boolean;
  stale: boolean;
  retry: () => void;
}

export function useStockSearch(input: string): StockSearchState {
  const query = useDebouncedValue(input.trim(), SEARCH_DEBOUNCE_MS);
  const enabled = query.length >= SEARCH_MIN_CHARS;

  const result = useQuery({
    queryKey: queryKeys.marketSearch(query),
    queryFn: ({ signal }) => searchStocks(query, SEARCH_LIMIT, signal),
    enabled,
    staleTime: 0,
    gcTime: 60_000,
    retry: false,
  });

  const envelope = result.data;
  const envelopeFailed = envelope?.status === "error";

  return {
    query,
    items: envelope?.data?.items ?? [],
    isLoading: enabled && result.isPending,
    error: envelopeFailed
      ? (envelope?.error_message ?? "搜索服务暂时不可用")
      : result.error
        ? displayErrorMessage(result.error)
        : null,
    truncated: envelope?.data?.truncated ?? false,
    stale: envelope?.status === "stale",
    retry: () => {
      void result.refetch();
    },
  };
}
