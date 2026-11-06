import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import type { JobDetail } from "../../api/types";
import { LauncherDialog } from "../launcher/LauncherDialog";
import type { TickerSelection } from "../launcher/types";
import { SearchBox } from "../search/SearchBox";
import { Button } from "../../ui";
import { ActiveJobCard } from "./ActiveJobCard";
import styles from "./WorkbenchPage.module.css";
import { RecentJobs } from "./RecentJobs";

const CODE_PATTERN = /^\d{6}$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function WorkbenchPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const launchRequested = params.get("launch") === "1";
  const requestedTicker = params.get("ticker") ?? "";
  const launchTicker = CODE_PATTERN.test(requestedTicker) ? requestedTicker : "";
  const requestedDate = params.get("date") ?? "";
  const launchDate =
    launchRequested && DATE_PATTERN.test(requestedDate) ? requestedDate : null;
  const [launcherOpen, setLauncherOpen] = useState(launchRequested);
  const [pickedTicker, setPickedTicker] = useState<TickerSelection | null>(null);
  const [reportsOpen, setReportsOpen] = useState(false);

  useEffect(() => {
    if (launchRequested) {
      setLauncherOpen(true);
    }
  }, [launchRequested]);

  const initialTicker: TickerSelection | null =
    launchTicker === ""
      ? null
      : {
          code: launchTicker,
          name: pickedTicker?.code === launchTicker ? pickedTicker.name : null,
        };

  function openLauncher() {
    setLauncherOpen(true);
    setPickedTicker(null);
    if (!launchRequested) {
      setParams({ launch: "1" }, { replace: true });
    }
  }

  function launchFromSearch(selection: TickerSelection) {
    setLauncherOpen(true);
    setPickedTicker(selection);
    setParams(
      { launch: "1", ticker: selection.code },
      { replace: true },
    );
  }

  function closeLauncher() {
    setLauncherOpen(false);
    setPickedTicker(null);
    if (params.has("launch") || params.has("ticker")) {
      setParams({}, { replace: true });
    }
  }

  function created(job: JobDetail) {
    setLauncherOpen(false);
    setPickedTicker(null);
    navigate(`/jobs/${job.job_id}`, { replace: true });
  }

  return (
    <section className={styles.page} data-testid="page-workbench">
      <header className={styles.header}>
        <h1 className={styles.title}>工作台</h1>
        <p className={styles.lead}>回到未完成的研究，或开始一次新的分析。</p>
      </header>

      <ActiveJobCard />

      <section className={styles.hero} aria-labelledby="workbench-start-title">
        <h2 className={styles.heroTitle} id="workbench-start-title">
          分析一只股票
        </h2>
        <p className={styles.heroLead}>
          输入代码或名称，选中后打开分析启动器。
        </p>
        <div className={styles.startRow}>
          <SearchBox
            label="搜索要分析的股票"
            className={styles.heroSearch}
            onSelect={launchFromSearch}
          />
          <Button
            variant="primary"
            data-testid="workbench-primary"
            onClick={openLauncher}
          >
            开始分析
          </Button>
        </div>
      </section>

      <RecentJobs onStartAnalysis={openLauncher} />

      <section
        className={styles.panel}
        aria-labelledby="recent-reports-title"
        data-testid="recent-reports"
      >
        <div className={styles.panelHead}>
          <h2 className={styles.panelTitle} id="recent-reports-title">
            最近报告
          </h2>
          <button
            type="button"
            className={styles.reportsToggle}
            aria-expanded={reportsOpen}
            onClick={() => setReportsOpen((value) => !value)}
          >
            查看全部
          </button>
        </div>
        <div
          className={`${styles.panelBody} ${styles.panelBodyCollapsible} ${
            reportsOpen ? styles.panelOpen : ""
          }`}
        >
          <p className={styles.panelText}>报告库将在 P3 开放。</p>
        </div>
      </section>

      <section
        className={styles.panel}
        aria-labelledby="market-summary-title"
        data-testid="market-summary"
      >
        <div className={styles.panelHead}>
          <h2 className={styles.panelTitle} id="market-summary-title">
            市场概览
          </h2>
        </div>
        <div className={styles.panelBody}>
          <p className={styles.panelText}>
            指数、行业与强势股将在 P4 接入。
          </p>
        </div>
      </section>

      {launcherOpen ? (
        <LauncherDialog
          open
          initialTicker={initialTicker}
          initialDate={launchDate}
          onClose={closeLauncher}
          onCreated={created}
        />
      ) : null}
    </section>
  );
}
