import type { ReportSection } from "../../api/types";
import { sectionNumber } from "./sections";
import styles from "./ReportToc.module.css";

export interface ReportTocProps {
  sections: ReportSection[];
  activeId: string | null;
  onJump: (sectionId: string) => void;
}

/** Desktop table of contents: contract order, present sections only. */
export function ReportToc({ sections, activeId, onJump }: ReportTocProps) {
  if (sections.length === 0) {
    return null;
  }
  return (
    <nav className={styles.toc} aria-label="章节目录" data-testid="report-toc">
      <p className={styles.heading}>目录</p>
      <ol className={styles.list}>
        {sections.map((section) => {
          const active = section.id === activeId;
          return (
            <li key={section.id}>
              <a
                className={active ? `${styles.link} ${styles.active}` : styles.link}
                href={`#${section.id}`}
                data-testid="toc-link"
                data-section-id={section.id}
                aria-current={active ? "location" : undefined}
                onClick={(event) => {
                  event.preventDefault();
                  onJump(section.id);
                }}
              >
                <span className={styles.number}>{sectionNumber(section.id)}</span>
                <span className={styles.title}>{section.title}</span>
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
