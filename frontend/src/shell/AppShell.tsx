import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { usePreferences } from "../lib/preferences";
import { ActiveJobBar } from "./ActiveJobBar";
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
  const { density } = usePreferences();
  const { pathname } = useLocation();
  // The workbench puts the active job in its own content block; elsewhere the
  // shell keeps one strip above the page.
  const showActiveBar = pathname !== "/workbench";

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed));
    } catch {
      // Storage can be blocked (private mode); the layout still works.
    }
  }, [collapsed]);

  // Before paint so a stored "compact" never flashes a comfortable layout.
  // Like the theme attribute, it stays after unmount.
  useLayoutEffect(() => {
    document.documentElement.dataset.density = density;
  }, [density]);

  useEffect(() => {
    setMoreOpen(false);
    setMobileSearchOpen(false);
  }, [pathname]);

  // The shell owns the tab title; pages never set it themselves. The first
  // render only names the tab — moving focus then would steal it from the URL.
  // Comparing the stored pathname also keeps StrictMode's double mount quiet.
  const lastPath = useRef(pathname);
  useEffect(() => {
    const label = pageTitle(pathname);
    document.title = label === "AStock Pro" ? label : `${label} · AStock Pro`;
    if (lastPath.current === pathname) {
      return;
    }
    lastPath.current = pathname;
    document.getElementById("main-content")?.focus({ preventScroll: true });
  }, [pathname]);

  return (
    <div className={`${styles.shell} ${collapsed ? styles.collapsed : ""}`}>
      <a
        className={styles.skipLink}
        href="#main-content"
        onClick={(event) => {
          // Browsers disagree on focusing a fragment target; own it here.
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
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
        {showActiveBar ? <ActiveJobBar /> : null}
        <main
          id="main-content"
          className={styles.content}
          data-scroll-lock
          tabIndex={-1}
        >
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
