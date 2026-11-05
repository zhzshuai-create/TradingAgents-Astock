import { Link, useLocation } from "react-router-dom";

import { Button, Drawer } from "../ui";
import styles from "./MobileNav.module.css";
import { Icon } from "./icons";
import {
  isNavActive,
  LEGACY_ENTRY_URL,
  PRIMARY_NAV,
  SECONDARY_NAV,
} from "./navigation";
import type { Theme } from "./useTheme";

export interface MobileNavProps {
  theme: Theme;
  onToggleTheme: () => void;
  moreOpen: boolean;
  onOpenMore: () => void;
  onCloseMore: () => void;
}

export function MobileNav({
  theme,
  onToggleTheme,
  moreOpen,
  onOpenMore,
  onCloseMore,
}: MobileNavProps) {
  const { pathname } = useLocation();
  const secondaryActive = SECONDARY_NAV.some((item) =>
    isNavActive(pathname, item),
  );

  return (
    <>
      <nav
        className={styles.nav}
        aria-label="移动端主导航"
        data-testid="mobile-nav"
      >
        <ul className={styles.list}>
          {PRIMARY_NAV.map((item) => {
            const active = isNavActive(pathname, item);
            return (
              <li key={item.to} className={styles.item}>
                <Link
                  to={item.to}
                  className={`${styles.link} ${active ? styles.active : ""}`}
                  aria-current={active ? "page" : undefined}
                >
                  <Icon name={item.icon} />
                  <span className={styles.label}>{item.label}</span>
                </Link>
              </li>
            );
          })}
          <li className={styles.item}>
            <button
              type="button"
              className={`${styles.link} ${moreOpen || secondaryActive ? styles.active : ""}`}
              onClick={onOpenMore}
              aria-haspopup="dialog"
              aria-expanded={moreOpen}
              aria-current={secondaryActive ? "page" : undefined}
            >
              <Icon name="more" />
              <span className={styles.label}>更多</span>
            </button>
          </li>
        </ul>
      </nav>

      <Drawer open={moreOpen} title="更多" onClose={onCloseMore} side="right">
        <nav aria-label="更多导航">
          <ul className={styles.moreList}>
            {SECONDARY_NAV.map((item) => {
              const active = isNavActive(pathname, item);
              return (
                <li key={item.to}>
                  <Link
                    to={item.to}
                    className={`${styles.moreLink} ${active ? styles.active : ""}`}
                    aria-current={active ? "page" : undefined}
                    onClick={onCloseMore}
                  >
                    <Icon name={item.icon} />
                    <span>{item.label}</span>
                  </Link>
                </li>
              );
            })}
            <li>
              <a
                className={styles.moreLink}
                href={LEGACY_ENTRY_URL}
                target="_blank"
                rel="noreferrer"
                onClick={onCloseMore}
              >
                <Icon name="external" />
                <span>旧版入口</span>
              </a>
            </li>
          </ul>
        </nav>
        <div className={styles.moreSection}>
          <Button variant="secondary" onClick={onToggleTheme}>
            {theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
          </Button>
        </div>
      </Drawer>
    </>
  );
}
