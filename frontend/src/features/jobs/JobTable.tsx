import { Link } from "react-router-dom";

import type { JobSummary } from "../../api/types";
import {
  JOB_STATUS_META,
  relativeTime,
  stageDetail,
  stageProgress,
} from "../../lib/jobStatus";
import { Badge } from "../../ui";
import { formatDuration } from "./format";
import styles from "./JobTable.module.css";

export interface JobTableProps {
  jobs: JobSummary[];
}

function JobRow({ job }: { job: JobSummary }) {
  const status = JOB_STATUS_META[job.status];
  const percent = stageProgress(job.current_stage);

  return (
    <tr data-testid="job-row">
      <td>
        <Link
          className={styles.ticker}
          to={`/stocks/${job.ticker_code}`}
          data-testid="job-ticker-link"
        >
          <span className={styles.name}>
            {job.ticker_name ?? job.ticker_code}
          </span>
          {job.ticker_name ? (
            <span className={styles.code}>{job.ticker_code}</span>
          ) : null}
        </Link>
      </td>
      <td>
        <time dateTime={job.analysis_date}>{job.analysis_date}</time>
      </td>
      <td>
        <Badge tone={status.tone}>{status.label}</Badge>
        {job.status === "failed" && job.error ? (
          <span className={styles.errorText}>{job.error.message}</span>
        ) : null}
      </td>
      <td>
        <span className={styles.stage}>{stageDetail(job)}</span>
        {percent === null ? null : (
          <span
            className={styles.progress}
            data-testid="stage-progress"
            aria-hidden="true"
          >
            <span className={styles.fill} style={{ width: `${percent}%` }} />
          </span>
        )}
      </td>
      <td className={styles.numeric}>{formatDuration(job.stats.elapsed_ms)}</td>
      <td>
        <time dateTime={job.created_at} title={job.created_at}>
          {relativeTime(job.created_at)}
        </time>
      </td>
      <td>
        <Link className={styles.view} to={`/jobs/${job.job_id}`}>
          查看
        </Link>
      </td>
    </tr>
  );
}

export function JobTable({ jobs }: JobTableProps) {
  return (
    <div className={styles.wrap}>
      <table className={styles.table} data-testid="job-table">
        <caption className={styles.caption}>任务列表</caption>
        <thead>
          <tr>
            <th scope="col">股票</th>
            <th scope="col">分析日期</th>
            <th scope="col">状态</th>
            <th scope="col">当前阶段</th>
            <th scope="col">耗时</th>
            <th scope="col">创建时间</th>
            <th scope="col">
              <span className={styles.caption}>操作</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <JobRow job={job} key={job.job_id} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
