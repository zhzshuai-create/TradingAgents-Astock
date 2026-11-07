import { useQuery } from "@tanstack/react-query";

import type { KlinePeriod } from "../../api/types";
import { stockKlineQuery } from "../../lib/query";
import { REFRESH_INTERVALS, usePolling } from "../../lib/useVisibleRefetch";
import { DataState } from "../../ui";
import { KLineChart } from "../charts/KLineChart";
import { envelopeState } from "../market/state";
import { KLINE_LIMIT } from "./stockParams";
import styles from "./StockPage.module.css";

export interface KLineTabProps {
  ticker: string;
  period: KlinePeriod;
  onPeriodChange: (period: KlinePeriod) => void;
  mobile?: boolean;
}

export function KLineTab({
  ticker,
  period,
  onPeriodChange,
  mobile = false,
}: KLineTabProps) {
  const query = useQuery({
    ...stockKlineQuery(ticker, period, KLINE_LIMIT),
    ...usePolling(REFRESH_INTERVALS.stock.kline),
  });
  const state = envelopeState(query);
  const data = query.data?.data ?? null;

  return (
    <div className={styles.tabPanel} data-testid="stock-kline">
      <DataState
        state={state === "ok" && (data?.bars.length ?? 0) === 0 ? "empty" : state}
        partial={query.data?.partial ?? false}
        failedBlocks={query.data?.failed_blocks ?? []}
        staleReason={query.data?.stale_reason ?? null}
        onRetry={() => void query.refetch()}
        skeletonHeight="420px"
        emptyTitle="暂无 K 线数据"
        emptyDescription="这只股票在当前周期没有可用的 K 线。"
      >
        {data === null ? null : (
          <KLineChart
            data={data}
            period={period}
            onPeriodChange={onPeriodChange}
            asOf={query.data?.as_of ?? null}
            fetchedAt={query.data?.fetched_at ?? null}
            mobile={mobile}
          />
        )}
      </DataState>
    </div>
  );
}
