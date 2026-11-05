import { Link } from "react-router-dom";

import type { JobSummary } from "../../api/types";
import { JOB_STATUS_META, stageDetail } from "../../lib/jobStatus";
import { Badge } from "../../ui";
import { formatDuration } from "./format";
import styles from "./JobCards.module.css";

export interface JobCardsProps {
  jobs: JobSummary[];
}

export function JobCards({ jobs }: JobCardsProps) {
  return (
    <ul className={styles.list} data-testid="job-cards">
      {jobs.map((job) => {
        const status = JOB_STATUS_META[job.status];
        return (
          <li key={job.job_id}>
            <Link
              className={styles.card}
              to={`/jobs/${job.job_id}`}
              data-testid="job-card"
            >
              <span className={styles.head}>
                <span className={styles.name}>
                  {job.ticker_name ?? job.ticker_code}
                </span>
                {job.ticker_name ? (
                  <span className={styles.code}>{job.ticker_code}</span>
                ) : null}
                <Badge tone={status.tone}>{status.label}</Badge>
              </span>
              <span className={styles.meta}>
                <time dateTime={job.analysis_date}>{job.analysis_date}</time>
                <span>{stageDetail(job)}</span>
              </span>
              <span className={styles.foot}>
                <span>耗时 {formatDuration(job.stats.elapsed_ms)}</span>
                {job.status === "failed" && job.error ? (
                  <span className={styles.error}>{job.error.message}</span>
                ) : null}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
