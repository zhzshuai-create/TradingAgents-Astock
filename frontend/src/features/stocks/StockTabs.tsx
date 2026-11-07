import {
  STOCK_TABS,
  STOCK_TAB_LABELS,
  type StockTab,
} from "./stockParams";
import styles from "./StockPage.module.css";

export interface StockTabsProps {
  active: StockTab;
  onChange: (tab: StockTab) => void;
}

export function StockTabs({ active, onChange }: StockTabsProps) {
  return (
    <div
      className={styles.tabs}
      role="tablist"
      aria-label="股票工作区页签"
      data-testid="stock-tabs"
      data-scroll="x"
    >
      {STOCK_TABS.map((tab) => (
        <button
          key={tab}
          type="button"
          role="tab"
          id={`stock-tab-${tab}`}
          aria-selected={tab === active}
          aria-controls="stock-tab-panel"
          className={styles.tab}
          data-testid="stock-tab"
          data-tab={tab}
          data-active={tab === active ? "true" : "false"}
          onClick={() => onChange(tab)}
        >
          {STOCK_TAB_LABELS[tab]}
        </button>
      ))}
    </div>
  );
}
