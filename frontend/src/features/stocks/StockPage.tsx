import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../../api/errors";
import { stockSnapshotQuery } from "../../lib/query";
import { InvalidTickerPage } from "../../pages/InvalidTickerPage";
import { LauncherDialog } from "../launcher/LauncherDialog";
import { envelopeState } from "../market/state";
import { useIsMobile } from "../market/useIsMobile";
import { IntradayTab } from "./IntradayTab";
import { KLineTab } from "./KLineTab";
import { NewsTab } from "./NewsTab";
import { ReportsTab } from "./ReportsTab";
import { StockActionBar } from "./StockActionBar";
import { StockHeader } from "./StockHeader";
import { StockTabs } from "./StockTabs";
import {
  marketOf,
  parseStockSearch,
  toStockSearch,
  type StockState,
  type StockTab,
} from "./stockParams";
import { useStockActions } from "./useStockActions";
import { ValuationTab } from "./ValuationTab";
import styles from "./StockPage.module.css";

/** A 400 with `details.field="ticker"` means the name table has no such code. */
export function isTickerRejected(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 400 &&
    error.details.field === "ticker"
  );
}

export interface StockPageProps {
  ticker: string;
}

export function StockPage({ ticker }: StockPageProps) {
  const [params, setParams] = useSearchParams();
  const state = parseStockSearch(params.toString());
  const isMobile = useIsMobile();
  const snapshot = useQuery(stockSnapshotQuery(ticker));
  const snapshotData = snapshot.data?.data ?? null;
  const quote = snapshotData?.quote ?? null;
  const actions = useStockActions(ticker, quote?.name ?? null);

  // Tab scroll memory lives for this mount only, so a refresh starts at the top.
  const scrollMemory = useRef<Record<string, number>>({});
  const previousTab = useRef<StockTab | null>(null);
  useEffect(() => {
    const main = document.getElementById("main-content");
    if (main === null) {
      return;
    }
    const previous = previousTab.current;
    if (previous !== null && previous !== state.tab) {
      main.scrollTop = scrollMemory.current[state.tab] ?? 0;
    }
    previousTab.current = state.tab;
  }, [state.tab]);

  if (isTickerRejected(snapshot.error)) {
    return <InvalidTickerPage ticker={ticker} reason="unresolved" />;
  }

  function patch(next: Partial<StockState>) {
    if (next.tab !== undefined && next.tab !== state.tab) {
      // Read before the swap: the shorter tab could clamp scrollTop to 0.
      const main = document.getElementById("main-content");
      scrollMemory.current[state.tab] = main?.scrollTop ?? 0;
    }
    setParams(toStockSearch({ ...state, ...next }), { replace: true });
  }

  return (
    <section className={styles.page} data-testid="page-stock">
      <StockHeader
        ticker={ticker}
        market={marketOf(ticker)}
        quote={quote}
        state={envelopeState(snapshot)}
        source={snapshot.data?.source ?? null}
        asOf={snapshot.data?.as_of ?? null}
        fetchedAt={snapshot.data?.fetched_at ?? null}
        partial={snapshot.data?.partial ?? false}
        failedBlocks={snapshot.data?.failed_blocks ?? []}
        staleReason={snapshot.data?.stale_reason ?? null}
        onRetry={() => void snapshot.refetch()}
        primary={actions.primary}
        mobile={isMobile}
      />

      <StockTabs
        active={state.tab}
        onChange={(tab) => patch({ tab })}
      />

      <div
        className={styles.panel}
        id="stock-tab-panel"
        role="tabpanel"
        aria-labelledby={`stock-tab-${state.tab}`}
        data-testid="stock-tab-panel"
        data-tab={state.tab}
      >
        {state.tab === "valuation" ? (
          <ValuationTab
            ticker={ticker}
            snapshot={snapshotData}
            snapshotState={envelopeState(snapshot)}
            onRetrySnapshot={() => void snapshot.refetch()}
          />
        ) : null}
        {state.tab === "kline" ? (
          <KLineTab
            ticker={ticker}
            period={state.period}
            onPeriodChange={(period) => patch({ period })}
            mobile={isMobile}
          />
        ) : null}
        {state.tab === "intraday" ? (
          <IntradayTab
            ticker={ticker}
            date={state.date}
            onDateChange={(date) => patch({ date })}
          />
        ) : null}
        {state.tab === "news" ? <NewsTab ticker={ticker} /> : null}
        {state.tab === "reports" ? <ReportsTab ticker={ticker} /> : null}
      </div>

      {isMobile ? <StockActionBar primary={actions.primary} /> : null}

      {actions.launcherOpen ? (
        <LauncherDialog
          open
          initialTicker={actions.initialTicker}
          onClose={actions.closeLauncher}
          onCreated={actions.created}
        />
      ) : null}
    </section>
  );
}
