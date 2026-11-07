import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { ApiError, displayErrorMessage } from "../../api/errors";
import type { ReportSection } from "../../api/types";
import { reportDetailQuery } from "../../lib/query";
import { Badge, Button, Drawer, EmptyState, Skeleton } from "../../ui";
import { DecisionCard } from "./DecisionCard";
import { REPORT_RATING_META } from "./format";
import { ReportActions } from "./ReportActions";
import { ReportMarkdown } from "./ReportMarkdown";
import { ReportMeta } from "./ReportMeta";
import { ReportToc } from "./ReportToc";
import { useReportActions } from "./useReportActions";
import {
  orderedPartKeys,
  orderedSections,
  partLabel,
} from "./sections";
import styles from "./ReportReaderPage.module.css";

const MOBILE_QUERY = "(max-width: 767px)";

/** Matches the shell breakpoint; mobile swaps the TOC column for a drawer. */
function useMobileViewport(): boolean {
  const read = () =>
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(MOBILE_QUERY).matches;
  const [mobile, setMobile] = useState(read);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined;
    }
    const query = window.matchMedia(MOBILE_QUERY);
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return mobile;
}

export function ReportReaderPage() {
  const { reportId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const query = useQuery(reportDetailQuery(reportId));
  const detail = query.data;
  const sections = useMemo(
    () => orderedSections(detail?.sections ?? {}),
    [detail],
  );
  const [activeId, setActiveId] = useState<string | null>(null);
  const [tocOpen, setTocOpen] = useState(false);
  const hashHandled = useRef(false);
  const mobile = useMobileViewport();

  const jumpTo = useCallback(
    (sectionId: string) => {
      const target = document.getElementById(sectionId);
      if (target === null) {
        return;
      }
      target.scrollIntoView({ block: "start" });
      setActiveId(sectionId);
      navigate(
        { hash: `#${sectionId}` },
        { replace: true, preventScrollReset: true },
      );
    },
    [navigate],
  );

  // Jumping from the mobile drawer closes it before the scroll, so the hash
  // and highlight land on the visible page (M04). The drawer locks
  // #main-content with overflow:hidden, so the scroll waits one commit.
  const pendingJump = useRef<string | null>(null);
  const jumpFromToc = useCallback((sectionId: string) => {
    pendingJump.current = sectionId;
    setTocOpen(false);
  }, []);

  useEffect(() => {
    if (tocOpen || pendingJump.current === null) {
      return;
    }
    const sectionId = pendingJump.current;
    pendingJump.current = null;
    jumpTo(sectionId);
  }, [jumpTo, tocOpen]);

  // A deep link (#sec-debate) scrolls after the body exists; a missing or
  // empty section leaves the reader at the top without an error (D5).
  useEffect(() => {
    if (hashHandled.current || detail === undefined || sections.length === 0) {
      return;
    }
    hashHandled.current = true;
    const sectionId = location.hash.replace(/^#/, "");
    if (sectionId === "") {
      setActiveId(sections[0].id);
      return;
    }
    if (!sections.some((section) => section.id === sectionId)) {
      setActiveId(sections[0].id);
      return;
    }
    const frame = requestAnimationFrame(() => {
      document.getElementById(sectionId)?.scrollIntoView({ block: "start" });
      setActiveId(sectionId);
    });
    return () => cancelAnimationFrame(frame);
  }, [detail, location.hash, sections]);

  useEffect(() => {
    if (sections.length === 0) {
      return;
    }
    const root = document.getElementById("main-content");
    if (root === null || typeof IntersectionObserver === "undefined") {
      return;
    }
    const visible = new Set<string>();
    // A thin band under the container top is the reading line. Neighbouring
    // sections overlap it whenever one is scrolled to the top, so the later
    // chapter wins; at the very bottom the last chapter is forced active.
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = entry.target.id;
          if (entry.isIntersecting) {
            visible.add(id);
          } else {
            visible.delete(id);
          }
        }
        const maxScroll = root.scrollHeight - root.clientHeight;
        if (maxScroll > 4 && root.scrollTop >= maxScroll - 4) {
          setActiveId(sections[sections.length - 1].id);
          return;
        }
        const current = [...sections]
          .reverse()
          .find((section) => visible.has(section.id));
        if (current !== undefined) {
          setActiveId(current.id);
        }
      },
      { root, rootMargin: "0px 0px -92% 0px", threshold: 0 },
    );
    for (const section of sections) {
      const element = document.getElementById(section.id);
      if (element !== null) {
        observer.observe(element);
      }
    }
    return () => observer.disconnect();
  }, [sections]);

  function goBack() {
    const historyState = window.history.state as { idx?: number } | null;
    if (typeof historyState?.idx === "number" && historyState.idx > 0) {
      navigate(-1);
    } else {
      navigate("/reports");
    }
  }

  const meta = detail?.meta;
  const actions = useReportActions(meta);

  return (
    <section className={styles.page} data-testid="page-report-detail">
      {query.isPending ? (
        <div className={styles.loading} data-testid="reader-loading">
          <Skeleton height="40px" width="45%" />
          <Skeleton height="24px" width="30%" />
          <Skeleton height="320px" />
        </div>
      ) : query.isError && detail === undefined ? (
        query.error instanceof ApiError && query.error.code === "report_not_found" ? (
          <div data-testid="reader-not-found">
            <EmptyState
              title="没有找到这份报告"
              description="报告可能已被移除，或链接里的编号不正确。"
              action={
                <Link className={styles.textLink} to="/reports">
                  返回报告库
                </Link>
              }
            />
          </div>
        ) : (
          <div className={styles.errorPanel} role="alert">
            <span>{displayErrorMessage(query.error)}</span>
            <Button size="sm" onClick={() => void query.refetch()}>
              重试
            </Button>
          </div>
        )
      ) : meta === undefined ? null : (
        <>
          <header className={styles.header} data-testid="reader-header">
            <Button variant="ghost" size="sm" onClick={goBack}>
              返回
            </Button>
            {mobile && sections.length > 0 ? (
              <Button
                variant="secondary"
                size="sm"
                data-testid="reader-toc-trigger"
                aria-haspopup="dialog"
                aria-expanded={tocOpen}
                onClick={() => setTocOpen(true)}
              >
                目录
              </Button>
            ) : null}
            <div className={styles.identity}>
              <h1 className={styles.title}>
                <Link
                  className={styles.titleLink}
                  to={`/stocks/${meta.ticker_code}`}
                  data-testid="reader-stock-link"
                >
                  {meta.ticker_name ?? meta.ticker_code}
                </Link>
              </h1>
              {meta.ticker_name === null ? null : (
                <span className={styles.code}>{meta.ticker_code}</span>
              )}
            </div>
            <Badge tone={REPORT_RATING_META[meta.rating].tone}>
              {REPORT_RATING_META[meta.rating].label}
            </Badge>
            <span className={styles.date}>{meta.analysis_date}</span>
            {meta.origin === "legacy_import" ? (
              <Badge tone="neutral">历史导入</Badge>
            ) : null}
            {mobile ? null : (
              <div className={styles.headerActions}>
                <ReportActions variant="header" actions={actions} />
              </div>
            )}
          </header>

          {mobile ? (
            <DecisionCard key={meta.report_id} meta={meta} collapsible />
          ) : null}

          <div className={styles.layout}>
            {mobile ? null : (
              <aside className={styles.tocColumn}>
                <ReportToc
                  sections={sections}
                  activeId={activeId}
                  onJump={jumpTo}
                />
              </aside>
            )}

            <article className={styles.article} data-testid="report-article">
              {sections.map((section) => (
                <ReportSectionView
                  key={section.id}
                  section={section}
                  allSections={detail?.sections ?? {}}
                  mobile={mobile}
                />
              ))}
            </article>

            {mobile ? (
              <ReportMeta meta={meta} />
            ) : (
              <aside className={styles.side}>
                <DecisionCard meta={meta} />
                <ReportMeta meta={meta} />
              </aside>
            )}
          </div>

          {mobile ? (
            <>
              <div className={styles.actionBar} data-testid="reader-action-bar">
                <ReportActions variant="bar" actions={actions} />
              </div>
              <Drawer
                open={tocOpen}
                title="目录"
                side="bottom"
                onClose={() => setTocOpen(false)}
              >
                <ReportToc
                  sections={sections}
                  activeId={activeId}
                  onJump={jumpFromToc}
                  showHeading={false}
                />
              </Drawer>
            </>
          ) : null}
        </>
      )}
    </section>
  );
}

