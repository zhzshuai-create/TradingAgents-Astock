import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { displayErrorMessage } from "../../api/errors";
import { listJobs } from "../../api/jobs";
import type { JobSummary } from "../../api/types";
import { JOB_STATUS_META } from "../../lib/jobStatus";
import { queryKeys } from "../../lib/query";
import { Button, Dialog, EmptyState, Skeleton } from "../../ui";
import { JobCards } from "./JobCards";
import { JobFilters } from "./JobFilters";
import { JobTable } from "./JobTable";
import {
  JOB_STATUS_ORDER,
  listStateHasFilters,
  parseJobListSearch,
  toJobListFilters,
  toJobListSearch,
  type JobListState,
} from "./listParams";
import styles from "./JobListPage.module.css";

/** A back navigation rebuilds at most this many pages (20 rows each). */
const MAX_RESTORE_PAGES = 20;

function chipLabels(state: JobListState): string[] {
  const chips: string[] = [];
  // While the activity switch is on, status is not part of the request.
  if (!state.activeOnly && state.statuses.length < JOB_STATUS_ORDER.length) {
    chips.push(
      state.statuses.map((status) => JOB_STATUS_META[status].label).join("、"),
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
  if (state.activeOnly) {
    chips.push("只看活动任务");
  }
  return chips;
}

export function JobListPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const state = parseJobListSearch(params.toString());
  const filters = toJobListFilters(state);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const restoredScroll = useRef(false);
  // A cursor in the URL means "this many pages were loaded"; a cursor is the
  // pageParam of the last page, so the pages are rebuilt from the first one.
  const [restoreCursor, setRestoreCursor] = useState<string | null>(
    () => state.cursor,
  );

  const query = useInfiniteQuery({
    queryKey: queryKeys.jobs(filters),
    queryFn: ({ pageParam, signal }) =>
      listJobs({ ...filters, cursor: pageParam ?? undefined }, signal),
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
    const desired = toJobListSearch({
      ...state,
      cursor:
        query.data === undefined ? state.cursor : restoreCursor ?? lastPageParam,
    });
    if (desired !== params.toString()) {
      setParams(desired, { replace: true });
    }
  }, [lastPageParam, params, query.data, restoreCursor, setParams, state]);

  // A14: the list scrolls inside #main-content, which the browser's own
  // history restore does not cover. One save on leave, one restore on return.
  useEffect(() => {
    const key = `ta:jobs-scroll:${location.pathname}${location.search}`;
    const main = document.getElementById("main-content");
    let tracked = main === null ? 0 : main.scrollTop;
    const remember = () => {
      if (main !== null) {
        tracked = main.scrollTop;
      }
    };
    main?.addEventListener("scroll", remember, { passive: true });
    return () => {
      main?.removeEventListener("scroll", remember);
      if (main === null) {
        return;
      }
      // The list unmounts before this cleanup runs, which clamps scrollTop to
      // 0; keep the last position the user actually scrolled to.
      const top = main.scrollTop > 0 ? main.scrollTop : tracked;
      try {
        sessionStorage.setItem(key, String(top));
      } catch {
        // storage unavailable: leave the scroll position to the browser
      }
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
    const key = `ta:jobs-scroll:${location.pathname}${location.search}`;
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

  function applyFilters(patch: Partial<Omit<JobListState, "cursor">>) {
    const next: JobListState = { ...state, ...patch, cursor: null };
    setParams(toJobListSearch(next), { replace: true });
  }

  function resetFilters() {
    setParams("", { replace: true });
  }

  const seen = new Set<string>();
  const jobs: JobSummary[] = [];
  for (const page of query.data?.pages ?? []) {
    for (const job of page.items) {
      if (!seen.has(job.job_id)) {
        seen.add(job.job_id);
        jobs.push(job);
      }
    }
  }

  const chips = chipLabels(state);

  return (
    <section className={styles.page} data-testid="page-jobs">
      <header className={styles.header}>
        <div className={styles.headRow}>
          <div className={styles.heading}>
            <h1 className={styles.title}>任务</h1>
            <p className={styles.lead}>查看正在运行的分析与历史任务。</p>
          </div>
          <div className={styles.mobileAction} data-testid="job-filter-open">
            <Button onClick={() => setFiltersOpen(true)}>筛选</Button>
          </div>
        </div>
        {chips.length === 0 ? null : (
          <ul className={styles.chips} data-testid="job-filter-chips">
            {chips.map((chip) => (
              <li className={styles.chip} key={chip} data-testid="job-filter-chip">
                {chip}
              </li>
            ))}
          </ul>
        )}
      </header>

      <section className={styles.filtersPanel} aria-label="任务筛选">
        <JobFilters
          state={state}
          onChange={applyFilters}
          onReset={resetFilters}
        />
      </section>

      {query.isPending ? (
        <div className={styles.skeleton} data-testid="jobs-loading">
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
      ) : jobs.length === 0 ? (
        listStateHasFilters(state) ? (
          <div data-testid="jobs-filtered-empty">
            <EmptyState
              title="没有符合条件的任务"
              description="换一组筛选条件，或清空筛选查看全部任务。"
              action={<Button onClick={resetFilters}>清空筛选</Button>}
            />
          </div>
        ) : (
          <div data-testid="jobs-empty">
            <EmptyState
              title="还没有分析任务"
              description="选一只股票，开始第一次分析。"
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
            <JobTable jobs={jobs} />
          </div>
          <div className={styles.cardArea}>
            <JobCards jobs={jobs} />
          </div>
          <div className={styles.more}>
            {query.isFetchNextPageError ? (
              <div className={styles.errorPanel} role="alert">
                <span>加载更多失败，已加载的任务仍然保留。</span>
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
        title="筛选任务"
        fullscreenOnMobile
        onClose={() => setFiltersOpen(false)}
        footer={
          <Button variant="primary" onClick={() => setFiltersOpen(false)}>
            应用筛选
          </Button>
        }
      >
        <JobFilters
          state={state}
          onChange={applyFilters}
          onReset={resetFilters}
          compact
          testId="job-filters-mobile"
        />
      </Dialog>
    </section>
  );
}
