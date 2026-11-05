import type { JobStage, StageId } from "../../api/types";
import { STAGE_STATUS_LABELS } from "../../lib/jobStatus";
import styles from "./StageTimeline.module.css";

interface StageTimelineProps {
  stages: JobStage[];
  currentStageId: string | null;
  expandedStageId: string | null;
  onSelect: (stageId: StageId) => void;
}

interface StageGroupProps {
  label: string;
  testId: string;
  items: JobStage[];
  currentStageId: string | null;
  expandedStageId: string | null;
  onSelect: (stageId: StageId) => void;
}

function StageGroup({
  label,
  testId,
  items,
  currentStageId,
  expandedStageId,
  onSelect,
}: StageGroupProps) {
  return (
    <section className={styles.group}>
      <h2 className={styles.groupTitle}>{label}</h2>
      <div
        className={`${styles.grid} ${items.length <= 5 ? styles.five : ""}`}
        data-testid={testId}
      >
        {items.map((stage) => {
          const isCurrent = stage.id === currentStageId;
          const classes = [
            styles.stage,
            isCurrent ? styles.current : "",
            stage.status === "failed" ? styles.failed : "",
            stage.status === "done" ? styles.done : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <button
              type="button"
              key={stage.id}
              className={classes}
              data-testid={`stage-${stage.id}`}
              aria-current={isCurrent ? "step" : undefined}
              aria-expanded={expandedStageId === stage.id}
              onClick={() => onSelect(stage.id)}
            >
              <span className={styles.index}>{stage.index}</span>
              <span className={styles.name}>{stage.name}</span>
              <span className={styles.status}>
                {STAGE_STATUS_LABELS[stage.status]}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function StageTimeline({
  stages,
  currentStageId,
  expandedStageId,
  onSelect,
}: StageTimelineProps) {
  const analysis = stages.filter((stage) => stage.index <= 7);
  const flow = stages.filter((stage) => stage.index >= 8);

  return (
    <section className={styles.timeline} aria-label="阶段总览">
      {analysis.length === 0 ? null : (
        <StageGroup
          label="7 个分析阶段"
          testId="stage-group-analysis"
          items={analysis}
          currentStageId={currentStageId}
          expandedStageId={expandedStageId}
          onSelect={onSelect}
        />
      )}
      {flow.length === 0 ? null : (
        <StageGroup
          label="5 个流程阶段"
          testId="stage-group-flow"
          items={flow}
          currentStageId={currentStageId}
          expandedStageId={expandedStageId}
          onSelect={onSelect}
        />
      )}
    </section>
  );
}
