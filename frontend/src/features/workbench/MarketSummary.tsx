import { type UseQueryResult, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import type { MarketEnvelope } from "../../api/types";
import {
  marketIndustriesQuery,
  marketOverviewQuery,
  marketStrongStocksQuery,
} from "../../lib/query";
import { DataState } from "../../ui";
import { type DataStateValue, sessionLabel } from "../market/copy";
import styles from "./MarketSummary.module.css";

const SUMMARY_TOP = 3;

function envelopeState<T>(
  query: UseQueryResult<MarketEnvelope<T>>,
): DataStateValue {
  if (query.isPending) {
    return "loading";
  }
  if (query.isError || query.data === undefined) {
    return "error";
  }
  return query.data.status;
}

function changeText(pct: number): string {
  return `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

/** A-share convention: red rises, green falls. */
function changeTone(pct: number): string {
  if (pct > 0) {
    return styles.up;
  }
  return pct < 0 ? styles.down : styles.flat;
}

export function MarketSummary() {
  const overview = useQuery(marketOverviewQuery());
  const industries = useQuery(marketIndustriesQuery(SUMMARY_TOP));
  const strongStocks = useQuery(marketStrongStocksQuery());

  const overviewData = overview.data?.data ?? null;
  const industryRows = (industries.data?.data?.top ?? []).slice(0, SUMMARY_TOP);
  const strongRows = (strongStocks.data?.data?.items ?? []).slice(0, SUMMARY_TOP);

  return (
    <section
      className={styles.panel}
      aria-labelledby="market-summary-title"
      data-testid="market-summary"
    >
      <div className={styles.panelHead}>
        <h2 className={styles.panelTitle} id="market-summary-title">
          市场概览
        </h2>
        <Link className={styles.all} to="/market">
          查看市场
        </Link>
      </div>

      <div className={styles.blocks}>
        <section className={styles.block} data-testid="summary-indices">
          <h3 className={styles.blockTitle}>三大指数</h3>
          <DataState
            state={envelopeState(overview)}
            partial={overview.data?.partial}
            failedBlocks={overview.data?.failed_blocks}
            staleReason={overview.data?.stale_reason}
            onRetry={() => void overview.refetch()}
            skeletonHeight="96px"
          >
            {overviewData === null ? null : (
              <>
                <ul className={styles.rows}>
                  {overviewData.indices.map((index) => (
                    <li
                      className={styles.indexRow}
                      data-testid="summary-index"
                      key={index.code}
                    >
                      <span className={styles.indexName}>{index.name}</span>
                      <span className={styles.indexPrice}>
                        {index.price.toFixed(2)}
                      </span>
                      <span className={changeTone(index.change_pct)}>
                        {changeText(index.change_pct)}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className={styles.session}>
                  {sessionLabel(overviewData.market_session)}
                </p>
              </>
            )}
          </DataState>
        </section>

        <section className={styles.block} data-testid="summary-industries">
          <h3 className={styles.blockTitle}>行业涨幅</h3>
          <DataState
            state={envelopeState(industries)}
            partial={industries.data?.partial}
            failedBlocks={industries.data?.failed_blocks}
            staleReason={industries.data?.stale_reason}
            onRetry={() => void industries.refetch()}
            skeletonHeight="96px"
          >
            <ul className={styles.rows}>
              {industryRows.map((row) => (
                <li
                  className={styles.row}
                  data-testid="summary-industry"
                  key={row.code}
                >
                  <span className={styles.rowName}>{row.name}</span>
                  <span className={changeTone(row.change_pct)}>
                    {changeText(row.change_pct)}
                  </span>
                </li>
              ))}
            </ul>
          </DataState>
        </section>

        <section className={styles.block} data-testid="summary-strong">
          <h3 className={styles.blockTitle}>强势股</h3>
          <DataState
            state={envelopeState(strongStocks)}
            partial={strongStocks.data?.partial}
            failedBlocks={strongStocks.data?.failed_blocks}
            staleReason={strongStocks.data?.stale_reason}
            onRetry={() => void strongStocks.refetch()}
            skeletonHeight="96px"
          >
            <ul className={styles.rows}>
              {strongRows.map((item) => (
                <li className={styles.row} key={item.ticker_code}>
                  <Link
                    className={styles.rowLink}
                    to={`/stocks/${item.ticker_code}`}
                    data-testid="summary-strong-stock"
                  >
                    <span className={styles.rowName}>{item.name}</span>
                    <span className={changeTone(item.change_pct)}>
                      {changeText(item.change_pct)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </DataState>
        </section>
      </div>
    </section>
  );
}