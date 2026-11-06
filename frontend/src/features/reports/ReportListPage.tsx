import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";

import { displayErrorMessage } from "../../api/errors";
import { listReports } from "../../api/reports";
import type { ReportSummary } from "../../api/types";
import { queryKeys } from "../../lib/query";
import { Button, Dialog, EmptyState, Skeleton } from "../../ui";
import { REPORT_RATING_META } from "./format";
import { ReportCards } from "./ReportCards";
import { ReportFilters } from "./ReportFilters";
import { ReportTable } from "./ReportTable";
import {
  parseReportListSearch,
  reportListStateHasFilters,
  REPORT_RATING_ORDER,
  toReportListFilters,
  toReportListSearch,
  type ReportListState,
} from "./listParams";
import styles from "./ReportListPage.module.css";

/** A back navigation rebuilds at most this many pages (20 rows each). */
const MAX_RESTORE_PAGES = 20;

/**
 * Scroll belongs to the filtered list, not to one cursor: a paginated return
 * rebuilds the pages from the first one, so the cursor must not split the key.
 */
function scrollStorageKey(pathname: string, search: string): string {
  const params = new URLSearchParams(search);
  params.delete("cursor");
  const query = params.toString();
  return `ta:reports-scroll:${pathname}${query ? `?${query}` : ""}`;
}

function chipLabels(state: ReportListState): string[] {
  const chips: string[] = [];
  if (state.ratings.length < REPORT_RATING_ORDER.length) {
    chips.push(
      `评级 ${state.ratings
        .map((rating) => REPORT_RATING_META[rating].label)
        .join("、")}`,
    );
  }
  if (state.ticker !== "") {
    chips.push(`股票 ${state.ticker}`);
  }
  if (state.dateFrom !== "" && state.dateTo !== "") {
    chips.push(`分析日期 ${state.dateFrom} 至 ${state.dateTo}`);
  } else if (state.dateFrom !== "") {
    chips.push(`分析日期 ${state.dateFrom} 起`);
  } else if (state.dateTo !== "") {
    chips.push(`分析日期截至 ${state.dateTo}`);
  }
  return chips;
}

