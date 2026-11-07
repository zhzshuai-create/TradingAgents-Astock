import { Link, useLocation } from "react-router-dom";

import styles from "./Sidebar.module.css";
import { Icon } from "./icons";
import {
  isNavActive,
  LEGACY_ENTRY_URL,
  PRIMARY_NAV,
  SECONDARY_NAV,
  type IconName,
} from "./navigation";

export interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { pathname } = useLocation();

  return (
    <aside
      className={`${styles.sidebar} ${collapsed ? styles.collapsed : ""}`}
      aria-label="主导航"
    >
      <Link to="/workbench" className={styles.brand} aria-label="AStock Pro 工作台">
        <span className={styles.mark} aria-hidden="true">
          A
        </span>
        <span className={styles.brandName}>AStock Pro</span>
      </Link>

      <nav className={styles.nav} aria-label="页面导航">
        <ul className={styles.list}>
          {PRIMARY_NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                label={item.label}
                icon={item.icon}
                active={isNavActive(pathname, item)}
                collapsed={collapsed}
              />
            </li>
          ))}
        </ul>
        <div className={styles.divider} role="presentation" />
        <ul className={styles.list}>
          {SECONDARY_NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                label={item.label}
                icon={item.icon}
                active={isNavActive(pathname, item)}
                collapsed={collapsed}
              />
            </li>
          ))}
          <li>
            <a
              className={styles.link}
              href={LEGACY_ENTRY_URL}
              target="_blank"
              rel="noreferrer"
              data-testid="sidebar-legacy-entry"
              title={collapsed ? "旧版入口" : undefined}
            >
              <Icon name="external" />
              <span className={styles.label}>旧版入口</span>
            </a>
          </li>
        </ul>
      </nav>

      <button
        type="button"
        className={styles.toggle}
        onClick={onToggle}
        aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
        aria-expanded={!collapsed}
        title={collapsed ? "展开侧栏" : "收起侧栏"}
      >
        <Icon name={collapsed ? "expand" : "collapse"} size={18} />
        <span className={styles.label}>收起</span>
      </button>
    </aside>
  );
}

interface NavLinkProps {
  to: string;
  label: string;
  icon: IconName;
  active: boolean;
  collapsed: boolean;
}

function NavLink({ to, label, icon, active, collapsed }: NavLinkProps) {
  return (
    <Link
      to={to}
      className={`${styles.link} ${active ? styles.active : ""}`}
      aria-current={active ? "page" : undefined}
      title={collapsed ? label : undefined}
    >
      <Icon name={icon} />
      <span className={styles.label}>{label}</span>
    </Link>
  );
}
