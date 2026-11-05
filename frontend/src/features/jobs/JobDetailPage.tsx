import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, displayErrorMessage } from "../../api/errors";
import type { JobStage, StageId } from "../../api/types";
import { jobDetailQuery } from "../../lib/query";
import { Button, Drawer, EmptyState, Skeleton } from "../../ui";
import { JobNotice } from "./JobNotice";
import { StageReportBody, StageReportView } from "./StageReportView";
import { StageTimeline } from "./StageTimeline";
import { StatsBar } from "./StatsBar";
import { StatusHeader } from "./StatusHeader";
import styles from "./JobDetailPage.module.css";

function isJobNotFound(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.status === 404 || error.code === "job_not_found")
  );
}

/** The most recently finished stage, used for the one auto-expanded report. */
function latestCompletedStage(stages: JobStage[]): StageId | null {
  let best: JobStage | null = null;
  for (const stage of stages) {
    if (stage.status !== "done" && stage.status !== "failed") {
      continue;
    }
    if (best === null) {
      best = stage;
      continue;
    }
    const next = stage.finished_at === null ? null : Date.parse(stage.finished_at);
    const current =
      best.finished_at === null ? null : Date.parse(best.finished_at);
    if (next === null && current === null) {
      if (stage.index > best.index) {
        best = stage;
      }
    } else if (next !== null && (current === null || next > current)) {
      best = stage;
    } else if (next !== null && current === next && stage.index > best.index) {
      best = stage;
    }
  }
  return best?.id ?? null;
}

function isMobileViewport(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(max-width: 767px)").matches
  );
}

export function JobDetailPage() {
  const { jobId = "" } = useParams();
  const query = useQuery({
    ...jobDetailQuery(jobId),
    enabled: jobId !== "",
  });
  const [expandedStageId, setExpandedStageId] = useState<StageId | null>(null);
  const [drawerStageId, setDrawerStageId] = useState<StageId | null>(null);
  const autoExpandedFor = useRef<string | null>(null);

  useEffect(() => {
    autoExpandedFor.current = null;
    setExpandedStageId(null);
    setDrawerStageId(null);
  }, [jobId]);

  useEffect(() => {
    if (query.data === undefined || autoExpandedFor.current === jobId) {
      return;
    }
    autoExpandedFor.current = jobId;
    setExpandedStageId(latestCompletedStage(query.data.stages));
  }, [jobId, query.data]);

  const job = query.data;

  if (jobId === "" || (query.isError && isJobNotFound(query.error))) {
    return (
      <section className={styles.page} data-testid="page-job-detail">
        <div data-testid="job-not-found">
          <EmptyState
            title="没有找到这个任务"
            description="任务可能已被删除，或链接地址不正确。"
            action={
              <Link className={styles.linkButton} to="/jobs">
                返回任务列表
              </Link>
            }
          />
        </div>
      </section>
    );
  }

  if (query.isPending) {
    return (
      <section className={styles.page} data-testid="page-job-detail">
        <div className={styles.skeleton} data-testid="job-detail-loading">
          <Skeleton height="104px" />
          <Skeleton height="148px" />
          <Skeleton height="72px" />
        </div>
      </section>
    );
  }

  if (query.isError || job === undefined) {
    return (
      <section className={styles.page} data-testid="page-job-detail">
        <div className={styles.errorPanel} role="alert" data-testid="job-detail-error">
          <p>{displayErrorMessage(query.error)}</p>
          <Button onClick={() => void query.refetch()}>重试</Button>
        </div>
      </section>
    );
  }

  const currentStageId =
    job.current_stage?.id ??
    job.stages.find((stage) => stage.status === "active")?.id ??
    null;
  const drawerStage =
    job.stages.find((stage) => stage.id === drawerStageId) ?? null;

  function selectStage(stageId: StageId) {
    if (isMobileViewport()) {
      setDrawerStageId(stageId);
      return;
    }
    setExpandedStageId(stageId);
    const target = document.getElementById(`stage-report-${stageId}`);
    target?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }

  function toggleStage(stageId: StageId) {
    setExpandedStageId((current) => (current === stageId ? null : stageId));
  }

  return (
    <section className={styles.page} data-testid="page-job-detail">
      <StatusHeader job={job} />
      <StageTimeline
        stages={job.stages}
        currentStageId={currentStageId}
        expandedStageId={expandedStageId}
        onSelect={selectStage}
      />
      <StatsBar stats={job.stats} />
      <div className={styles.reports}>
        <StageReportView
          jobId={job.job_id}
          stages={job.stages}
          expandedStageId={expandedStageId}
          onToggle={toggleStage}
        />
      </div>
      <JobNotice job={job} />
      <Drawer
        open={drawerStage !== null}
        title={
          drawerStage === null
            ? "阶段报告"
            : `${drawerStage.index}. ${drawerStage.name}`
        }
        side="bottom"
        onClose={() => setDrawerStageId(null)}
      >
        {drawerStage === null ? null : (
          <StageReportBody jobId={job.job_id} stage={drawerStage} />
        )}
      </Drawer>
    </section>
  );
}
