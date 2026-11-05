import { Link } from "react-router-dom";

import type { ApiError } from "../../api/errors";
import { Button } from "../../ui";
import styles from "./SubmitState.module.css";

export interface SubmitStateProps {
  error: ApiError | null;
  conflictJobId: string | null;
  cooldownSeconds: number;
  hasFieldErrors: boolean;
  onDismissConflict: () => void;
  metaLoading: boolean;
  metaError: string | null;
  onRetryMeta: () => void;
}

export function SubmitState({
  error,
  conflictJobId,
  cooldownSeconds,
  hasFieldErrors,
  onDismissConflict,
  metaLoading,
  metaError,
  onRetryMeta,
}: SubmitStateProps) {
  const rateLimited = error !== null && error.status === 429;
  const generalError =
    error !== null && !rateLimited && conflictJobId === null && !hasFieldErrors;

  return (
    <div className={styles.state}>
      {metaLoading ? (
        <p className={styles.info} role="status">
          正在加载配置…
        </p>
      ) : null}
      {metaError === null ? null : (
        <div className={styles.banner} role="alert">
          <span>{metaError}</span>
          <Button size="sm" onClick={onRetryMeta}>
            重试
          </Button>
        </div>
      )}
      {conflictJobId === null ? null : (
        <div className={`${styles.banner} ${styles.warning}`} role="alert">
          <span>{error?.message ?? "该股票今日已有进行中的分析"}</span>
          <div className={styles.actions}>
            <Link className={styles.link} to={`/jobs/${conflictJobId}`} replace>
              查看进行中的任务
            </Link>
            <Button size="sm" onClick={onDismissConflict}>
              取消
            </Button>
          </div>
        </div>
      )}
      {rateLimited && cooldownSeconds > 0 ? (
        <p className={styles.warningText} role="alert">
          {error.message}（请等待 {cooldownSeconds} 秒）
        </p>
      ) : null}
      {generalError ? (
        <p className={styles.errorText} role="alert">
          {error.message}
        </p>
      ) : null}
      {hasFieldErrors && error !== null ? (
        <p className={styles.errorText} role="alert">
          请检查标记的字段后重新提交。
        </p>
      ) : null}
    </div>
  );
}
