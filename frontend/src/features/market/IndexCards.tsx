import type { MarketIndex } from "../../api/types";
import { IndexCard } from "./IndexCard";
import styles from "./MarketPage.module.css";

export interface IndexCardsProps {
  indices: MarketIndex[];
  asOf: string | null;
  fetchedAt: string;
  source: string;
}

export function IndexCards({
  indices,
  asOf,
  fetchedAt,
  source,
}: IndexCardsProps) {
  return (
    <div className={styles.indexGrid} data-testid="market-indices">
      {indices.map((index) => (
        <IndexCard
          key={index.code}
          index={index}
          asOf={asOf}
          fetchedAt={fetchedAt}
          source={source}
        />
      ))}
    </div>
  );
}