import { Link } from "react-router-dom";

import type { JobStatus } from "../api/types";
import { Badge, type BadgeTone } from "../ui";
import styles from "./ActiveJobBar.module.css";
import { useActiveJobs } from "./useActiveJobs";

const STATUS: Record<JobStatus, { label: string; tone: BadgeTone }> = {
  queued: { label: "排队中", tone: "neutral" },
  running: { label: "运行中", tone: "info" },
  pause_requested: { label: "暂停中", tone: "warning" },
  paused: { label: "已暂停", tone: "warning" },
  cancel_requested: { label: "取消中", tone: "warning" },
  cancelled: { label: "已取消", tone: "neutral" },
  succeeded: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
  interrupted: { label: "已中断", tone: "danger" },
};

/** One strip above the content on every page; nothing when no job is active. */
export function ActiveJobBar() {
  const { job, extra } = useActiveJobs();
  if (job === null) {
    return null;
  }

  const status = STATUS[job.status];
  const stage = job.current_stage;
  const detail = stage
    ? `${stage.name} ${stage.index}/${stage.total}`
    : job.status === "queued"
      ? "等待开始"
      : "阶段切换中";

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
      <span className={styles.stage}>{detail}</span>
      {stage ? (
        <span className={styles.progress} aria-hidden="true">
          <span
            className={styles.progressFill}
            style={{ width: `${(stage.index / stage.total) * 100}%` }}
          />
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
