/** Export and reanalyze controls; the parent supplies one shared hook. */

import { exportFileUrl } from "../../api/exports";
import { reportMarkdownUrl } from "../../api/reports";
import { usePreferences } from "../../lib/preferences";
import { Button } from "../../ui";
import styles from "./ReportActions.module.css";
import type { UseReportActionsResult } from "./useReportActions";

export interface ReportActionsProps {
  variant: "header" | "bar";
  actions: UseReportActionsResult;
  reportId: string;
}

function exportLabel(actions: UseReportActionsResult): string {
  if (actions.exportPosting) {
    return "请求中…";
  }
  if (actions.exportState === "queued") {
    return "排队中…";
  }
  if (actions.exportState === "rendering") {
    return "渲染中…";
  }
  if (actions.exportState === "failed") {
    return "重试导出";
  }
  return "导出 PDF";
}

export function ReportActions({
  variant,
  actions,
  reportId,
}: ReportActionsProps) {
  const { export: exportFormat } = usePreferences();

  const exportControl =
    actions.exportState === "ready" && actions.exportId !== null ? (
      <a
        className={styles.download}
        href={exportFileUrl(actions.exportId)}
        download
        data-testid="export-download"
      >
        下载 PDF
      </a>
    ) : (
      <Button
        variant="secondary"
        data-testid="export-button"
        onClick={actions.requestExport}
        disabled={actions.exportPending}
        aria-busy={actions.exportPending}
      >
        {exportLabel(actions)}
      </Button>
    );

  const markdownControl =
    reportId === "" ? null : (
      <a
        className={styles.download}
        href={reportMarkdownUrl(reportId)}
        download
        data-testid="export-markdown"
        aria-label="下载 Markdown"
      >
        下载 Markdown
      </a>
    );

  // Both formats stay reachable; the preference only decides which is first.
  const exportControls = (
    <>
      {exportFormat === "pdf" ? exportControl : markdownControl}
      {exportFormat === "pdf" ? markdownControl : exportControl}
    </>
  );

  const reanalyzeControl = (
    <Button
      variant="primary"
      data-testid="reanalyze-button"
      onClick={actions.reanalyze}
      disabled={actions.reanalyzeBusy}
    >
      {actions.reanalyzeBusy ? "处理中…" : "重新分析"}
    </Button>
  );

  if (variant === "bar") {
    return (
      <>
        <div className={styles.barRow}>
          {exportControls}
          {reanalyzeControl}
        </div>
        {actions.alert === null ? null : (
          <p className={styles.barError} role="alert">
            {actions.alert}
          </p>
        )}
      </>
    );
  }

  return (
    <div className={styles.group} data-testid="reader-actions">
      {exportControls}
      {reanalyzeControl}
      {actions.alert === null ? null : (
        <p className={styles.headerError} role="alert">
          {actions.alert}
        </p>
      )}
    </div>
  );
}
