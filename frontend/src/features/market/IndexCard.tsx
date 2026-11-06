import type { MarketIndex } from "../../api/types";
import { sourceLabel } from "./copy";
import {
  changeTone,
  formatMarketTime,
  formatPrice,
  formatSignedAmount,
  formatSignedPct,
} from "./format";
import styles from "./MarketPage.module.css";

const TONE_CLASS = {
  up: styles.up,
  down: styles.down,
  flat: styles.flat,
} as const;

export interface IndexCardProps {
  index: MarketIndex;
  asOf: string | null;
  fetchedAt: string;
  source: string;
  className?: string;
}

export function IndexCard({
  index,
  asOf,
  fetchedAt,
  source,
  className,
}: IndexCardProps) {
  return (
    <article
      className={`${styles.indexCard} ${className ?? ""}`.trim()}
      data-testid="index-card"
    >
      <header className={styles.indexHead}>
        <span className={styles.indexName}>{index.name}</span>
        <span className={styles.indexCode}>{index.code}</span>
      </header>
      <strong className={styles.indexPrice}>{formatPrice(index.price)}</strong>
      <span
        className={`${styles.indexChange} ${TONE_CLASS[changeTone(index.change_pct)]}`}
      >
        {formatSignedPct(index.change_pct)}
        <span className={styles.indexAmount}>
          {formatSignedAmount(index.change_amt)}
        </span>
      </span>
      <footer className={styles.indexFoot}>
        {formatMarketTime(asOf ?? fetchedAt)} · {sourceLabel(source)}
      </footer>
    </article>
  );
}