import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";

import { displayErrorMessage } from "../../api/errors";
import type { JobStage, StageId } from "../../api/types";
import { STAGE_STATUS_LABELS } from "../../lib/jobStatus";
import { stageReportQuery } from "../../lib/query";
import { Button, Skeleton } from "../../ui";
import { markdownPreview } from "./format";
import styles from "./StageReportView.module.css";

interface StageReportBodyProps {
  jobId: string;
  stage: JobStage;
}

export function StageReportBody({ jobId, stage }: StageReportBodyProps) {
  const query = useQuery({
    ...stageReportQuery(jobId, stage.id),
    enabled: stage.status === "done" || stage.status === "failed",
  });
  const [showFull, setShowFull] = useState(false);

  useEffect(() => {
    setShowFull(false);
  }, [stage.id]);

  if (stage.status !== "done" && stage.status !== "failed") {
    return (
      <p className={styles.empty} data-testid="stage-report-empty">
        尚未产出
      </p>
    );
  }
  if (query.isPending) {
    return (
      <div className={styles.loading} data-testid="stage-report-loading">
        <Skeleton height="14px" />
        <Skeleton height="14px" width="80%" />
        <Skeleton height="14px" width="60%" />
      </div>
    );
  }
  if (query.isError) {
    return (
      <div className={styles.error} data-testid="stage-report-error">
        <p>{displayErrorMessage(query.error)}</p>
        <Button size="sm" onClick={() => void query.refetch()}>
          重试
        </Button>
      </div>
    );
  }

  const markdown = query.data.markdown;
  if (markdown === null) {
    return (
      <p className={styles.empty} data-testid="stage-report-empty">
        尚未产出
      </p>
    );
  }

  const preview = markdownPreview(markdown);
  const body = showFull || !preview.hasMore ? markdown : preview.text;

  return (
    <div className={styles.body} data-testid="stage-report-body">
      <div className={styles.markdown}>
        <ReactMarkdown
          skipHtml
          components={{
            a: ({ node, ...props }) => {
              void node;
              return (
                <a {...props} target="_blank" rel="noopener noreferrer" />
              );
            },
          }}
        >
          {body}
        </ReactMarkdown>
      </div>
      {preview.hasMore && !showFull ? (
        <Button
          size="sm"
          onClick={() => setShowFull(true)}
          data-testid="stage-report-expand"
        >
          展开全文
        </Button>
      ) : null}
      {query.data.truncated ? (
        <p className={styles.truncated} data-testid="stage-report-truncated">
          报告超过 128 KiB，仅显示前 128 KiB。
        </p>
      ) : null}
    </div>
  );
}

interface StageReportViewProps {
  jobId: string;
  stages: JobStage[];
  expandedStageId: StageId | null;
  onToggle: (stageId: StageId) => void;
}

export function StageReportView({
  jobId,
  stages,
  expandedStageId,
  onToggle,
}: StageReportViewProps) {
  if (stages.length === 0) {
    return null;
  }
  const ordered = [...stages].sort((a, b) => b.index - a.index);

  return (
    <section
      className={styles.list}
      aria-label="阶段报告"
      data-testid="stage-report-list"
    >
      <h2 className={styles.title}>阶段报告</h2>
      {ordered.map((stage) => {
        const expanded = expandedStageId === stage.id;
        return (
          <article
            key={stage.id}
            id={`stage-report-${stage.id}`}
            className={styles.item}
            data-testid={`stage-report-${stage.id}`}
          >
            <button
              type="button"
              className={styles.toggle}
              aria-expanded={expanded}
              onClick={() => onToggle(stage.id)}
              data-testid={`stage-report-toggle-${stage.id}`}
            >
              <span className={styles.index}>{stage.index}</span>
              <span className={styles.name}>{stage.name}</span>
              <span className={styles.state}>
                {STAGE_STATUS_LABELS[stage.status]}
              </span>
              <span className={styles.chevron} aria-hidden="true">
                {expanded ? "收起" : "展开"}
              </span>
            </button>
            {expanded ? (
              <div className={styles.content}>
                <StageReportBody jobId={jobId} stage={stage} />
              </div>
            ) : null}
          </article>
        );
      })}
    </section>
  );
}
