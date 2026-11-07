import { Link } from "react-router-dom";

import type { ReportSummary } from "../../api/types";
import { Badge } from "../../ui";
import {
  formatGeneratedAt,
  originLabel,
  REPORT_RATING_META,
  summaryLabel,
} from "./format";
import styles from "./ReportTable.module.css";

export interface ReportTableProps {
  reports: ReportSummary[];
}

function ReportRow({ report }: { report: ReportSummary }) {
  const { meta } = report;
  const rating = REPORT_RATING_META[meta.rating];
  const generated = formatGeneratedAt(meta.generated_at);

  return (
    <tr data-testid="report-row">
      <td>
        <Badge tone={rating.tone}>{rating.label}</Badge>
      </td>
      <th scope="row">
        <Link className={styles.name} to={`/reports/${meta.report_id}`}>
          {meta.ticker_name ?? meta.ticker_code}
        </Link>
        {meta.ticker_name ? (
          <span className={styles.code}>{meta.ticker_code}</span>
        ) : null}
      </th>
      <td>
        <time dateTime={meta.analysis_date}>{meta.analysis_date}</time>
      </td>
      <td>
        {meta.origin === "legacy_import" ? (
          <Badge tone="neutral">历史导入</Badge>
        ) : (
          <span>{originLabel(report)}</span>
        )}
      </td>
      <td>
        {meta.generated_at === null ? (
          <span className={styles.unknown}>生成时间未知</span>
        ) : (
          <time dateTime={meta.generated_at} title={meta.generated_at}>
            {generated}
          </time>
        )}
      </td>
      <td>{meta.signal}</td>
      <td className={styles.numeric}>{summaryLabel(report)}</td>
    </tr>
  );
}

export function ReportTable({ reports }: ReportTableProps) {
  return (
    <div className={styles.wrap}>
      <table className={styles.table} data-testid="report-table">
        <caption className={styles.caption}>报告列表</caption>
        <thead>
          <tr>
            <th scope="col">评级</th>
            <th scope="col">股票</th>
            <th scope="col">分析日期</th>
            <th scope="col">来源</th>
            <th scope="col">生成时间</th>
            <th scope="col">信号</th>
            <th scope="col">摘要</th>
          </tr>
        </thead>
        <tbody>
          {reports.map((report) => (
            <ReportRow report={report} key={report.meta.report_id} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
