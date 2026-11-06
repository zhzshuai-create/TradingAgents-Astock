import type { MarketIndex } from "../../../api/types";
import { IndexCard } from "../IndexCard";
import styles from "../MarketPage.module.css";

export interface IndexStripProps {
  indices: MarketIndex[];
  asOf: string | null;
  fetchedAt: string;
  source: string;
}

/** Below 767px the three cards scroll horizontally inside this container. */
export function IndexStrip({
  indices,
  asOf,
  fetchedAt,
  source,
}: IndexStripProps) {
  return (
    <div className={styles.indexStrip} data-testid="index-strip">
      {indices.map((index) => (
        <IndexCard
          key={index.code}
          index={index}
          asOf={asOf}
          fetchedAt={fetchedAt}
          source={source}
          className={styles.indexSlide}
        />
      ))}
    </div>
  );
}