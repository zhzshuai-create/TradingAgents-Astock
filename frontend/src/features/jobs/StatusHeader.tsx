import { Link } from "react-router-dom";

import type { JobDetail } from "../../api/types";
import { JOB_STATUS_META } from "../../lib/jobStatus";
import { Badge } from "../../ui";
import { JobActions } from "./JobActions";
import styles from "./StatusHeader.module.css";

interface StatusHeaderProps {
  job: JobDetail;
}

export function StatusHeader({ job }: StatusHeaderProps) {
  const meta = JOB_STATUS_META[job.status];

  return (
    <header className={styles.header} data-testid="job-header">
      <div className={styles.identity}>
        <p className={styles.eyebrow}>
          <Link className={styles.back} to="/jobs">
            任务
          </Link>
          <span aria-hidden="true"> / </span>
          {job.ticker_code}
        </p>
        <div className={styles.nameRow}>
          <h1 className={styles.name}>{job.ticker_name ?? job.ticker_code}</h1>
          <Badge tone={meta.tone} dot>
            {meta.label}
          </Badge>
        </div>
        <p className={styles.meta}>
          {job.ticker_name === null ? "" : `${job.ticker_code} · `}
          分析日期 {job.analysis_date}
        </p>
      </div>

      <div className={styles.side}>
        <JobActions job={job} />
        {job.status === "succeeded" && job.report_id !== null ? (
          <Link
            className={styles.reportLink}
            to={`/reports/${job.report_id}`}
            data-testid="job-open-report"
          >
            打开报告
          </Link>
        ) : null}
      </div>
    </header>
  );
}
