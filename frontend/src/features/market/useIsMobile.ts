import { useEffect, useState } from "react";

import { BREAKPOINTS } from "../../ui/breakpoints";

export const MOBILE_QUERY = `(max-width: ${BREAKPOINTS.md - 1}px)`;

/** Matches the shell breakpoint; market swaps tables for cards below it. */
export function useIsMobile(): boolean {
  const read = () =>
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(MOBILE_QUERY).matches;
  const [mobile, setMobile] = useState(read);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined;
    }
    const query = window.matchMedia(MOBILE_QUERY);
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return mobile;
}