function ReportSectionView({
  section,
  allSections,
  mobile,
}: {
  section: ReportSection;
  allSections: Record<string, ReportSection>;
  mobile: boolean;
}) {
  const parts = section.parts ?? {};
  const partKeys = orderedPartKeys(section.id, parts);
  const refs = section.parts_ref ?? {};
  const refKeys = Object.keys(refs).sort();
  return (
    <section
      className={styles.section}
      id={section.id}
      data-testid="report-section"
      data-section-id={section.id}
    >
      <h2 className={styles.sectionTitle}>{section.title}</h2>
      {section.body.trim() === "" ? null : (
        <ReportMarkdown mobile={mobile}>{section.body}</ReportMarkdown>
      )}
      {partKeys.map((key) => (
        <section className={styles.part} key={key}>
          <h3 className={styles.partTitle}>{partLabel(section.id, key)}</h3>
          <ReportMarkdown mobile={mobile}>{parts[key]}</ReportMarkdown>
        </section>
      ))}
      {refKeys.map((key) => {
        const target = refs[key];
        const targetTitle = allSections[target]?.title ?? target;
        return (
          <section className={styles.part} key={key}>
            <h3 className={styles.partTitle}>{partLabel(section.id, key)}</h3>
            <p className={styles.ref}>见「{targetTitle}」（内容相同）。</p>
          </section>
        );
      })}
    </section>
  );
}
