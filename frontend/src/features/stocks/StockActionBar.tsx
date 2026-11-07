import { Button } from "../../ui";
import type { StockPrimaryAction } from "./StockHeader";
import styles from "./StockPage.module.css";

export interface StockActionBarProps {
  primary: StockPrimaryAction;
}

/** Fixed above the bottom nav; the desktop header keeps its own button. */
export function StockActionBar({ primary }: StockActionBarProps) {
  return (
    <div className={styles.actionBar} data-testid="stock-action-bar">
      <Button
        variant="primary"
        className={styles.actionBarButton}
        onClick={primary.onClick}
        data-testid="stock-primary-action"
      >
        {primary.label}
      </Button>
    </div>
  );
}
