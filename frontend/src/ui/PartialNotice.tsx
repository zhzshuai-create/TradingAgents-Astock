import { blockLabel, PARTIAL_COPY } from "../features/market/copy";
import styles from "./PartialNotice.module.css";

export interface PartialNoticeProps {
  blocks: string[];
}

export function PartialNotice({ blocks }: PartialNoticeProps) {
  return (
    <div className={styles.notice} data-testid="partial-notice">
      <strong className={styles.title}>{PARTIAL_COPY}</strong>
      {blocks.length === 0 ? null : (
        <span className={styles.blocks} data-testid="partial-blocks">
          {blocks.map(blockLabel).join("、")}
        </span>
      )}
    </div>
  );
}
