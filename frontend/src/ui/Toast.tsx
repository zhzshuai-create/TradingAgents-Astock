import { useEffect } from "react";
import { createPortal } from "react-dom";

import styles from "./Toast.module.css";

export type ToastTone = "info" | "success" | "warning" | "danger";

export interface ToastProps {
  open: boolean;
  title: string;
  description?: string;
  tone?: ToastTone;
  onClose: () => void;
  durationMs?: number;
}

export function Toast({
  open,
  title,
  description,
  tone = "info",
  onClose,
  durationMs = 4000,
}: ToastProps) {
  useEffect(() => {
    if (!open || durationMs <= 0) {
      return;
    }
    const timer = window.setTimeout(onClose, durationMs);
    return () => window.clearTimeout(timer);
  }, [open, durationMs, onClose]);

  if (!open) {
    return null;
  }

  return createPortal(
    <div
      className={`${styles.toast} ${styles[tone]}`}
      role="status"
      aria-live="polite"
    >
      <div className={styles.content}>
        <strong className={styles.title}>{title}</strong>
        {description === undefined ? null : (
          <p className={styles.description}>{description}</p>
        )}
      </div>
      <button
        type="button"
        className={styles.close}
        aria-label="关闭提示"
        onClick={onClose}
      >
        ×
      </button>
    </div>,
    document.body,
  );
}
