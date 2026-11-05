/** Submit intent, idempotent key and the create branches for W02. */

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, UNKNOWN_ERROR_MESSAGE } from "../../api/errors";
import { createJob } from "../../api/jobs";
import type { CreateJobRequest, JobDetail } from "../../api/types";
import { IdempotencyIntent } from "../../lib/idempotency";
import { invalidateJobQueries } from "../../lib/query";

export interface CreateJobInfo {
  /** 200 + X-Existing-Job: the same intent already had a job. */
  existing: boolean;
}

export interface UseCreateJobOptions {
  onCreated: (job: JobDetail, info: CreateJobInfo) => void;
}

export interface CreateJobState {
  submitting: boolean;
  done: boolean;
  error: ApiError | null;
  conflictJobId: string | null;
  cooldownSeconds: number;
  submit: (payload: CreateJobRequest) => void;
  dismissConflict: () => void;
  reset: () => void;
}

const DEFAULT_COOLDOWN_SECONDS = 5;

export function useCreateJob({
  onCreated,
}: UseCreateJobOptions): CreateJobState {
  const client = useQueryClient();
  const intentRef = useRef<IdempotencyIntent | null>(null);
  if (intentRef.current === null) {
    intentRef.current = new IdempotencyIntent();
  }
  const inFlightRef = useRef(false);
  const aliveRef = useRef(true);
  const onCreatedRef = useRef(onCreated);
  onCreatedRef.current = onCreated;

  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [conflictJobId, setConflictJobId] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (cooldown <= 0) {
      return;
    }
    const timer = window.setTimeout(
      () => setCooldown((value) => Math.max(0, value - 1)),
      1000,
    );
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  useEffect(() => {
    if (cooldown === 0 && error !== null && error.status === 429) {
      setError(null);
    }
  }, [cooldown, error]);

  const submit = useCallback(
    (payload: CreateJobRequest) => {
      if (inFlightRef.current || cooldown > 0) {
        return;
      }
      inFlightRef.current = true;
      setSubmitting(true);
      setError(null);
      setConflictJobId(null);

      const key = intentRef.current?.keyFor(payload) ?? "";
      createJob(payload, key)
        .then(async (result) => {
          await invalidateJobQueries(client, result.job.job_id);
          intentRef.current?.reset();
          if (!aliveRef.current) {
            return;
          }
          setSubmitting(false);
          setDone(true);
          onCreatedRef.current(result.job, {
            existing: result.status === 200 && result.existingJobId !== null,
          });
        })
        .catch((caught: unknown) => {
          if (!aliveRef.current) {
            return;
          }
          const apiError =
            caught instanceof ApiError
              ? caught
              : new ApiError({
                  code: "unknown_error",
                  message: UNKNOWN_ERROR_MESSAGE,
                  status: 0,
                });
          setSubmitting(false);
          setError(apiError);
          if (apiError.code === "idempotency_mismatch") {
            intentRef.current?.reset();
            return;
          }
          if (apiError.code === "active_conflict") {
            const active = apiError.details.active_job_id;
            setConflictJobId(typeof active === "string" ? active : null);
            return;
          }
          if (apiError.status === 429) {
            const seconds = apiError.retryAfterSeconds ?? DEFAULT_COOLDOWN_SECONDS;
            setCooldown(Math.max(1, seconds));
          }
        })
        .finally(() => {
          inFlightRef.current = false;
        });
    },
    [client, cooldown],
  );

  const dismissConflict = useCallback(() => {
    setConflictJobId(null);
    setError(null);
  }, []);

  const reset = useCallback(() => {
    intentRef.current?.reset();
    inFlightRef.current = false;
    setSubmitting(false);
    setDone(false);
    setError(null);
    setConflictJobId(null);
    setCooldown(0);
  }, []);

  return {
    submitting,
    done,
    error,
    conflictJobId,
    cooldownSeconds: cooldown,
    submit,
    dismissConflict,
    reset,
  };
}
