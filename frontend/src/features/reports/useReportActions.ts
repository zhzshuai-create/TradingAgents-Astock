/** Export and reanalyze actions shared by the desktop header and mobile bar. */

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  getExportStatus,
  requestPdfExport,
} from "../../api/exports";
import {
  ApiError,
  displayErrorMessage,
  isAbortError,
} from "../../api/errors";
import { retryJob } from "../../api/jobs";
import type { ExportState, ExportStatus, ReportMeta } from "../../api/types";
import { createIdempotencyKey } from "../../lib/idempotency";

export const EXPORT_POLL_MS = 600;
export const EXPORT_FAILED_MESSAGE = "导出失败，请重试";

export type ExportUiState = ExportState | "idle";

export interface UseReportActionsResult {
  exportState: ExportUiState;
  exportId: string | null;
  /** The POST is in flight; the response has not been applied yet. */
  exportPosting: boolean;
  /** True from the click until the export is ready or failed. */
  exportPending: boolean;
  exportError: string | null;
  requestExport: () => void;
  reanalyzeBusy: boolean;
  reanalyzeError: string | null;
  reanalyze: () => void;
  alert: string | null;
}

function failureMessage(status: ExportStatus): string {
  const message = status.error?.message?.trim();
  return message ? message : EXPORT_FAILED_MESSAGE;
}

/**
 * State lives here so the desktop header and the mobile action bar stay in
 * sync. A POST happens only on requestExport, and polling stops on unmount,
 * on ready/failed, and whenever the report id changes.
 */
export function useReportActions(
  meta: ReportMeta | undefined,
): UseReportActionsResult {
  const navigate = useNavigate();
  const reportId = meta?.report_id ?? "";
  const [exportState, setExportState] = useState<ExportUiState>("idle");
  const [exportId, setExportId] = useState<string | null>(null);
  const [exportPosting, setExportPosting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [reanalyzeBusy, setReanalyzeBusy] = useState(false);
  const [reanalyzeError, setReanalyzeError] = useState<string | null>(null);

  const aliveRef = useRef(true);
  const generationRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const exportActiveRef = useRef(false);
  const reanalyzeActiveRef = useRef(false);
  const retryKeyRef = useRef<string | null>(null);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      generationRef.current += 1;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      controllerRef.current?.abort();
    };
  }, []);

  // A different report starts from a clean action state.
  useEffect(() => {
    generationRef.current += 1;
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    controllerRef.current?.abort();
    controllerRef.current = null;
    exportActiveRef.current = false;
    reanalyzeActiveRef.current = false;
    retryKeyRef.current = null;
    setExportState("idle");
    setExportId(null);
    setExportPosting(false);
    setExportError(null);
    setReanalyzeBusy(false);
    setReanalyzeError(null);
  }, [reportId]);

  async function pollOnce(id: string, generation: number): Promise<void> {
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const status = await getExportStatus(id, controller.signal);
      if (!aliveRef.current || generation !== generationRef.current) {
        return;
      }
      if (status.status === "ready") {
        exportActiveRef.current = false;
        setExportId(id);
        setExportState("ready");
        return;
      }
      if (status.status === "failed") {
        exportActiveRef.current = false;
        setExportState("failed");
        setExportError(failureMessage(status));
        return;
      }
      setExportState(status.status);
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        void pollOnce(id, generation);
      }, EXPORT_POLL_MS);
    } catch (caught) {
      if (isAbortError(caught)) {
        return;
      }
      if (!aliveRef.current || generation !== generationRef.current) {
        return;
      }
      exportActiveRef.current = false;
      setExportState("failed");
      setExportError(displayErrorMessage(caught));
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
    }
  }

  function requestExport(): void {
    if (meta === undefined || reportId === "" || exportActiveRef.current) {
      return;
    }
    if (exportState === "ready") {
      return;
    }
    exportActiveRef.current = true;
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    controllerRef.current?.abort();
    setExportPosting(true);
    setExportError(null);

    requestPdfExport(reportId)
      .then((result) => {
        if (!aliveRef.current || generation !== generationRef.current) {
          return;
        }
        setExportId(result.exportId);
        if (result.status === "ready") {
          exportActiveRef.current = false;
          setExportState("ready");
          return;
        }
        if (result.status === "failed") {
          exportActiveRef.current = false;
          setExportState("failed");
          setExportError(EXPORT_FAILED_MESSAGE);
          return;
        }
        setExportState(result.status);
        timerRef.current = window.setTimeout(() => {
          timerRef.current = null;
          void pollOnce(result.exportId, generation);
        }, EXPORT_POLL_MS);
      })
      .catch((caught) => {
        if (!aliveRef.current || generation !== generationRef.current) {
          return;
        }
        exportActiveRef.current = false;
        setExportState("failed");
        setExportError(displayErrorMessage(caught));
      })
      .finally(() => {
        if (aliveRef.current && generation === generationRef.current) {
          setExportPosting(false);
        }
      });
  }

  function reanalyze(): void {
    if (meta === undefined || reanalyzeActiveRef.current) {
      return;
    }
    if (meta.job_id === null) {
      const params = new URLSearchParams({
        launch: "1",
        ticker: meta.ticker_code,
        date: meta.analysis_date,
      });
      navigate(`/workbench?${params.toString()}`);
      return;
    }

    reanalyzeActiveRef.current = true;
    setReanalyzeBusy(true);
    setReanalyzeError(null);
    if (retryKeyRef.current === null) {
      retryKeyRef.current = createIdempotencyKey();
    }
    const key = retryKeyRef.current;
    retryJob(meta.job_id, "same_config", key)
      .then((result) => {
        retryKeyRef.current = null;
        if (aliveRef.current) {
          navigate(`/jobs/${result.job.job_id}`);
        }
      })
      .catch((caught) => {
        // Keep the key across 5xx/network failures, drop it once the server
        // has answered a 4xx (except 429, where the same intent may replay).
        if (
          caught instanceof ApiError &&
          caught.status >= 400 &&
          caught.status < 500 &&
          caught.status !== 429
        ) {
          retryKeyRef.current = null;
        }
        if (aliveRef.current) {
          setReanalyzeError(displayErrorMessage(caught));
        }
      })
      .finally(() => {
        reanalyzeActiveRef.current = false;
        if (aliveRef.current) {
          setReanalyzeBusy(false);
        }
      });
  }

  return {
    exportState,
    exportId,
    exportPosting,
    exportPending:
      exportPosting ||
      exportState === "queued" ||
      exportState === "rendering",
    exportError,
    requestExport,
    reanalyzeBusy,
    reanalyzeError,
    reanalyze,
    alert: exportError ?? reanalyzeError,
  };
}
