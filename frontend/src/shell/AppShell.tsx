import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import styles from "./AppShell.module.css";
import { MobileNav } from "./MobileNav";
import { pageTitle } from "./navigation";
import { Sidebar } from "./Sidebar";
import { MobileTopBar, TopBar } from "./TopBar";
import { useTheme } from "./useTheme";

export const SIDEBAR_STORAGE_KEY = "astock.sidebar-collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [moreOpen, setMoreOpen] = useState(false);
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false);
  const { theme, toggle } = useTheme();
  const { pathname } = useLocation();

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed));
    } catch {
      // Storage can be blocked (private mode); the layout still works.
    }
  }, [collapsed]);

  useEffect(() => {
    setMoreOpen(false);
    setMobileSearchOpen(false);
  }, [pathname]);

  return (
    <div className={`${styles.shell} ${collapsed ? styles.collapsed : ""}`}>
      <a className={styles.skipLink} href="#main-content">
        跳到主要内容
      </a>
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed((value) => !value)}
      />
      <div className={styles.main}>
        <TopBar theme={theme} onToggleTheme={toggle} />
        <MobileTopBar
          title={pageTitle(pathname)}
          searchOpen={mobileSearchOpen}
          onToggleSearch={() => setMobileSearchOpen((value) => !value)}
          theme={theme}
          onToggleTheme={toggle}
        />
        <main id="main-content" className={styles.content} tabIndex={-1}>
          <Outlet />
        </main>
      </div>
      <MobileNav
        theme={theme}
        onToggleTheme={toggle}
        moreOpen={moreOpen}
        onOpenMore={() => setMoreOpen(true)}
        onCloseMore={() => setMoreOpen(false)}
      />
    </div>
  );
}
