import type { ReactNode } from "react";

import styles from "./EmptyState.module.css";

export interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <section className={styles.empty}>
      <h2 className={styles.title}>{title}</h2>
      {description === undefined ? null : (
        <p className={styles.description}>{description}</p>
      )}
      {action === undefined ? null : (
        <div className={styles.action}>{action}</div>
      )}
    </section>
  );
}
