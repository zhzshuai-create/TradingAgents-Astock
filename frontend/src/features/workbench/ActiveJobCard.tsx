import { Link } from "react-router-dom";

import { JOB_STATUS_META, stageDetail, stageProgress } from "../../lib/jobStatus";
import { useActiveJobs } from "../../shell/useActiveJobs";
import { Badge } from "../../ui";
import styles from "./ActiveJobCard.module.css";

/**
 * Workbench activity block. The shell bar steps aside on this route so the
 * card is the one place the active job appears.
 */
export function ActiveJobCard() {
  const { job, extra } = useActiveJobs();
  if (job === null) {
    return null;
  }

  const status = JOB_STATUS_META[job.status];
  const percent = stageProgress(job.current_stage);

  return (
    <section
      className={styles.wrap}
      aria-label="活动任务"
      data-testid="active-job-bar"
    >
      <Link
        className={styles.card}
        to={`/jobs/${job.job_id}`}
        data-testid="workbench-active-card"
      >
        <span className={styles.head}>
          <Badge tone={status.tone} dot>
            {status.label}
          </Badge>
          <span className={styles.name}>{job.ticker_name ?? job.ticker_code}</span>
          {job.ticker_name ? (
            <span className={styles.code}>{job.ticker_code}</span>
          ) : null}
        </span>
        <span className={styles.stage}>{stageDetail(job)}</span>
        {percent !== null ? (
          <span className={styles.progress} aria-hidden="true">
            <span className={styles.fill} style={{ width: `${percent}%` }} />
          </span>
        ) : null}
        <span className={styles.view}>查看</span>
      </Link>
      {extra > 0 ? (
        <Link className={styles.more} to="/jobs?active=true">
          还有 {extra} 个
        </Link>
      ) : null}
    </section>
  );
}
