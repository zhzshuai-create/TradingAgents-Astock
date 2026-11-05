import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { isAbortError } from "../../api/errors";
import {
  SseFailureError,
  SseProtocolError,
  streamJobEvents,
  type JobEventStreamOptions,
} from "../../api/sse";
import type {
  JobDetail,
  JobSseEvent,
  JobStatus,
  StageStatus,
} from "../../api/types";
import { jobDetailQuery, queryKeys } from "../../lib/query";

const TERMINAL_STATUSES: ReadonlySet<JobStatus> = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "interrupted",
]);

const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000] as const;

export interface JobStreamState {
  reconnecting: boolean;
  expired: boolean;
}

export function jobCursorStorageKey(jobId: string): string {
  return `ta:job-cursor:${jobId}`;
}

function readCursor(jobId: string): number | null {
  try {
    const raw = sessionStorage.getItem(jobCursorStorageKey(jobId));
    if (raw === null) {
      return null;
    }
    const value = Number(raw);
    return Number.isInteger(value) && value >= 0 ? value : null;
  } catch {
    return null;
  }
}

function writeCursor(jobId: string, cursor: number): void {
  try {
    sessionStorage.setItem(jobCursorStorageKey(jobId), String(cursor));
  } catch {
    // Storage can be unavailable; the next connection starts from a snapshot.
  }
}

function removeCursor(jobId: string): void {
  try {
    sessionStorage.removeItem(jobCursorStorageKey(jobId));
  } catch {
    // Nothing to clean up when storage is unavailable.
  }
}

/**
 * Subscribe to the read-only event stream and patch the job detail cache.
 *
 * A page load still reads GET /jobs/{id}; the stream starts once that detail
 * exists. Reconnects send the cursor saved in sessionStorage, so a refresh
 * replays only what the tab has not applied yet.
 */
export function useJobStream(jobId: string, enabled: boolean): JobStreamState {
  const queryClient = useQueryClient();
  const [reconnecting, setReconnecting] = useState(false);
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    setReconnecting(false);
    setExpired(false);
    if (!enabled || jobId === "") {
      return undefined;
    }

    const key = queryKeys.job(jobId);
    let disposed = false;
    let stopped = false;
    let attempt = 0;
    let cursor = readCursor(jobId);
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const commitCursor = (seq: number): void => {
      cursor = cursor === null ? seq : Math.max(cursor, seq);
      writeCursor(jobId, cursor);
    };

    const applyEvent = (event: JobSseEvent): boolean => {
      if (event.type === "snapshot") {
        if (event.payload.job.job_id !== jobId) {
          throw new SseProtocolError("snapshot belongs to another job");
        }
        queryClient.setQueryData<JobDetail>(key, event.payload.job);
        commitCursor(event.payload.last_seq);
        return false;
      }
      if (cursor !== null && event.seq <= cursor) {
        return false;
      }
      const base = queryClient.getQueryData<JobDetail>(key);
      if (base === undefined) {
        commitCursor(event.seq);
        return false;
      }

      switch (event.type) {
        case "stage_changed": {
          const payload = event.payload;
          const status: StageStatus =
            payload.stage_status === "started" ? "active" : payload.stage_status;
          const stages = base.stages.map((stage) =>
            stage.id === payload.stage_id
              ? {
                  ...stage,
                  name: payload.stage_name,
                  index: payload.index,
                  status,
                  started_at: payload.started_at ?? stage.started_at,
                  finished_at: payload.finished_at ?? stage.finished_at,
                  duration_ms: payload.duration_ms ?? stage.duration_ms,
                }
              : stage,
          );
          const current_stage =
            status === "active"
              ? {
                  id: payload.stage_id,
                  name: payload.stage_name,
                  index: payload.index,
                  total: payload.total,
                  status,
                }
              : base.current_stage?.id === payload.stage_id
                ? null
                : base.current_stage;
          queryClient.setQueryData<JobDetail>(key, { ...base, stages, current_stage });
          break;
        }
        case "stats":
          queryClient.setQueryData<JobDetail>(key, { ...base, stats: event.payload });
          break;
        case "status_changed": {
          const payload = event.payload;
          queryClient.setQueryData<JobDetail>(key, {
            ...base,
            status: payload.to,
            pending_action: payload.pending_action,
            error: payload.error,
          });
          break;
        }
        case "report_ready":
          queryClient.setQueryData<JobDetail>(key, {
            ...base,
            report_id: event.payload.report_id,
            links: { ...base.links, report: event.payload.url },
          });
          break;
        case "error":
          if (event.payload.fatal) {
            return true;
          }
          break;
      }
      commitCursor(event.seq);
      return false;
    };

    const reconcile = async (): Promise<void> => {
      try {
        await queryClient.fetchQuery(jobDetailQuery(jobId));
      } catch {
        // Keep the last known detail; the next refresh can try again.
      }
      if (!disposed) {
        setReconnecting(false);
        setExpired(false);
      }
      removeCursor(jobId);
    };

    const scheduleRetry = (): void => {
      if (disposed || stopped) {
        return;
      }
      setReconnecting(true);
      const delay =
        RETRY_DELAYS_MS[Math.min(attempt, RETRY_DELAYS_MS.length - 1)];
      attempt += 1;
      timer = setTimeout(() => {
        timer = null;
        void connect();
      }, delay);
    };

    const connect = async (): Promise<void> => {
      if (disposed || stopped) {
        return;
      }
      const current = new AbortController();
      controller = current;
      const options: JobEventStreamOptions = {
        signal: current.signal,
        lastEventId: cursor,
        onOpen: () => {
          if (disposed || stopped) {
            return;
          }
          attempt = 0;
          setReconnecting(false);
          setExpired(false);
        },
        onEvent: (event) => {
          if (disposed || stopped) {
            return;
          }
          if (applyEvent(event)) {
            stopped = true;
            current.abort();
            void reconcile();
          }
        },
      };

      try {
        await streamJobEvents(jobId, options);
        if (disposed || stopped) {
          return;
        }
        const latest = queryClient.getQueryData<JobDetail>(key);
        if (latest !== undefined && TERMINAL_STATUSES.has(latest.status)) {
          stopped = true;
          await reconcile();
          return;
        }
        scheduleRetry();
      } catch (error) {
        if (disposed || stopped || isAbortError(error)) {
          return;
        }
        if (error instanceof SseFailureError) {
          if (error.failure.kind === "expired") {
            stopped = true;
            removeCursor(jobId);
            setReconnecting(false);
            setExpired(true);
            return;
          }
          if (error.failure.kind === "not_found") {
            stopped = true;
            setReconnecting(false);
            return;
          }
        }
        if (error instanceof SseProtocolError) {
          stopped = true;
          void reconcile();
          return;
        }
        scheduleRetry();
      }
    };

    void connect();

    return () => {
      disposed = true;
      stopped = true;
      if (timer !== null) {
        clearTimeout(timer);
      }
      controller?.abort();
    };
  }, [enabled, jobId, queryClient]);

  return { reconnecting, expired };
}
