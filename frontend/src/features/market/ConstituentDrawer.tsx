import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { marketConstituentsQuery } from "../../lib/query";
import { DataState, Drawer } from "../../ui";
import {
  changeTone,
  formatPrice,
  formatSignedPct,
} from "./format";
import { CONSTITUENT_LIMIT } from "./marketParams";
import { envelopeState } from "./state";
import styles from "./MarketPage.module.css";

export interface ConstituentDrawerProps {
  board: string;
  industryName: string;
  onClose: () => void;
}

const TONE_CLASS = {
  up: styles.up,
  down: styles.down,
  flat: styles.flat,
} as const;

export function ConstituentDrawer({
  board,
  industryName,
  onClose,
}: ConstituentDrawerProps) {
  const query = useQuery(marketConstituentsQuery(board, CONSTITUENT_LIMIT));
  const envelope = query.data;
  const items = envelope?.data?.items ?? [];

  return (
    <Drawer
      open={board !== ""}
      title={industryName === "" ? "行业成分股" : `${industryName} · 成分股`}
      onClose={onClose}
    >
      <div data-testid="constituent-drawer">
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
                  className={styles.constituentRow}
                  to={`/stocks/${item.code}?tab=valuation`}
                  data-testid="constituent-row"
                >
                  <span className={styles.constituentName}>{item.name}</span>
                  <span className={styles.constituentCode}>{item.code}</span>
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
                </Link>
              </li>
            ))}
          </ul>
        </DataState>
      </div>
    </Drawer>
  );
}