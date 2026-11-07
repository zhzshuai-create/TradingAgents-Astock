import { useQuery } from "@tanstack/react-query";

import { stockIntradayQuery } from "../../lib/query";
import { REFRESH_INTERVALS, usePolling } from "../../lib/useVisibleRefetch";
import { DataState } from "../../ui";
import { IntradayChart } from "../charts/IntradayChart";
import { EMPTY_COPY } from "../market/copy";
import { envelopeState } from "../market/state";
import styles from "./StockPage.module.css";

export interface IntradayTabProps {
  ticker: string;
  date: string;
  onDateChange: (date: string) => void;
}

export function IntradayTab({ ticker, date, onDateChange }: IntradayTabProps) {
  const query = useQuery({
    ...stockIntradayQuery(ticker, date === "" ? null : date),
    ...usePolling(
      date === ""
        ? REFRESH_INTERVALS.stock.intradayToday
        : REFRESH_INTERVALS.stock.intradayHistory,
    ),
  });
  const state = envelopeState(query);
  const data = query.data?.data ?? null;

  return (
    <div className={styles.tabPanel} data-testid="stock-intraday">
      <div className={styles.tabControls}>
        <label className={styles.control}>
          分时日期
          <input
            className={styles.input}
            type="date"
            value={date}
            onChange={(event) => onDateChange(event.target.value)}
          />
        </label>
        <button
          type="button"
          className={styles.textButton}
          data-testid="intraday-latest"
          disabled={date === ""}
          onClick={() => onDateChange("")}
        >
          最新交易日
        </button>
      </div>
      <DataState
        state={state === "ok" && (data?.points.length ?? 0) === 0 ? "empty" : state}
        partial={query.data?.partial ?? false}
        failedBlocks={query.data?.failed_blocks ?? []}
        staleReason={query.data?.stale_reason ?? null}
        onRetry={() => void query.refetch()}
        skeletonHeight="360px"
        emptyTitle={
          date === "" ? "暂无分时数据" : EMPTY_COPY.intradayOutOfRetention
        }
        emptyDescription={
          date === ""
            ? "这只股票暂未返回分时数据。"
            : "数据源只保留最近若干个交易日的分时，请换一个日期。"
        }
      >
        {data === null ? null : (
          <IntradayChart
            data={data}
            asOf={query.data?.as_of ?? null}
            fetchedAt={query.data?.fetched_at ?? null}
          />
        )}
      </DataState>
    </div>
  );
}
