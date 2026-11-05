import type { JobDetail } from "../../api/types";
import styles from "./JobNotice.module.css";

interface JobNoticeProps {
  job: JobDetail;
}

interface Notice {
  kind: "info" | "warning" | "danger";
  title: string;
  body: string;
  next?: string;
}

function noticeFor(job: JobDetail): Notice | null {
  switch (job.status) {
    case "queued":
      return {
        kind: "info",
        title: "排队中",
        body: "等待 Worker 认领，任务还没有开始执行。",
      };
    case "pause_requested":
      return {
        kind: "warning",
        title: "暂停中",
        body: "已受理，将在当前阶段结束后生效。",
      };
    case "cancel_requested":
      return {
        kind: "warning",
        title: "取消中",
        body: "已受理，将在当前阶段结束后生效。",
      };
    case "failed":
      return {
        kind: "danger",
        title: "分析失败",
        body: job.error?.message ?? "分析没有完成。",
        next: "已完成阶段的报告仍可查看，可以据此决定后续处理。",
      };
    case "interrupted":
      return {
        kind: "warning",
        title: "任务已中断",
        body: "任务意外停止，需要人工选择从检查点继续或重新分析。",
        next: "已完成阶段的报告仍可查看。",
      };
    case "succeeded":
      return job.report_id === null
        ? {
            kind: "danger",
            title: "报告不可用",
            body: "任务已完成，但报告还没有提交。请联系维护。",
          }
        : null;
    default:
      return null;
  }
}

export function JobNotice({ job }: JobNoticeProps) {
  const notice = noticeFor(job);
  if (notice === null) {
    return null;
  }
  return (
    <section
      className={`${styles.notice} ${styles[notice.kind]}`}
      aria-label={notice.title}
      data-testid="job-notice"
      data-kind={job.status}
    >
      <h2 className={styles.title}>{notice.title}</h2>
      <p className={styles.body}>{notice.body}</p>
      {notice.next === undefined ? null : (
        <p className={styles.next}>{notice.next}</p>
      )}
    </section>
  );
}
