import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import type { ReportSummary } from "../../api/types";
import { recentReportsQuery } from "../../lib/query";
import { Badge, DataState } from "../../ui";
import type { DataStateValue } from "../market/copy";
import { formatGeneratedAt, REPORT_RATING_META } from "../reports/format";
import styles from "./RecentReports.module.css";

export const RECENT_REPORTS_LIMIT = 3;

export interface RecentTicker {
  code: string;
  name: string;
}

function tickerName(report: ReportSummary): string {
  return report.meta.ticker_name ?? report.meta.ticker_code;
}

/** Deduplicates the tickers already present in the latest report rows. */
export function uniqueTickers(reports: ReportSummary[]): RecentTicker[] {
  const seen = new Set<string>();
  const tickers: RecentTicker[] = [];
  for (const report of reports) {
    const { ticker_code: code } = report.meta;
    if (seen.has(code)) {
      continue;
    }
    seen.add(code);
    tickers.push({ code, name: tickerName(report) });
  }
  return tickers;
}

function RecentReportRow({ report }: { report: ReportSummary }) {
  const { meta } = report;
  const rating = REPORT_RATING_META[meta.rating];

  return (
    <li className={styles.rowItem} data-testid="recent-report">
      <Link className={styles.row} to={`/reports/${meta.report_id}`}>
        <span className={styles.rowMain}>
          <span className={styles.name}>{tickerName(report)}</span>
          {meta.ticker_name ? (
            <span className={styles.code}>{meta.ticker_code}</span>
          ) : null}
        </span>
        <span className={styles.rowMeta}>
          <Badge tone={rating.tone}>{rating.label}</Badge>
          <time dateTime={meta.analysis_date}>{meta.analysis_date}</time>
          <time dateTime={meta.generated_at ?? undefined}>
            {formatGeneratedAt(meta.generated_at)}
          </time>
        </span>
      </Link>
    </li>
  );
}

export function RecentReports() {
  const [open, setOpen] = useState(false);
  const query = useQuery({ ...recentReportsQuery(RECENT_REPORTS_LIMIT), retry: false });
  const reports = (query.data?.items ?? []).slice(0, RECENT_REPORTS_LIMIT);
  const tickers = uniqueTickers(reports);

  const state: DataStateValue = query.isPending
    ? "loading"
    : query.isError
      ? "error"
      : reports.length === 0
        ? "empty"
        : "ok";

  return (
    <section
      className={styles.panel}
      aria-labelledby="recent-reports-title"
      data-testid="recent-reports"
    >
      <div className={styles.panelHead}>
        <h2 className={styles.panelTitle} id="recent-reports-title">
          最近报告
        </h2>
        <div className={styles.headActions}>
          <Link className={styles.all} to="/reports">
            查看全部
          </Link>
          <button
            type="button"
            className={styles.toggle}
            aria-expanded={open}
            aria-controls="recent-reports-body"
            onClick={() => setOpen((value) => !value)}
          >
            {open ? "收起" : "展开"}
          </button>
        </div>
      </div>
      <div
        id="recent-reports-body"
        className={`${styles.panelBody} ${styles.panelBodyCollapsible} ${
          open ? styles.panelOpen : ""
        }`}
      >
        <DataState
          state={state}
          onRetry={() => void query.refetch()}
          skeletonHeight="200px"
          emptyTitle="还没有报告"
          emptyDescription="完成一次分析后，报告会出现在这里。"
        >
          <ul className={styles.list}>
            {reports.map((report) => (
              <RecentReportRow key={report.meta.report_id} report={report} />
            ))}
          </ul>
          {tickers.length > 0 ? (
            <div className={styles.tickers} data-testid="recent-report-tickers">
              <h3 className={styles.tickersTitle}>最近研究的股票</h3>
              <ul className={styles.tickerList}>
                {tickers.map((ticker) => (
                  <li key={ticker.code}>
                    <Link
                      className={styles.tickerLink}
                      to={`/stocks/${ticker.code}`}
                      data-testid="recent-report-ticker"
                    >
                      {ticker.name}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </DataState>
      </div>
    </section>
  );
}