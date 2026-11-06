import type { MarketSession } from "../../api/types";
import { sessionLabel, sourceLabel } from "./copy";
import { formatMarketTime } from "./format";
import styles from "./MarketPage.module.css";

export interface MarketSessionBarProps {
  session: MarketSession;
  asOf: string | null;
  fetchedAt: string;
  source: string;
}

export function MarketSessionBar({
  session,
  asOf,
  fetchedAt,
  source,
}: MarketSessionBarProps) {
  const updated = asOf ?? fetchedAt;
  return (
    <div className={styles.sessionBar} data-testid="market-session">
      <span className={styles.sessionName} data-session={session}>
        {sessionLabel(session)}
      </span>
      <span className={styles.sessionMeta}>
        最近更新 {formatMarketTime(updated)}
      </span>
      <span className={styles.sessionMeta}>来源 {sourceLabel(source)}</span>
    </div>
  );
}