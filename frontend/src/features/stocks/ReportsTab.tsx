import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { stockReportsQuery } from "../../lib/query";
import { Badge, DataState } from "../../ui";
import type { DataStateValue } from "../market/copy";
import {
  formatGeneratedAt,
  REPORT_RATING_META,
} from "../reports/format";
import { STOCK_REPORTS_LIMIT } from "./stockParams";
import styles from "./StockPage.module.css";

export function ReportsTab({ ticker }: { ticker: string }) {
  const query = useQuery(stockReportsQuery(ticker, STOCK_REPORTS_LIMIT));
  const reports = query.data?.items ?? [];
  const state: DataStateValue = query.isPending
    ? "loading"
    : query.isError
      ? "error"
      : reports.length === 0
        ? "empty"
        : "ok";

  return (
    <div className={styles.tabPanel} data-testid="stock-reports">
      <DataState
        state={state}
        onRetry={() => void query.refetch()}
        skeletonHeight="300px"
        emptyTitle="还没有这只股票的报告"
        emptyDescription="完成一次分析后，报告会出现在这里。"
      >
        <ul className={styles.reportList}>
          {reports.map((report) => {
            const { meta } = report;
            const rating = REPORT_RATING_META[meta.rating];
            return (
              <li
                className={styles.reportItem}
                data-testid="stock-report-row"
                key={meta.report_id}
              >
                <Link
                  className={styles.reportLink}
                  to={`/reports/${meta.report_id}`}
                >
                  {meta.analysis_date} 报告
                </Link>
                <Badge tone={rating.tone}>{rating.label}</Badge>
                <span className={styles.reportMeta}>
                  生成时间 {formatGeneratedAt(meta.generated_at)}
                </span>
                {meta.job_id === null ? null : (
                  <Link
                    className={styles.reportMeta}
                    to={`/jobs/${meta.job_id}`}
                  >
                    查看任务
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      </DataState>
    </div>
  );
}
