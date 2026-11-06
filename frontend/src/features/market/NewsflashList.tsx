import type { ReactNode } from "react";

import type { NewsflashItem } from "../../api/types";
import { formatMarketTime } from "./format";
import styles from "./MarketPage.module.css";

export interface NewsflashListProps {
  items: NewsflashItem[];
}

// Only http(s) substrings become anchors; everything else stays inert text.
const URL_PATTERN = /https?:\/\/[^\s<>"']+/g;

function linkify(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  let cursor = 0;
  let index = 0;
  for (const match of text.matchAll(URL_PATTERN)) {
    const start = match.index ?? 0;
    const raw = match[0].replace(/[.,;:!?。，；：！？、]+$/, "");
    if (raw === "") {
      continue;
    }
    if (start > cursor) {
      parts.push(text.slice(cursor, start));
    }
    parts.push(
      <a
        key={`link-${index}`}
        href={raw}
        target="_blank"
        rel="noopener noreferrer"
        data-testid="newsflash-link"
      >
        {raw}
      </a>,
    );
    index += 1;
    cursor = start + raw.length;
  }
  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }
  return parts;
}

export function NewsflashList({ items }: NewsflashListProps) {
  return (
    <ul className={styles.newsList} data-testid="newsflash-list">
      {items.map((item, index) => (
        <li
          key={`${item.published_at}-${index}`}
          className={styles.newsItem}
          data-testid="newsflash-item"
        >
          <time className={styles.newsTime}>
            {formatMarketTime(item.published_at)}
          </time>
          <div className={styles.newsBody}>
            <strong className={styles.newsTitle}>{linkify(item.title)}</strong>
            {item.content === "" ? null : (
              <p className={styles.newsText}>{linkify(item.content)}</p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}