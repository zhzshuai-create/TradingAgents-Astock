import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import type { JobSummary } from "../../api/types";
import { JOB_STATUS_META, relativeTime, stageDetail } from "../../lib/jobStatus";
import { jobsQuery } from "../../lib/query";
import { Badge, Button, EmptyState, Skeleton } from "../../ui";
import styles from "./RecentJobs.module.css";

export const RECENT_JOBS_LIMIT = 3;

export interface RecentJobsProps {
  onStartAnalysis: () => void;
}

function RecentJobRow({ job }: { job: JobSummary }) {
  const status = JOB_STATUS_META[job.status];

  return (
    <li className={styles.row} data-testid="recent-job">
      <Link className={styles.rowLink} to={`/jobs/${job.job_id}`}>
        <span className={styles.identity}>
          <Badge tone={status.tone}>{status.label}</Badge>
          <span className={styles.name}>{job.ticker_name ?? job.ticker_code}</span>
          {job.ticker_name ? (
            <span className={styles.code}>{job.ticker_code}</span>
          ) : null}
        </span>
        <span className={styles.meta}>
          <span className={styles.stage}>{stageDetail(job)}</span>
          <time className={styles.time} dateTime={job.created_at}>
            {relativeTime(job.created_at)}
          </time>
        </span>
      </Link>
      {job.status === "failed" ? (
        <div className={styles.rowActions}>
          <Link className={styles.action} to={`/jobs/${job.job_id}`}>
            查看错误
          </Link>
          <Link
            className={styles.action}
            to={`/workbench?launch=1&ticker=${job.ticker_code}`}
          >
            重新分析
          </Link>
        </div>
      ) : null}
    </li>
  );
}

export function RecentJobs({ onStartAnalysis }: RecentJobsProps) {
  const query = useQuery({
    ...jobsQuery({ limit: RECENT_JOBS_LIMIT }),
    retry: false,
  });
  const jobs = (query.data?.items ?? []).slice(0, RECENT_JOBS_LIMIT);

  return (
    <section
      className={styles.section}
      aria-labelledby="recent-jobs-title"
      data-testid="recent-jobs"
    >
      <div className={styles.head}>
        <h2 className={styles.title} id="recent-jobs-title">
          最近任务
        </h2>
        <Link className={styles.all} to="/jobs">
          查看全部
        </Link>
      </div>
      {query.isPending ? (
        <div className={styles.skeleton} data-testid="recent-jobs-loading">
          <Skeleton height="48px" />
          <Skeleton height="48px" />
          <Skeleton height="48px" />
        </div>
      ) : query.isError ? (
        <div className={styles.error} role="alert">
          <span>暂时无法加载最近任务。</span>
          <Button size="sm" onClick={() => void query.refetch()}>
            重试
          </Button>
        </div>
      ) : jobs.length === 0 ? (
        <EmptyState
          title="还没有分析任务"
          description="选一只股票，开始第一次分析。"
          action={
            <Button variant="primary" onClick={onStartAnalysis}>
              开始第一次分析
            </Button>
          }
        />
      ) : (
        <ul className={styles.list}>
          {jobs.map((job) => (
            <RecentJobRow key={job.job_id} job={job} />
          ))}
        </ul>
      )}
    </section>
  );
}
