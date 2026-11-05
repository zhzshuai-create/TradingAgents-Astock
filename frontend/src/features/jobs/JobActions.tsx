import { useState } from "react";

import { displayErrorMessage } from "../../api/errors";
import type { AllowedAction, JobDetail } from "../../api/types";
import { Button } from "../../ui";
import { ConfirmDialog } from "./ConfirmDialog";
import { useJobActions } from "./useJobActions";
import styles from "./JobActions.module.css";

export const JOB_ACTION_LABELS: Record<AllowedAction, string> = {
  pause: "暂停",
  resume: "继续",
  cancel: "取消",
  retry: "使用相同参数重试",
  reanalyze: "重新分析",
  resume_from_checkpoint: "从检查点继续",
};

interface JobActionsProps {
  job: JobDetail;
}

export function JobActions({ job }: JobActionsProps) {
  const { busy, error, fingerprintMismatch, run } = useJobActions(job);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const actions = fingerprintMismatch
    ? job.allowed_actions.filter((action) => action === "reanalyze")
    : job.allowed_actions;

  if (actions.length === 0 && !fingerprintMismatch) {
    return null;
  }

  async function confirmCancel() {
    await run("cancel");
    setConfirmOpen(false);
  }

  return (
    <>
      <div className={styles.wrap} data-testid="job-actions">
        {actions.length === 0 ? null : (
          <div className={styles.actions} aria-busy={busy !== null}>
            {actions.map((action) => (
              <Button
                key={action}
                size="sm"
                disabled={busy !== null}
                data-testid={`job-action-${action}`}
                onClick={() => {
                  if (action === "cancel") {
                    setConfirmOpen(true);
                    return;
                  }
                  void run(action);
                }}
              >
                {busy === action ? "处理中…" : JOB_ACTION_LABELS[action]}
              </Button>
            ))}
          </div>
        )}
        {fingerprintMismatch ? (
          <p className={styles.notice} data-testid="job-action-notice">
            配置已变化，只能重新分析
          </p>
        ) : null}
        {error === null ? null : (
          <p className={styles.error} role="alert" data-testid="job-action-error">
            {displayErrorMessage(error)}
          </p>
        )}
      </div>
      <ConfirmDialog
        open={confirmOpen}
        busy={busy === "cancel"}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => void confirmCancel()}
      />
    </>
  );
}
