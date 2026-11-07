import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { metaOptionsQuery } from "../lib/query";
import { Button } from "../ui";
import { JournalFrame } from "../features/journal/JournalFrame";
import styles from "../features/journal/JournalPage.module.css";
import { JournalStarting } from "../features/journal/JournalStarting";
import { JournalUnavailable } from "../features/journal/JournalUnavailable";
import { journalOrigin } from "../features/journal/useJournalThemeBridge";

export const JOURNAL_RETRY_INTERVAL_MS = 2_000;
export const JOURNAL_RETRY_LIMIT_MS = 30_000;

export function JournalPage() {
  const { data, isPending, refetch } = useQuery(metaOptionsQuery);
  const [starting, setStarting] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef(0);
  const refetchRef = useRef(refetch);
  refetchRef.current = refetch;

  const journal = data?.journal;
  const entryUrl = journal?.entry_url ?? null;
  const available = journal?.available === true && journalOrigin(entryUrl) !== null;

  const startRetry = useCallback(() => {
    startedAt.current = Date.now();
    setElapsed(0);
    setStarting(true);
    void refetchRef.current();
  }, []);

  const cancelRetry = useCallback(() => setStarting(false), []);

  useEffect(() => {
    if (starting && available) {
      setStarting(false);
    }
  }, [starting, available]);

  useEffect(() => {
    if (!starting) {
      return undefined;
    }
    const poll = window.setInterval(() => {
      void refetchRef.current();
    }, JOURNAL_RETRY_INTERVAL_MS);
    const deadline = window.setTimeout(() => {
      setStarting(false);
    }, JOURNAL_RETRY_LIMIT_MS);
    return () => {
      window.clearInterval(poll);
      window.clearTimeout(deadline);
    };
  }, [starting]);

  useEffect(() => {
    if (!starting) {
      return undefined;
    }
    const ticker = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt.current) / 1000));
    }, 1_000);
    return () => window.clearInterval(ticker);
  }, [starting]);

  // Only the iframe scrolls while the journal is available.
  useEffect(() => {
    if (!available) {
      return undefined;
    }
    const main = document.getElementById("main-content");
    if (main === null) {
      return undefined;
    }
    const previous = main.style.overflowY;
    main.style.overflowY = "hidden";
    main.scrollTop = 0;
    return () => {
      main.style.overflowY = previous;
    };
  }, [available]);

  if (available && entryUrl !== null) {
    return (
      <section
        className={styles.page}
        data-testid="page-journal"
        data-view="available"
      >
        <JournalFrame entryUrl={entryUrl} />
      </section>
    );
  }

  let body: ReactNode;
  if (starting) {
    body = (
      <JournalStarting
        elapsedSeconds={elapsed}
        entryUrl={entryUrl}
        onCancel={cancelRetry}
      />
    );
  } else if (journal !== undefined) {
    body = (
      <JournalUnavailable
        reason={journal.reason}
        entryUrl={entryUrl}
        onRetry={startRetry}
      />
    );
  } else if (isPending) {
    body = <p className={styles.lead}>正在读取日志状态…</p>;
  } else {
    body = (
      <>
        <p className={styles.lead} role="alert">
          暂时无法读取日志状态，请确认后端服务可用后重试。
        </p>
        <div className={styles.actions}>
          <Button variant="secondary" onClick={() => void refetch()}>
            重试
          </Button>
        </div>
        <p className={styles.isolation} data-testid="journal-isolation">
          本系统不会读取或修改交易日志的数据。
        </p>
      </>
    );
  }

  return (
    <section
      className={styles.page}
      data-testid="page-journal"
      data-view={starting ? "starting" : "unavailable"}
    >
      <header className={styles.head}>
        <h1 className={styles.title}>交易日志</h1>
      </header>
      {body}
    </section>
  );
}
