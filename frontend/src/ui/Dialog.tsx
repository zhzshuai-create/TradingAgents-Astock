import { useId, type ReactNode } from "react";
import { createPortal } from "react-dom";

import styles from "./Dialog.module.css";
import { useDialogFocus } from "./useDialogFocus";

export interface DialogProps {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
}

export function Dialog({ open, title, children, onClose, footer }: DialogProps) {
  const titleId = useId();
  const panelRef = useDialogFocus(open, onClose);

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
        className={styles.panel}
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
            aria-label="关闭对话框"
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div className={styles.body}>{children}</div>
        {footer === undefined ? null : (
          <footer className={styles.footer}>{footer}</footer>
        )}
      </div>
    </div>,
    document.body,
  );
}