export function ReportListPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const state = parseReportListSearch(params.toString());
  const filters = toReportListFilters(state);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const restoredScroll = useRef(false);
  // A cursor in the URL means "this many pages were loaded"; a cursor is the
  // pageParam of the last page, so the pages are rebuilt from the first one.
  const [restoreCursor, setRestoreCursor] = useState<string | null>(
    () => state.cursor,
  );

  const query = useInfiniteQuery({
    queryKey: queryKeys.reports(filters),
    queryFn: ({ pageParam, signal }) =>
      listReports({ ...filters, cursor: pageParam ?? undefined }, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    staleTime: 0,
    retry: false,
  });

  const lastPageParam =
    query.data === undefined
      ? null
      : ((query.data.pageParams[query.data.pageParams.length - 1] ?? null) as
          | string
          | null);

  useEffect(() => {
    if (restoreCursor !== null && state.cursor === null) {
      setRestoreCursor(null);
    }
  }, [restoreCursor, state.cursor]);

  useEffect(() => {
    if (restoreCursor === null || query.data === undefined) {
      return;
    }
    if (lastPageParam === restoreCursor) {
      setRestoreCursor(null);
      return;
    }
    if (!query.hasNextPage || query.isFetchingNextPage) {
      if (!query.hasNextPage) {
        setRestoreCursor(null);
      }
      return;
    }
    if (query.data.pages.length >= MAX_RESTORE_PAGES) {
      setRestoreCursor(null);
      return;
    }
    void query.fetchNextPage();
  }, [lastPageParam, query, restoreCursor]);

  // The cursor lives in the URL as an opaque token; loading a page updates it.
  // Unknown or malformed deep-link values are dropped on the same pass so the
  // two rewrites cannot undo each other. While pages are being rebuilt the
  // target cursor stays in the URL.
  useEffect(() => {
    const desired = toReportListSearch({
      ...state,
      cursor:
        query.data === undefined ? state.cursor : restoreCursor ?? lastPageParam,
    });
    if (desired !== params.toString()) {
      setParams(desired, { replace: true });
    }
  }, [lastPageParam, params, query.data, restoreCursor, setParams, state]);

  // A14: the list scrolls inside #main-content, which the browser's own
  // history restore does not cover. The shell resets that container to the top
  // as a navigation starts, while the list is still mounted, so capture the
  // last position on the way out (click capture, back) rather than on scroll.
  useEffect(() => {
    const key = scrollStorageKey(location.pathname, location.search);
    const main = document.getElementById("main-content");
    if (main === null) {
      return;
    }
    let last = -1;
    const remember = () => {
      const top = main.scrollTop;
      if (top === last) {
        return;
      }
      last = top;
      try {
        sessionStorage.setItem(key, String(top));
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
  }, [location.pathname, location.search]);

  useEffect(() => {
    if (
      restoredScroll.current ||
      restoreCursor !== null ||
      query.data === undefined
    ) {
      return;
    }
    restoredScroll.current = true;
    const key = scrollStorageKey(location.pathname, location.search);
    let saved: string | null = null;
    try {
      saved = sessionStorage.getItem(key);
      if (saved !== null) {
        sessionStorage.removeItem(key);
      }
    } catch {
      return;
    }
    if (saved === null) {
      return;
    }
    const top = Number(saved);
    if (!Number.isFinite(top) || top <= 0) {
      return;
    }
    const main = document.getElementById("main-content");
    if (main !== null) {
      main.scrollTop = top;
    }
  }, [location.pathname, location.search, query.data, restoreCursor]);

  function applyFilters(patch: Partial<Omit<ReportListState, "cursor">>) {
    const next: ReportListState = { ...state, ...patch, cursor: null };
    setParams(toReportListSearch(next), { replace: true });
  }

  function resetFilters() {
    setParams("", { replace: true });
  }

  const seen = new Set<string>();
  const reports: ReportSummary[] = [];
  for (const page of query.data?.pages ?? []) {
    for (const report of page.items) {
      if (!seen.has(report.meta.report_id)) {
        seen.add(report.meta.report_id);
        reports.push(report);
      }
    }
  }

  const chips = chipLabels(state);

  return (
    <section className={styles.page} data-testid="page-reports">
      <header className={styles.header}>
        <div className={styles.headRow}>
          <div className={styles.heading}>
            <h1 className={styles.title}>报告</h1>
            <p className={styles.lead}>按股票、日期和评级查找历史报告。</p>
          </div>
          <div className={styles.mobileAction} data-testid="report-filter-open">
            <Button onClick={() => setFiltersOpen(true)}>筛选</Button>
          </div>
        </div>
        {chips.length === 0 ? null : (
          <ul className={styles.chips} data-testid="report-filter-chips">
            {chips.map((chip) => (
              <li
                className={styles.chip}
                key={chip}
                data-testid="report-filter-chip"
              >
                {chip}
              </li>
            ))}
          </ul>
        )}
      </header>

      <section className={styles.filtersPanel} aria-label="报告筛选">
        <ReportFilters
          state={state}
          onChange={applyFilters}
          onReset={resetFilters}
        />
      </section>

      {query.isPending ? (
        <div className={styles.skeleton} data-testid="reports-loading">
          <Skeleton height="56px" />
          <Skeleton height="56px" />
          <Skeleton height="56px" />
          <Skeleton height="56px" />
        </div>
      ) : query.isError && query.data === undefined ? (
        <div className={styles.errorPanel} role="alert">
          <span>{displayErrorMessage(query.error)}</span>
          <Button size="sm" onClick={() => void query.refetch()}>
            重试
          </Button>
        </div>
      ) : reports.length === 0 ? (
        reportListStateHasFilters(state) ? (
          <div data-testid="reports-filtered-empty">
            <EmptyState
              title="没有符合条件的报告"
              description="换一组筛选条件，或清空筛选查看全部报告。"
              action={<Button onClick={resetFilters}>清空筛选</Button>}
            />
          </div>
        ) : (
          <div data-testid="reports-empty">
            <EmptyState
              title="还没有报告"
              description="完成一次分析后，报告会出现在这里。"
              action={
                <Button
                  variant="primary"
                  onClick={() => navigate("/workbench?launch=1")}
                >
                  开始一次分析
                </Button>
              }
            />
          </div>
        )
      ) : (
        <div className={styles.results}>
          <div className={styles.tableArea}>
            <ReportTable reports={reports} />
          </div>
          <div className={styles.cardArea}>
            <ReportCards reports={reports} />
          </div>
          <div className={styles.more}>
            {query.isFetchNextPageError ? (
              <div className={styles.errorPanel} role="alert">
                <span>加载更多失败，已加载的报告仍然保留。</span>
                <Button size="sm" onClick={() => void query.fetchNextPage()}>
                  重试
                </Button>
              </div>
            ) : null}
            {query.hasNextPage ? (
              <Button
                onClick={() => void query.fetchNextPage()}
                disabled={query.isFetchingNextPage}
              >
                {query.isFetchingNextPage ? "加载中…" : "加载更多"}
              </Button>
            ) : null}
          </div>
        </div>
      )}

      <Dialog
        open={filtersOpen}
        title="筛选报告"
        fullscreenOnMobile
        onClose={() => setFiltersOpen(false)}
        footer={
          <Button variant="primary" onClick={() => setFiltersOpen(false)}>
            应用筛选
          </Button>
        }
      >
        <ReportFilters
          state={state}
          onChange={applyFilters}
          onReset={resetFilters}
          compact
          testId="report-filters-mobile"
        />
      </Dialog>
    </section>
  );
}
