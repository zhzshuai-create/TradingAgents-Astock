import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

import {
  marketIndustriesQuery,
  marketNewsflashQuery,
  marketOverviewQuery,
  marketStrongStocksQuery,
} from "../../lib/query";
import { DataState } from "../../ui";
import { ConstituentDrawer } from "./ConstituentDrawer";
import { EMPTY_COPY } from "./copy";
import { IndexCards } from "./IndexCards";
import { IndustryTable } from "./IndustryTable";
import {
  INDUSTRY_TOP_OPTIONS,
  NEWSFLASH_LIMIT,
  parseMarketSearch,
  toMarketSearch,
  type MarketState,
} from "./marketParams";
import { MarketSessionBar } from "./MarketSessionBar";
import { NewsflashList } from "./NewsflashList";
import { envelopeState } from "./state";
import { StrongStocksTable } from "./StrongStocksTable";
import styles from "./MarketPage.module.css";

const SCROLL_PREFIX = "ta:market-scroll:";
const SCROLL_MARKER = "taMarketScroll";

function scrollStorageKey(pathname: string, search: string): string {
  return `${SCROLL_PREFIX}${pathname}${search}`;
}

function isReload(): boolean {
  const [entry] = performance.getEntriesByType(
    "navigation",
  ) as PerformanceNavigationTiming[];
  return entry?.type === "reload";
}

