import { useEffect, useId, type ReactNode } from "react";
import { createPortal } from "react-dom";

import styles from "./Drawer.module.css";
import { useDialogFocus } from "./useDialogFocus";

export type DrawerSide = "left" | "right" | "bottom";

export interface DrawerProps {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
  side?: DrawerSide;
}

export function Drawer({
  open,
  title,
  children,
  onClose,
  footer,
  side = "right",
}: DrawerProps) {
  const titleId = useId();
  const panelRef = useDialogFocus(open, onClose);

  // The page behind a drawer must not scroll with it. The shell scrolls a
  // content element, not body, so both kinds of container are locked.
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
    <div
      className={styles.backdrop}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        ref={panelRef}
        className={`${styles.panel} ${styles[side]}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className={styles.header}>
          <h2 id={titleId} className={styles.title}>
            {title}
          </h2>
          <button
            type="button"
            className={styles.close}
            aria-label="关闭抽屉"
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div className={styles.body} data-testid="drawer-body">{children}</div>
        {footer === undefined ? null : (
          <footer className={styles.footer}>{footer}</footer>
        )}
      </div>
    </div>,
    document.body,
  );
}
