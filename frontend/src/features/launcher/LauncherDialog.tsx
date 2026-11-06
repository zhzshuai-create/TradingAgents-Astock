import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { displayErrorMessage } from "../../api/errors";
import type { JobDetail } from "../../api/types";
import { metaOptionsQuery } from "../../lib/query";
import { Button, Dialog, Toast } from "../../ui";
import { ConfigFields } from "./ConfigFields";
import { SubmitState } from "./SubmitState";
import { fieldErrorsFor, hasFieldErrors } from "./submitErrors";
import { TickerField } from "./TickerField";
import {
  defaultStageToggles,
  toCreateJobRequest,
  type TickerSelection,
} from "./types";
import { useCreateJob, type CreateJobInfo } from "./useCreateJob";
import styles from "./LauncherDialog.module.css";

const FORM_ID = "launcher-form";
const EXISTING_NOTICE_MS = 800;

export interface LauncherDialogProps {
  open: boolean;
  initialTicker?: TickerSelection | null;
  initialDate?: string | null;
  onClose: () => void;
  onCreated: (job: JobDetail, info: CreateJobInfo) => void;
}

export function LauncherDialog({
  open,
  initialTicker = null,
  initialDate = null,
  onClose,
  onCreated,
}: LauncherDialogProps) {
  const meta = useQuery(metaOptionsQuery);
  const [ticker, setTicker] = useState<TickerSelection | null>(initialTicker);
  const [date, setDate] = useState<string | null>(null);
  const [profile, setProfile] = useState<string | null>(null);
  const [parallel, setParallel] = useState(true);
  const [toggles, setToggles] = useState<Record<string, boolean> | null>(null);
  const [existingJob, setExistingJob] = useState<JobDetail | null>(null);

  const metaData = meta.data;
  const effectiveTicker = ticker ?? initialTicker;
  const defaultDate = metaData?.default_analysis_date ?? "";
  const seededDate = initialDate === "" ? null : initialDate;
  const effectiveDate = date ?? seededDate ?? defaultDate;
  const effectiveProfile = profile ?? metaData?.llm_profiles[0]?.id ?? "";
  const effectiveToggles = toggles ?? defaultStageToggles(metaData);

  const onCreatedRef = useRef(onCreated);
  onCreatedRef.current = onCreated;

  const create = useCreateJob({
    onCreated: (job, info) => {
      if (info.existing) {
        setExistingJob(job);
        return;
      }
      onCreatedRef.current(job, info);
    },
  });

  useEffect(() => {
    if (existingJob === null) {
      return;
    }
    const timer = window.setTimeout(() => {
      onCreatedRef.current(existingJob, { existing: true });
    }, EXISTING_NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [existingJob]);

  const busy = create.submitting || create.done || existingJob !== null;
  const fieldErrors = fieldErrorsFor(create.error);
  const dateTooLate =
    effectiveDate !== "" && defaultDate !== "" && effectiveDate > defaultDate;
  const ready =
    effectiveTicker !== null &&
    effectiveDate !== "" &&
    effectiveProfile !== "" &&
    metaData !== undefined &&
    !dateTooLate;
  const canSubmit =
    ready &&
    !busy &&
    create.cooldownSeconds === 0 &&
    create.conflictJobId === null;

  function requestClose() {
    if (busy) {
      return;
    }
    create.reset();
    onClose();
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || effectiveTicker === null) {
      return;
    }
    create.submit(
      toCreateJobRequest({
        ticker: effectiveTicker,
        analysisDate: effectiveDate,
        llmProfile: effectiveProfile,
        parallelAnalysts: parallel,
        stageToggles: effectiveToggles,
      }),
    );
  }

  const submitLabel = create.done
    ? "正在打开…"
    : create.submitting
      ? "提交中"
      : "开始分析";

  return (
    <>
      <Dialog
        open={open}
        title="分析启动器"
        fullscreenOnMobile
        onClose={requestClose}
        footer={
          <div className={styles.footer}>
            <Button onClick={requestClose} disabled={busy}>
              取消
            </Button>
            <Button
              type="submit"
              form={FORM_ID}
              variant="primary"
              disabled={!canSubmit}
            >
              {submitLabel}
            </Button>
          </div>
        }
      >
        <form id={FORM_ID} className={styles.form} onSubmit={onSubmit} noValidate>
          <TickerField
            value={effectiveTicker}
            onChange={setTicker}
            error={fieldErrors.fields.ticker}
            candidates={fieldErrors.candidates}
          />

          <div className={styles.field}>
            <label className={styles.label} htmlFor="launcher-date">
              分析日期
            </label>
            <input
              id="launcher-date"
              className={styles.input}
              type="date"
              value={effectiveDate}
              max={defaultDate === "" ? undefined : defaultDate}
              onChange={(event) => setDate(event.target.value)}
              disabled={metaData === undefined}
            />
            {dateTooLate ? (
              <p className={styles.error} role="alert">
                分析日期不能晚于服务器当天（{defaultDate}）
              </p>
            ) : null}
            {fieldErrors.fields.analysis_date === undefined ? null : (
              <p className={styles.error} role="alert">
                {fieldErrors.fields.analysis_date}
              </p>
            )}
          </div>

          {metaData === undefined ? null : (
            <ConfigFields
              meta={metaData}
              profile={effectiveProfile}
              onProfileChange={setProfile}
              parallel={parallel}
              onParallelChange={setParallel}
              toggles={effectiveToggles}
              onToggleChange={(id, value) =>
                setToggles({ ...effectiveToggles, [id]: value })
              }
              profileError={fieldErrors.fields.llm_profile}
              configError={fieldErrors.fields.config}
              allowedValues={fieldErrors.allowedValues}
            />
          )}

          <div className={styles.notes}>
            <p className={styles.cost}>
              分析会调用付费模型，预计 5–15 分钟。
            </p>
            <p className={styles.note}>
              取消只关闭表单；已经提交的分析不会被撤回。
            </p>
          </div>

          <SubmitState
            error={create.error}
            conflictJobId={create.conflictJobId}
            cooldownSeconds={create.cooldownSeconds}
            hasFieldErrors={hasFieldErrors(fieldErrors)}
            onDismissConflict={create.dismissConflict}
            metaLoading={meta.isPending}
            metaError={
              meta.error === null ? null : displayErrorMessage(meta.error)
            }
            onRetryMeta={() => {
              void meta.refetch();
            }}
          />
        </form>
      </Dialog>
      <Toast
        open={existingJob !== null}
        title="已有一个相同分析"
        description="正在打开已有任务…"
        tone="info"
        onClose={() => undefined}
      />
    </>
  );
}
