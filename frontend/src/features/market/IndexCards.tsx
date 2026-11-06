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

export interface IndexCardsProps {
  indices: MarketIndex[];
  asOf: string | null;
  fetchedAt: string;
  source: string;
}

const TONE_CLASS = {
  up: styles.up,
  down: styles.down,
  flat: styles.flat,
} as const;

export function IndexCards({
  indices,
  asOf,
  fetchedAt,
  source,
}: IndexCardsProps) {
  return (
    <div className={styles.indexGrid} data-testid="market-indices">
      {indices.map((index) => (
        <article
          key={index.code}
          className={styles.indexCard}
          data-testid="index-card"
        >
          <header className={styles.indexHead}>
            <span className={styles.indexName}>{index.name}</span>
            <span className={styles.indexCode}>{index.code}</span>
          </header>
          <strong className={styles.indexPrice}>
            {formatPrice(index.price)}
          </strong>
          <span className={`${styles.indexChange} ${TONE_CLASS[changeTone(index.change_pct)]}`}>
            {formatSignedPct(index.change_pct)}
            <span className={styles.indexAmount}>
              {formatSignedAmount(index.change_amt)}
            </span>
          </span>
          <footer className={styles.indexFoot}>
            {formatMarketTime(asOf ?? fetchedAt)} · {sourceLabel(source)}
          </footer>
        </article>
      ))}
    </div>
  );
}