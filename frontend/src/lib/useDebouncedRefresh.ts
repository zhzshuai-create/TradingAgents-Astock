/** Manual refresh shared by the market and stock pages (p4-backlog D9). */

import { useCallback, useEffect, useRef } from "react";

/** A second click inside this window replaces the pending refresh. */
export const REFRESH_DEBOUNCE_MS = 500;

/**
 * Trailing debounce: one click sends one refresh group after the window
 * closes, and a burst of clicks still sends exactly one group.
 */
export function useDebouncedRefresh(
  refresh: () => unknown,
  delay = REFRESH_DEBOUNCE_MS,
): () => void {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef(refresh);

  useEffect(() => {
    latest.current = refresh;
  }, [refresh]);

  useEffect(
    () => () => {
      if (timer.current !== null) {
        clearTimeout(timer.current);
        timer.current = null;
      }
    },
    [],
  );

  return useCallback(() => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
    }
    timer.current = setTimeout(() => {
      timer.current = null;
      void latest.current();
    }, delay);
  }, [delay]);
}
