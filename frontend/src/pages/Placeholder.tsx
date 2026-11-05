import type { ReactNode } from "react";

import { Badge } from "../ui";
import styles from "./pages.module.css";

export interface PlaceholderProps {
  title: string;
  description: string;
  testId: string;
  action?: ReactNode;
}

export function Placeholder({
  title,
  description,
  testId,
  action,
}: PlaceholderProps) {
  return (
    <section className={styles.page} data-testid={testId}>
      <Badge tone="info">页面骨架</Badge>
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.lead}>{description}</p>
      {action ? <div className={styles.actions}>{action}</div> : null}
    </section>
  );
}
