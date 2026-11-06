import { Link } from "react-router-dom";

import type { ReportSummary } from "../../api/types";
import { Badge } from "../../ui";
import {
  formatGeneratedAt,
  originLabel,
  REPORT_RATING_META,
  summaryLabel,
} from "./format";
import styles from "./ReportCards.module.css";

export interface ReportCardsProps {
  reports: ReportSummary[];
}

export function ReportCards({ reports }: ReportCardsProps) {
  return (
    <ul className={styles.list} data-testid="report-cards">
      {reports.map((report) => {
        const { meta } = report;
        const rating = REPORT_RATING_META[meta.rating];
        const generated =
          meta.generated_at === null
            ? "生成时间未知"
            : `生成于 ${formatGeneratedAt(meta.generated_at)}`;

        return (
          <li key={meta.report_id}>
            <Link
              className={styles.card}
              to={`/reports/${meta.report_id}`}
              data-testid="report-card"
            >
              <span className={styles.head}>
                <Badge tone={rating.tone}>{rating.label}</Badge>
                <span className={styles.name}>
                  {meta.ticker_name ?? meta.ticker_code}
                </span>
                {meta.ticker_name ? (
                  <span className={styles.code}>{meta.ticker_code}</span>
                ) : null}
              </span>
              <span className={styles.meta}>
                <time dateTime={meta.analysis_date}>{meta.analysis_date}</time>
                <span>
                  {originLabel(report)} · {generated}
                </span>
              </span>
              <span className={styles.foot}>
                <span>信号 {meta.signal}</span>
                <span>摘要 {summaryLabel(report)}</span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