export function MarketPage() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const state = parseMarketSearch(params.toString());

  const overview = useQuery(marketOverviewQuery());
  const industries = useQuery(marketIndustriesQuery(state.top));
  const strong = useQuery(marketStrongStocksQuery(state.date || null));
  const news = useQuery(marketNewsflashQuery(NEWSFLASH_LIMIT));

  const overviewData = overview.data?.data;
  const industriesData = industries.data?.data;
  const strongData = strong.data?.data;
  const newsData = news.data?.data;

  const industryRows = [
    ...(industriesData?.top ?? []),
    ...(industriesData?.bottom ?? []),
  ];
  const selectedIndustry = industryRows.find(
    (row) => row.code === state.board,
  );

  const scrollKey = scrollStorageKey(location.pathname, location.search);
  const restoredScroll = useRef(false);

  useEffect(() => {
    const main = document.getElementById("main-content");
    if (main === null) {
      return undefined;
    }
    const remember = () => {
      try {
        sessionStorage.setItem(scrollKey, String(main.scrollTop));
        window.history.replaceState(
          { ...window.history.state, [SCROLL_MARKER]: true },
          "",
        );
      } catch {
        // storage unavailable: leave the scroll position to the browser
      }
    };
    document.addEventListener("click", remember, true);
    window.addEventListener("popstate", remember);
    return () => {
      document.removeEventListener("click", remember, true);
      window.removeEventListener("popstate", remember);
    };
  }, [scrollKey]);

  const allSettled =
    !overview.isPending &&
    !industries.isPending &&
    !strong.isPending &&
    !news.isPending;

  useEffect(() => {
    if (restoredScroll.current || !allSettled) {
      return;
    }
    restoredScroll.current = true;
    if (isReload() || window.history.state?.[SCROLL_MARKER] !== true) {
      return;
    }
    try {
      const saved = sessionStorage.getItem(scrollKey);
      if (saved !== null) {
        sessionStorage.removeItem(scrollKey);
      }
      window.history.replaceState(
        { ...window.history.state, [SCROLL_MARKER]: false },
        "",
      );
      if (saved === null) {
        return;
      }
      const top = Number(saved);
      const main = document.getElementById("main-content");
      if (Number.isFinite(top) && top > 0 && main !== null) {
        main.scrollTop = top;
      }
    } catch {
      // storage unavailable: stay at the top
    }
  }, [allSettled, scrollKey]);

  function patch(next: Partial<MarketState>) {
    setParams(toMarketSearch({ ...state, ...next }), { replace: true });
  }

  const overviewBlock = envelopeState(overview);
  const industriesBlock = envelopeState(industries);
  const strongBlock = envelopeState(strong);
  const newsBlock = envelopeState(news);

  return (
    <div className={styles.page} data-testid="page-market">
      <header className={styles.pageHead}>
        <h1 className={styles.title}>市场</h1>
        <p className={styles.subtitle}>
          指数、行业与强势股的只读摘要，可钻取到个股工作区。
        </p>
      </header>

      <section className={styles.section} aria-labelledby="market-overview">
        <div className={styles.sectionHead}>
          <h2 id="market-overview" className={styles.sectionTitle}>
            市场概览
          </h2>
        </div>
        <DataState
          state={
            overviewBlock === "ok" && (overviewData?.indices.length ?? 0) === 0
              ? "empty"
              : overviewBlock
          }
          partial={overview.data?.partial ?? false}
          failedBlocks={overview.data?.failed_blocks ?? []}
          staleReason={overview.data?.stale_reason ?? null}
          onRetry={() => void overview.refetch()}
          emptyTitle="暂无市场数据"
          emptyDescription="指数数据暂未返回，稍后再试。"
          skeletonHeight="180px"
        >
          {overview.data !== undefined && overviewData != null ? (
            <>
              <MarketSessionBar
                session={overviewData.market_session}
                asOf={overview.data.as_of}
                fetchedAt={overview.data.fetched_at}
                source={overview.data.source}
              />
              <IndexCards
                indices={overviewData.indices}
                asOf={overview.data.as_of}
                fetchedAt={overview.data.fetched_at}
                source={overview.data.source}
              />
            </>
          ) : null}
        </DataState>
      </section>

      <section className={styles.section} aria-labelledby="market-industries">
        <div className={styles.sectionHead}>
          <h2 id="market-industries" className={styles.sectionTitle}>
            行业排名
          </h2>
          <label className={styles.control}>
            显示条数
            <select
              className={styles.select}
              value={state.top}
              onChange={(event) =>
                patch({ top: Number(event.target.value) as MarketState["top"] })
              }
            >
              {INDUSTRY_TOP_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  Top {option}
                </option>
              ))}
            </select>
          </label>
        </div>
        <DataState
          state={
            industriesBlock === "ok" && industryRows.length === 0
              ? "empty"
              : industriesBlock
          }
          partial={industries.data?.partial ?? false}
          failedBlocks={industries.data?.failed_blocks ?? []}
          staleReason={industries.data?.stale_reason ?? null}
          onRetry={() => void industries.refetch()}
          emptyTitle="暂无行业数据"
          emptyDescription="行业排名暂未返回，稍后再试。"
          skeletonHeight="360px"
        >
          {industriesData != null ? (
            <IndustryTable
              top={industriesData.top}
              bottom={industriesData.bottom}
              selectedBoard={state.board}
              onSelect={(board) => patch({ board })}
            />
          ) : null}
        </DataState>
      </section>

      <section className={styles.section} aria-labelledby="market-strong">
        <div className={styles.sectionHead}>
          <h2 id="market-strong" className={styles.sectionTitle}>
            强势股
          </h2>
          <div className={styles.controls}>
            <label className={styles.control}>
              强势股日期
              <input
                className={styles.input}
                type="date"
                value={state.date}
                onChange={(event) => patch({ date: event.target.value })}
              />
            </label>
            <button
              type="button"
              className={styles.textButton}
              disabled={state.date === ""}
              onClick={() => patch({ date: "" })}
            >
              最新
            </button>
          </div>
        </div>
        <DataState
          state={
            strongBlock === "ok" && (strongData?.items.length ?? 0) === 0
              ? "empty"
              : strongBlock
          }
          partial={strong.data?.partial ?? false}
          failedBlocks={strong.data?.failed_blocks ?? []}
          staleReason={strong.data?.stale_reason ?? null}
          onRetry={() => void strong.refetch()}
          emptyTitle={EMPTY_COPY.strongStocksNonTrading}
          emptyDescription="强势股数据在交易日收盘后更新。"
          skeletonHeight="320px"
        >
          {strongData != null ? (
            <StrongStocksTable
              items={strongData.items}
              activeTheme={state.theme}
              onThemeChange={(theme) => patch({ theme })}
            />
          ) : null}
        </DataState>
      </section>

      <section className={styles.section} aria-labelledby="market-newsflash">
        <div className={styles.sectionHead}>
          <h2 id="market-newsflash" className={styles.sectionTitle}>
            快讯
          </h2>
          {news.data?.as_of ? (
            <span className={styles.sectionMeta}>
              截至 {news.data.as_of.slice(11, 16)}
            </span>
          ) : null}
        </div>
        <DataState
          state={
            newsBlock === "ok" && (newsData?.items.length ?? 0) === 0
              ? "empty"
              : newsBlock
          }
          partial={news.data?.partial ?? false}
          failedBlocks={news.data?.failed_blocks ?? []}
          staleReason={news.data?.stale_reason ?? null}
          onRetry={() => void news.refetch()}
          emptyTitle="暂无快讯"
          emptyDescription="快讯暂未返回，稍后再试。"
          skeletonHeight="260px"
        >
          {newsData != null ? (
            <NewsflashList items={newsData.items} />
          ) : null}
        </DataState>
      </section>

      <ConstituentDrawer
        board={state.board}
        industryName={selectedIndustry?.name ?? ""}
        onClose={() => patch({ board: "" })}
      />
    </div>
  );
}