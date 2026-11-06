import type { ReactNode } from "react";

import type { StaleReason } from "../api/types";
import { type DataStateValue, STATE_COPY } from "../features/market/copy";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";
import { PartialNotice } from "./PartialNotice";
import { Skeleton } from "./Skeleton";
import { StaleBanner } from "./StaleBanner";
import styles from "./DataState.module.css";

export interface DataStateProps {
  state: DataStateValue;
  children?: ReactNode;
  /** Modifier, not a fifth state (p4-backlog D4). */
  partial?: boolean;
  failedBlocks?: string[];
  staleReason?: StaleReason | null;
  onRetry?: () => void;
  emptyTitle?: string;
  emptyDescription?: string;
  /** Loading skeleton and ok/stale content share this height (DS-04). */
  skeletonHeight?: string;
  label?: string;
}

export function DataState({
  state,
  children,
  partial = false,
  failedBlocks = [],
  staleReason = null,
  onRetry,
  emptyTitle,
  emptyDescription,
  skeletonHeight = "320px",
  label,
}: DataStateProps) {
  if (state === "loading") {
    return (
      <div
        className={styles.loading}
        style={{ height: skeletonHeight }}
        data-testid="data-state-loading"
        data-state="loading"
        aria-busy="true"
        aria-label={STATE_COPY.loading.label}
      >
        <Skeleton width="42%" height="1.75rem" />
        <Skeleton width="72%" height="1rem" />
        <Skeleton width="100%" height="1rem" />
        <Skeleton width="100%" height="7rem" radius="var(--radius-md)" />
      </div>
    );
  }

  if (state === "error") {
    return (
      <div
        className={styles.panel}
        data-testid="data-state-error"
        data-state="error"
        role="alert"
      >
        <strong className={styles.panelTitle}>
          {STATE_COPY.error.title}
        </strong>
        {onRetry === undefined ? null : (
          <Button variant="secondary" onClick={onRetry}>
            {STATE_COPY.error.retry}
          </Button>
        )}
      </div>
    );
  }

  if (state === "empty") {
    return (
      <div data-testid="data-state-empty" data-state="empty">
        <EmptyState
          title={emptyTitle ?? STATE_COPY.empty.title}
          description={emptyDescription}
        />
      </div>
    );
  }

  return (
    <div
      className={styles.content}
      style={{ minHeight: skeletonHeight }}
      data-testid={`data-state-${state}`}
      data-state={state}
      data-partial={partial ? "true" : "false"}
      aria-label={label}
    >
      {state === "stale" ? <StaleBanner reason={staleReason} /> : null}
      {partial ? <PartialNotice blocks={failedBlocks} /> : null}
      {children}
    </div>
  );
}
