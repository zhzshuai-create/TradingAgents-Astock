import { useQuery } from "@tanstack/react-query";

import { stockNewsQuery } from "../../lib/query";
import { REFRESH_INTERVALS, usePolling } from "../../lib/useVisibleRefetch";
import { DataState } from "../../ui";
import { sourceLabel } from "../market/copy";
import { envelopeState } from "../market/state";
import { STOCK_NEWS_LIMIT } from "./stockParams";
import styles from "./StockPage.module.css";

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function formatNewsTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Only absolute http(s) URLs become anchors; everything else stays text. */
export function safeHref(raw: string): string | null {
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? raw
      : null;
  } catch {
    return null;
  }
}

export function NewsTab({ ticker }: { ticker: string }) {
  const query = useQuery({
    ...stockNewsQuery(ticker, STOCK_NEWS_LIMIT),
    ...usePolling(REFRESH_INTERVALS.stock.news),
  });
  const state = envelopeState(query);
  const items = query.data?.data?.items ?? [];

  return (
    <div className={styles.tabPanel} data-testid="stock-news">
      <DataState
        state={state === "ok" && items.length === 0 ? "empty" : state}
        partial={query.data?.partial ?? false}
        failedBlocks={query.data?.failed_blocks ?? []}
        staleReason={query.data?.stale_reason ?? null}
        onRetry={() => void query.refetch()}
        skeletonHeight="320px"
        emptyTitle="暂无新闻"
        emptyDescription="这只股票近期没有返回新闻。"
      >
        <ul className={styles.newsList}>
          {items.map((item, index) => {
            const href = safeHref(item.url);
            return (
              <li
                className={styles.newsItem}
                data-testid="stock-news-item"
                key={`${item.published_at}-${index}`}
              >
                <div className={styles.newsHead}>
                  {href === null ? (
                    <span className={styles.newsTitle}>{item.title}</span>
                  ) : (
                    <a
                      className={styles.newsTitle}
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      data-testid="stock-news-link"
                    >
                      {item.title}
                    </a>
                  )}
                  <span className={styles.newsMeta}>
                    {sourceLabel(item.source)}
                  </span>
                  <time
                    className={styles.newsMeta}
                    dateTime={item.published_at}
                  >
                    {formatNewsTime(item.published_at)}
                  </time>
                </div>
                {item.content === "" ? null : (
                  <p className={styles.newsBody}>{item.content}</p>
                )}
              </li>
            );
          })}
        </ul>
      </DataState>
    </div>
  );
}
