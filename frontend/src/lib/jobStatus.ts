/** One status vocabulary for the bar, the workbench and later job pages. */

import type { CurrentStage, JobStatus } from "../api/types";
import type { BadgeTone } from "../ui";

export interface JobStatusMeta {
  label: string;
  tone: BadgeTone;
}

export const JOB_STATUS_META: Record<JobStatus, JobStatusMeta> = {
  queued: { label: "排队中", tone: "neutral" },
  running: { label: "运行中", tone: "info" },
  pause_requested: { label: "暂停中", tone: "warning" },
  paused: { label: "已暂停", tone: "warning" },
  cancel_requested: { label: "取消中", tone: "warning" },
  cancelled: { label: "已取消", tone: "neutral" },
  succeeded: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
  // Interrupted work waits for a person; it is never reported as running.
  interrupted: { label: "等待人工处理", tone: "warning" },
};

export function stageDetail(job: {
  status: JobStatus;
  current_stage: CurrentStage | null;
}): string {
  const stage = job.current_stage;
  if (stage !== null) {
    return `${stage.name} ${stage.index}/${stage.total}`;
  }
  switch (job.status) {
    case "queued":
      return "等待开始";
    case "running":
      return "阶段切换中";
    case "pause_requested":
      return "等待暂停生效";
    case "paused":
      return "已暂停";
    case "cancel_requested":
      return "等待取消生效";
    case "cancelled":
      return "已取消";
    case "succeeded":
      return "已完成";
    case "failed":
      return "分析失败";
    case "interrupted":
      return "需要人工处理";
  }
}

export function stageProgress(stage: CurrentStage | null): number | null {
  if (stage === null || stage.total <= 0) {
    return null;
  }
  const ratio = Math.min(1, Math.max(0, stage.index / stage.total));
  return Math.round(ratio * 100);
}

export function relativeTime(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) {
    return "";
  }
  const seconds = Math.max(0, Math.floor((now - then) / 1000));
  if (seconds < 60) {
    return "刚刚";
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes} 分钟前`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours} 小时前`;
  }
  const days = Math.floor(hours / 24);
  if (days < 30) {
    return `${days} 天前`;
  }
  return new Date(then).toLocaleDateString("zh-CN");
}
