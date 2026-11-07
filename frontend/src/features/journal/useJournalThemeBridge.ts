/** Theme messages stay inside the journal origin; every receipt is checked. */

import { useCallback, useEffect, useRef, type RefObject } from "react";

export const JOURNAL_THEME_MESSAGE = "astock-theme-request";

/** ``entry_url`` must be http/https before it may become a frame origin. */
export function journalOrigin(entryUrl: string | null | undefined): string | null {
  if (entryUrl === null || entryUrl === undefined || entryUrl === "") {
    return null;
  }
  try {
    const url = new URL(entryUrl);
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.origin
      : null;
  } catch {
    return null;
  }
}

export interface JournalThemeBridge {
  frameRef: RefObject<HTMLIFrameElement | null>;
  sendTheme: () => void;
}

export function useJournalThemeBridge(
  entryUrl: string | null,
): JournalThemeBridge {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const origin = journalOrigin(entryUrl);

  const sendTheme = useCallback(() => {
    const frame = frameRef.current;
    if (origin === null || frame === null) {
      return;
    }
    const theme =
      document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    frame.contentWindow?.postMessage(
      { type: JOURNAL_THEME_MESSAGE, theme },
      origin,
    );
  }, [origin]);

  useEffect(() => {
    if (origin === null) {
      return undefined;
    }
    const handleMessage = (event: MessageEvent<unknown>) => {
      const frame = frameRef.current;
      if (event.origin !== origin) {
        return;
      }
      if (frame === null || event.source !== frame.contentWindow) {
        return;
      }
      const data = event.data as { type?: unknown } | null | undefined;
      if (data?.type !== JOURNAL_THEME_MESSAGE) {
        return;
      }
      sendTheme();
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [origin, sendTheme]);

  useEffect(() => {
    if (origin === null) {
      return undefined;
    }
    const observer = new MutationObserver(() => sendTheme());
    observer.observe(document.documentElement, {
      attributeFilter: ["data-theme"],
      attributes: true,
    });
    return () => observer.disconnect();
  }, [origin, sendTheme]);

  return { frameRef, sendTheme };
}
