import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { SearchBox } from "../features/search/SearchBox";
import { metaOptionsQuery } from "../lib/query";
import { Badge } from "../ui";
import { Icon } from "./icons";
import styles from "./TopBar.module.css";
import type { Theme } from "./useTheme";

export interface TopBarProps {
  theme: Theme;
  onToggleTheme: () => void;
}

function ServiceStatus() {
  const { status } = useQuery(metaOptionsQuery);
  const badge =
    status === "pending"
      ? { tone: "neutral" as const, label: "检测中" }
      : status === "error"
        ? { tone: "danger" as const, label: "服务不可用" }
        : { tone: "success" as const, label: "服务正常" };

  return (
    <div
      className={styles.serviceSlot}
      data-testid="service-status"
      title="来自服务端元信息"
    >
      <Badge tone={badge.tone} dot>
        {badge.label}
      </Badge>
    </div>
  );
}

export function TopBar({ theme, onToggleTheme }: TopBarProps) {
  return (
    <header className={styles.topbar}>
      <SearchBox />
      <div className={styles.slots}>
        <button
          type="button"
          className={styles.iconButton}
          onClick={onToggleTheme}
          aria-label={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
          title={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
        >
          <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
        </button>
        <ServiceStatus />
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
  const searchButtonRef = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);

  // The input unmounts on close, which drops focus to <body>; take it back
  // once React has committed the panel away.
  useEffect(() => {
    if (!searchOpen && restoreFocus.current) {
      restoreFocus.current = false;
      searchButtonRef.current?.focus();
    }
  }, [searchOpen]);

  return (
    <header className={styles.mobileHeader}>
      <div className={styles.mobileRow}>
        <span className={styles.mobileTitle}>{title}</span>
        <div className={styles.mobileActions}>
          <button
            ref={searchButtonRef}
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
          <SearchBox
            compact
            autoFocus
            onEscape={() => {
              restoreFocus.current = true;
              onToggleSearch();
            }}
          />
        </div>
      ) : null}
    </header>
  );
}
