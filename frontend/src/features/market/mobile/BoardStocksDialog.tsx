import { useQuery } from "@tanstack/react-query";
import { useEffect, useId } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";

import { marketConstituentsQuery } from "../../../lib/query";
import { DataState } from "../../../ui";
import { useDialogFocus } from "../../../ui/useDialogFocus";
import {
  changeTone,
  formatPrice,
  formatSignedPct,
} from "../format";
import { CONSTITUENT_LIMIT } from "../marketParams";
import { envelopeState } from "../state";
import styles from "../MarketPage.module.css";

export interface BoardStocksDialogProps {
  board: string;
  industryName: string;
  onClose: () => void;
}

const TONE_CLASS = {
  up: styles.up,
  down: styles.down,
  flat: styles.flat,
} as const;

/** Full-screen constituent layer used below 767px; `board` query drives it. */
export function BoardStocksDialog({
  board,
  industryName,
  onClose,
}: BoardStocksDialogProps) {
  const titleId = useId();
  const open = board !== "";
  const panelRef = useDialogFocus(open, onClose);
  const query = useQuery(marketConstituentsQuery(board, CONSTITUENT_LIMIT));
  const envelope = query.data;
  const items = envelope?.data?.items ?? [];

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const targets = [
      document.body,
      ...document.querySelectorAll<HTMLElement>("[data-scroll-lock]"),
    ];
    const previous = targets.map((target) => target.style.overflow);
    for (const target of targets) {
      target.style.overflow = "hidden";
    }
    return () => {
      targets.forEach((target, index) => {
        target.style.overflow = previous[index] ?? "";
      });
    };
  }, [open]);

  if (!open) {
    return null;
  }

  return createPortal(
    <section
      ref={panelRef}
      className={styles.boardPanel}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      tabIndex={-1}
      data-testid="board-stocks-dialog"
    >
      <header className={styles.boardHeader}>
        <h2 id={titleId} className={styles.boardTitle}>
          {industryName === "" ? "行业成分股" : `${industryName} · 成分股`}
        </h2>
        <button
          type="button"
          className={styles.boardClose}
          aria-label="关闭成分股"
          onClick={onClose}
        >
          ×
        </button>
      </header>
      <div className={styles.boardBody}>
        <DataState
          state={envelopeState(query)}
          partial={envelope?.partial ?? false}
          failedBlocks={envelope?.failed_blocks ?? []}
          staleReason={envelope?.stale_reason ?? null}
          onRetry={() => void query.refetch()}
          emptyTitle="暂无成分股"
          emptyDescription="该行业暂未返回成分股。"
          skeletonHeight="240px"
        >
          <ul className={styles.constituentList}>
            {items.map((item) => (
              <li key={item.code}>
                <Link
                  className={styles.boardStockRow}
                  to={`/stocks/${item.code}?tab=valuation`}
                  data-testid="board-stock-row"
                >
                  <span className={styles.boardStockMain}>
                    <span className={styles.constituentName}>{item.name}</span>
                    <span className={styles.constituentCode}>{item.code}</span>
                  </span>
                  <span className={styles.boardStockNumbers}>
                    <span className={styles.constituentPrice}>
                      {formatPrice(item.price)}
                    </span>
                    <span
                      className={`${styles.numeric} ${
                        TONE_CLASS[changeTone(item.change_pct)]
                      }`}
                    >
                      {formatSignedPct(item.change_pct)}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </DataState>
      </div>
    </section>,
    document.body,
  );
}