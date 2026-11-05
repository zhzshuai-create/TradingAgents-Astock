import { Badge } from "../ui";
import { Icon } from "./icons";
import { SearchSlot } from "./SearchSlot";
import styles from "./TopBar.module.css";
import type { Theme } from "./useTheme";

export interface TopBarProps {
  theme: Theme;
  onToggleTheme: () => void;
}

export function TopBar({ theme, onToggleTheme }: TopBarProps) {
  return (
    <header className={styles.topbar}>
      <SearchSlot />
      <div className={styles.slots}>
        <div className={styles.activeSlot} data-testid="active-job-slot">
          <span className={styles.slotLabel}>进行中</span>
          <span className={styles.slotValue}>暂无任务</span>
        </div>
        <button
          type="button"
          className={styles.iconButton}
          onClick={onToggleTheme}
          aria-label={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
          title={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
        >
          <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
        </button>
        <div
          className={styles.serviceSlot}
          data-testid="service-status"
          title="服务状态将在 P2-04 接入"
        >
          <Badge tone="neutral" dot>
            状态未知
          </Badge>
        </div>
      </div>
    </header>
  );
}

export interface MobileTopBarProps extends TopBarProps {
  title: string;
  searchOpen: boolean;
  onToggleSearch: () => void;
}

export function MobileTopBar({
  title,
  searchOpen,
  onToggleSearch,
  theme,
  onToggleTheme,
}: MobileTopBarProps) {
  return (
    <header className={styles.mobileHeader}>
      <div className={styles.mobileRow}>
        <span className={styles.mobileTitle}>{title}</span>
        <div className={styles.mobileActions}>
          <button
            type="button"
            className={styles.iconButton}
            onClick={onToggleSearch}
            aria-label={searchOpen ? "关闭搜索" : "打开搜索"}
            aria-expanded={searchOpen}
          >
            <Icon name="search" size={18} />
          </button>
          <button
            type="button"
            className={styles.iconButton}
            onClick={onToggleTheme}
            aria-label={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
          </button>
        </div>
      </div>
      {searchOpen ? (
        <div className={styles.mobileSearch}>
          <SearchSlot compact autoFocus />
        </div>
      ) : null}
    </header>
  );
}
