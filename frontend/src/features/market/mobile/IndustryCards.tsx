import type { MarketIndustryRow } from "../../../api/types";
import { changeTone, formatSignedPct } from "../format";
import styles from "../MarketPage.module.css";

export interface IndustryCardsProps {
  top: MarketIndustryRow[];
  bottom: MarketIndustryRow[];
  selectedBoard: string;
  onSelect: (board: string) => void;
}

const TONE_CLASS = {
  up: styles.up,
  down: styles.down,
  flat: styles.flat,
} as const;

function IndustryCardGroup({
  rows,
  variant,
  selectedBoard,
  onSelect,
}: {
  rows: MarketIndustryRow[];
  variant: "top" | "bottom";
  selectedBoard: string;
  onSelect: (board: string) => void;
}) {
  return rows.map((row) => (
    <button
      key={`${variant}-${row.code}`}
      type="button"
      className={styles.industryCard}
      data-testid="industry-card"
      data-variant={variant}
      data-code={row.code}
      data-active={selectedBoard === row.code ? "true" : "false"}
      aria-pressed={selectedBoard === row.code}
      onClick={() => onSelect(row.code)}
    >
      <span className={styles.industryCardHead}>
        <span className={styles.industryCardRank}>{row.rank}</span>
        <span className={styles.industryCardName}>{row.name}</span>
        <span
          className={`${styles.numeric} ${TONE_CLASS[changeTone(row.change_pct)]}`}
        >
          {formatSignedPct(row.change_pct)}
        </span>
      </span>
      <span className={styles.industryCardMeta}>
        上涨 {row.up_count} / 下跌 {row.down_count} · 领涨 {row.leader}{" "}
        <span className={TONE_CLASS[changeTone(row.leader_change)]}>
          {formatSignedPct(row.leader_change)}
        </span>
      </span>
    </button>
  ));
}

/** Below 767px industries render as cards so the page never shows a table. */
export function IndustryCards({
  top,
  bottom,
  selectedBoard,
  onSelect,
}: IndustryCardsProps) {
  return (
    <div className={styles.industryCards} data-testid="industry-cards">
      <IndustryCardGroup
        rows={top}
        variant="top"
        selectedBoard={selectedBoard}
        onSelect={onSelect}
      />
      {bottom.length === 0 ? null : (
        <>
          <h3 className={styles.mobileGroupTitle}>涨幅末位</h3>
          <IndustryCardGroup
            rows={bottom}
            variant="bottom"
            selectedBoard={selectedBoard}
            onSelect={onSelect}
          />
        </>
      )}
    </div>
  );
}