import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { SearchBox } from "../search/SearchBox";
import { Button, Dialog } from "../../ui";
import { ActiveJobCard } from "./ActiveJobCard";
import styles from "./WorkbenchPage.module.css";
import { RecentJobs } from "./RecentJobs";

const CODE_PATTERN = /^\d{6}$/;

export function WorkbenchPage() {
  const [params, setParams] = useSearchParams();
  const launchRequested = params.get("launch") === "1";
  const requestedTicker = params.get("ticker") ?? "";
  const launchTicker = CODE_PATTERN.test(requestedTicker) ? requestedTicker : "";
  const [launcherOpen, setLauncherOpen] = useState(launchRequested);
  const [reportsOpen, setReportsOpen] = useState(false);

  useEffect(() => {
    if (launchRequested) {
      setLauncherOpen(true);
    }
  }, [launchRequested]);

  function openLauncher() {
    setLauncherOpen(true);
    if (!launchRequested) {
      setParams(
        launchTicker === ""
          ? { launch: "1" }
          : { launch: "1", ticker: launchTicker },
        { replace: true },
      );
    }
  }

  function closeLauncher() {
    setLauncherOpen(false);
    if (params.has("launch") || params.has("ticker")) {
      setParams({}, { replace: true });
    }
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

      <Dialog
        open={launcherOpen}
        title="分析启动器"
        onClose={closeLauncher}
        footer={
          <Button variant="primary" onClick={closeLauncher}>
            知道了
          </Button>
        }
      >
        <p>
          {launchTicker
            ? `已选择股票 ${launchTicker}。`
            : "选择一只股票开始分析。"}
          启动器将在 P2-08 接入，当前版本不会创建任务或消耗额度。
        </p>
      </Dialog>
    </section>
  );
}
