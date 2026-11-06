import type { StaleReason } from "../api/types";
import { STATE_COPY, staleDescription } from "../features/market/copy";
import styles from "./StaleBanner.module.css";

export interface StaleBannerProps {
  reason: StaleReason | null;
}

export function StaleBanner({ reason }: StaleBannerProps) {
  const detail = staleDescription(reason);
  return (
    <div
      className={styles.banner}
      role="status"
      aria-live="polite"
      data-testid="stale-banner"
    >
      <strong className={styles.title}>{STATE_COPY.stale.title}</strong>
      {detail === null ? null : <span className={styles.detail}>{detail}</span>}
    </div>
  );
}
