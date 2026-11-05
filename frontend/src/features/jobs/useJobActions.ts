/** Control, retry and reanalyze actions for the job detail header. */

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, UNKNOWN_ERROR_MESSAGE } from "../../api/errors";
import { controlJob, getJob, retryJob } from "../../api/jobs";
import type {
  AllowedAction,
  ControlAction,
  JobDetail,
  RetryMode,
} from "../../api/types";
import { createIdempotencyKey } from "../../lib/idempotency";
import {
  invalidateJobList,
  invalidateJobQueries,
  queryKeys,
} from "../../lib/query";

interface RetryIntent {
  mode: RetryMode;
  key: string;
}

export interface UseJobActionsResult {
  busy: AllowedAction | null;
  error: ApiError | null;
  fingerprintMismatch: boolean;
  run: (action: AllowedAction) => Promise<void>;
  dismissError: () => void;
}

function toApiError(caught: unknown): ApiError {
  return caught instanceof ApiError
    ? caught
    : new ApiError({
        code: "unknown_error",
        message: UNKNOWN_ERROR_MESSAGE,
        status: 0,
      });
}

export function useJobActions(job: JobDetail): UseJobActionsResult {
  const client = useQueryClient();
  const navigate = useNavigate();
  const jobId = job.job_id;
  const tickerCode = job.ticker_code;
  const inFlightRef = useRef(false);
  const intentRef = useRef<RetryIntent | null>(null);
  const aliveRef = useRef(true);
  const statusRef = useRef({ jobId, status: job.status });
  const [busy, setBusy] = useState<AllowedAction | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [fingerprintMismatch, setFingerprintMismatch] = useState(false);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  useEffect(() => {
    inFlightRef.current = false;
    intentRef.current = null;
    setBusy(null);
    setError(null);
    setFingerprintMismatch(false);
  }, [jobId]);

  const syncAllowedActions = useCallback(async () => {
    try {
      const fresh = await getJob(jobId);
      // status_changed carries no allowed_actions: take the button set from
      // the server, but never overwrite a newer status or streamed stages.
      client.setQueryData<JobDetail>(queryKeys.job(jobId), (current) =>
        current !== undefined && current.status === fresh.status
          ? { ...current, allowed_actions: fresh.allowed_actions }
          : current,
      );
    } catch {
      // Keep the current buttons; the next status change fetches again.
    }
  }, [client, jobId]);

  useEffect(() => {
    const previous = statusRef.current;
    statusRef.current = { jobId, status: job.status };
    if (previous.jobId !== jobId || previous.status === job.status) {
      return;
    }
    void syncAllowedActions();
  }, [job.status, jobId, syncAllowedActions]);

  const refresh = useCallback(async () => {
    await invalidateJobQueries(client, jobId);
    await client.refetchQueries({ queryKey: queryKeys.job(jobId) });
  }, [client, jobId]);

  const run = useCallback(
    (action: AllowedAction): Promise<void> => {
      if (inFlightRef.current) {
        return Promise.resolve();
      }
      if (action === "reanalyze") {
        navigate(`/workbench?launch=1&ticker=${encodeURIComponent(tickerCode)}`);
        return Promise.resolve();
      }

      inFlightRef.current = true;
      setBusy(action);
      setError(null);

      const handleFailure = async (caught: unknown) => {
        const apiError = toApiError(caught);
        if (apiError.code === "resume_fingerprint_mismatch") {
          intentRef.current = null;
          setFingerprintMismatch(true);
          setError(apiError);
          await refresh();
          return;
        }
        if (apiError.status === 409) {
          intentRef.current = null;
          await refresh();
          return;
        }
        if (
          apiError.status >= 400 &&
          apiError.status < 500 &&
          apiError.status !== 429
        ) {
          intentRef.current = null;
        }
        setError(apiError);
      };

      const runRetry = async (mode: RetryMode) => {
        if (intentRef.current?.mode !== mode) {
          intentRef.current = { mode, key: createIdempotencyKey() };
        }
        const key = intentRef.current.key;
        try {
          const result = await retryJob(jobId, mode, key);
          intentRef.current = null;
          await invalidateJobQueries(client, jobId);
          if (aliveRef.current) {
            navigate(`/jobs/${result.job.job_id}`, { replace: true });
          }
        } catch (caught) {
          await handleFailure(caught);
        }
      };

      const runControl = async (control: ControlAction) => {
        const fromStatus = statusRef.current.status;
        try {
          const result = await controlJob(jobId, control);
          // The stream owns status and stages; apply the accepted status only
          // when no newer event has moved the job on since the click.
          client.setQueryData<JobDetail>(queryKeys.job(jobId), (current) => {
            if (current === undefined || current.status !== fromStatus) {
              return current;
            }
            return {
              ...current,
              status: result.status,
              pending_action: result.accepted
                ? result.action === "resume"
                  ? null
                  : result.action
                : current.pending_action,
            };
          });
          await invalidateJobList(client);
          await syncAllowedActions();
        } catch (caught) {
          await handleFailure(caught);
        }
      };

      let task: Promise<void>;
      if (action === "retry") {
        task = runRetry("same_config");
      } else if (action === "resume_from_checkpoint") {
        task = runRetry("resume_from_checkpoint");
      } else {
        task = runControl(action);
      }

      return task.finally(() => {
        inFlightRef.current = false;
        if (aliveRef.current) {
          setBusy(null);
        }
      });
    },
    [client, jobId, navigate, refresh, tickerCode],
  );

  const dismissError = useCallback(() => setError(null), []);

  return { busy, error, fingerprintMismatch, run, dismissError };
}
