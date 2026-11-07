import type { MarketIndustryRow } from "../../api/types";
import {
  changeTone,
  formatSignedPct,
} from "./format";
import styles from "./MarketPage.module.css";

export interface IndustryTableProps {
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

function IndustryRows({
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
    <tr
      key={`${variant}-${row.code}`}
      className={styles.industryRow}
      data-testid="industry-row"
      data-variant={variant}
      data-code={row.code}
      data-active={selectedBoard === row.code ? "true" : "false"}
      onClick={() => onSelect(row.code)}
    >
      <td className={styles.rank}>{row.rank}</td>
      <th scope="row">
        <button
          type="button"
          className={styles.industryButton}
          onClick={(event) => {
            event.stopPropagation();
            onSelect(row.code);
          }}
        >
          {row.name}
        </button>
      </th>
      <td className={`${styles.numeric} ${TONE_CLASS[changeTone(row.change_pct)]}`}>
        {formatSignedPct(row.change_pct)}
      </td>
      <td className={styles.numeric}>
        <span className={styles.up}>{row.up_count}</span>
        <span className={styles.countDivider}>/</span>
        <span className={styles.down}>{row.down_count}</span>
      </td>
      <td className={styles.leaderCell}>
        <span>{row.leader}</span>
        <span className={TONE_CLASS[changeTone(row.leader_change)]}>
          {formatSignedPct(row.leader_change)}
        </span>
      </td>
    </tr>
  ));
}

export function IndustryTable({
  top,
  bottom,
  selectedBoard,
  onSelect,
}: IndustryTableProps) {
  return (
    <div className={styles.tableScroll}>
      <table className={styles.table} data-testid="industry-table">
        <caption className="sr-only">行业排名</caption>
        <thead>
          <tr>
            <th scope="col" className={styles.rank}>
              排名
            </th>
            <th scope="col">行业</th>
            <th scope="col" className={styles.numeric}>
              涨跌幅
            </th>
            <th scope="col" className={styles.numeric}>
              上涨/下跌
            </th>
            <th scope="col">领涨股</th>
          </tr>
        </thead>
        <tbody>
          <IndustryRows
            rows={top}
            variant="top"
            selectedBoard={selectedBoard}
            onSelect={onSelect}
          />
          {bottom.length === 0 ? null : (
            <>
              <tr className={styles.groupRow}>
                <th scope="rowgroup" colSpan={5}>
                  涨幅末位
                </th>
              </tr>
              <IndustryRows
                rows={bottom}
                variant="bottom"
                selectedBoard={selectedBoard}
                onSelect={onSelect}
              />
            </>
          )}
        </tbody>
      </table>
    </div>
  );
}