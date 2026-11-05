import { Link } from "react-router-dom";

import { JOB_STATUS_META, stageDetail, stageProgress } from "../lib/jobStatus";
import { Badge } from "../ui";
import styles from "./ActiveJobBar.module.css";
import { useActiveJobs } from "./useActiveJobs";

/** One strip above the content on every page except the workbench. */
export function ActiveJobBar() {
  const { job, extra } = useActiveJobs();
  if (job === null) {
    return null;
  }

  const status = JOB_STATUS_META[job.status];
  const percent = stageProgress(job.current_stage);

  return (
    <section
      className={styles.bar}
      aria-label="活动任务"
      data-testid="active-job-bar"
    >
      <Badge tone={status.tone} dot>
        {status.label}
      </Badge>
      <Link className={styles.identity} to={`/jobs/${job.job_id}`}>
        <span className={styles.ticker}>{job.ticker_name ?? job.ticker_code}</span>
        {job.ticker_name ? <span className={styles.code}>{job.ticker_code}</span> : null}
      </Link>
      <span className={styles.stage}>{stageDetail(job)}</span>
      {percent !== null ? (
        <span className={styles.progress} aria-hidden="true">
          <span className={styles.progressFill} style={{ width: `${percent}%` }} />
        </span>
      ) : null}
      <Link className={styles.view} to={`/jobs/${job.job_id}`}>
        查看
      </Link>
      {extra > 0 ? (
        <Link className={styles.more} to="/jobs?active=true">
          还有 {extra} 个
        </Link>
      ) : null}
    </section>
  );
}
