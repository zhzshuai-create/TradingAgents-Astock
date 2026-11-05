import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/errors";
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
  StageId,
} from "../../api/types";
import { getJob } from "../../api/jobs";
import { queryKeys } from "../../lib/query";
import { jobCursorStorageKey, useJobStream } from "./useJobStream";

vi.mock("../../api/jobs", () => ({
  listJobs: vi.fn(),
  getJob: vi.fn(),
  getStageReport: vi.fn(),
  createJob: vi.fn(),
  controlJob: vi.fn(),
  retryJob: vi.fn(),
}));

vi.mock("../../api/sse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/sse")>();
  return { ...actual, streamJobEvents: vi.fn() };
});

const streamMock = vi.mocked(streamJobEvents);
const getJobMock = vi.mocked(getJob);

const STAGE_IDS: StageId[] = [
  "market",
  "social",
  "news",
  "fundamentals",
  "policy",
  "hot_money",
  "lockup",
  "quality_gate",
  "debate",
  "trader",
  "risk",
  "pm",
];

function makeJob(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    job_id: "job-1",
    status: "running",
    pending_action: null,
    ticker_code: "000629",
    ticker_name: "钒钛股份",
    analysis_date: "2026-11-05",
    created_at: "2026-11-05T09:03:00+08:00",
    updated_at: "2026-11-05T09:04:00+08:00",
    started_at: "2026-11-05T09:03:01+08:00",
    finished_at: null,
    current_stage: null,
    stages: STAGE_IDS.map((id, index) => ({
      id,
      name: `阶段 ${index + 1}`,
      index: index + 1,
      status: "pending",
      started_at: null,
      finished_at: null,
      duration_ms: null,
    })),
    stats: { model_calls: 0, tokens_in: 0, tokens_out: 0, elapsed_ms: 0 },
    report_id: null,
    error: null,
    config_digest: "hash",
    graph_version: "graph-v1",
    retry_of_job_id: null,
    resume_of_job_id: null,
    resume_from_stage: null,
    allowed_actions: ["pause", "cancel"],
    links: {
      self: "/api/v1/jobs/job-1",
      events: "/api/v1/jobs/job-1/events",
      report: null,
    },
    reconcile_notes: [],
    ...overrides,
  };
}

function makeEvent(
  type: JobSseEvent["type"],
  seq: number,
  payload: unknown,
): JobSseEvent {
  return {
    seq,
    job_id: "job-1",
    type,
    at: "2026-11-05T09:04:00+08:00",
    payload,
  } as JobSseEvent;
}

interface StreamControl {
  options: JobEventStreamOptions;
  emit: (event: JobSseEvent) => void;
  finish: () => void;
  fail: (error: unknown) => void;
}

function captureStream(): StreamControl {
  let resolve!: () => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  let options: JobEventStreamOptions | null = null;
  streamMock.mockImplementationOnce((_jobId, next) => {
    options = next;
    return promise;
  });
  const control: StreamControl = {
    get options() {
      if (options === null) {
        throw new Error("stream was not started");
      }
      return options;
    },
    emit: (event) => {
      try {
        act(() => control.options.onEvent(event));
      } catch (error) {
        control.fail(error);
      }
    },
    finish: () => {
      act(() => resolve());
    },
    fail: (error) => {
      act(() => reject(error));
    },
  };
  return control;
}

function Harness({
  jobId = "job-1",
  enabled = true,
}: {
  jobId?: string;
  enabled?: boolean;
}) {
  const { reconnecting, expired } = useJobStream(jobId, enabled);
  return (
    <output
      data-testid="stream-state"
      data-reconnecting={reconnecting}
      data-expired={expired}
    />
  );
}

function mountHarness(initial = makeJob(), jobId = "job-1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  client.setQueryData(queryKeys.job(jobId), initial);
  const view = render(
    <QueryClientProvider client={client}>
      <Harness jobId={jobId} />
    </QueryClientProvider>,
  );
  return { client, unmount: view.unmount };
}

function renderHarness(initial = makeJob(), jobId = "job-1") {
  return mountHarness(initial, jobId).client;
}

function cached(client: QueryClient): JobDetail {
  const value = client.getQueryData<JobDetail>(queryKeys.job("job-1"));
  if (value === undefined) {
    throw new Error("job cache was cleared");
  }
  return value;
}

beforeEach(() => {
  streamMock.mockReset();
  getJobMock.mockReset();
  getJobMock.mockResolvedValue(makeJob());
  sessionStorage.clear();
  streamMock.mockImplementation(() => new Promise<void>(() => {}));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useJobStream snapshots and patches", () => {
  it("hydrates the detail cache from the snapshot and saves the cursor", () => {
    const control = captureStream();
    const client = renderHarness();

    expect(streamMock).toHaveBeenCalledTimes(1);
    expect(streamMock.mock.calls[0][0]).toBe("job-1");
    expect(streamMock.mock.calls[0][1].lastEventId).toBeNull();

    const snapshotJob = makeJob({ ticker_name: "快照名称" });
    control.emit(
      makeEvent("snapshot", 3, { job: snapshotJob, last_seq: 3 }),
    );

    expect(cached(client).ticker_name).toBe("快照名称");
    expect(sessionStorage.getItem(jobCursorStorageKey("job-1"))).toBe("3");
  });

  it("patches a stage when it starts and clears current_stage when it ends", () => {
    const control = captureStream();
    const client = renderHarness();

    control.emit(
      makeEvent("stage_changed", 1, {
        stage_id: "news",
        stage_name: "新闻舆情",
        stage_status: "started",
        index: 3,
        total: 12,
        started_at: "2026-11-05T09:05:00+08:00",
        finished_at: null,
        duration_ms: null,
      }),
    );

    let job = cached(client);
    expect(job.stages[2].status).toBe("active");
    expect(job.stages[2].name).toBe("新闻舆情");
    expect(job.current_stage).toMatchObject({
      id: "news",
      name: "新闻舆情",
      status: "active",
      index: 3,
      total: 12,
    });

    control.emit(
      makeEvent("stage_changed", 2, {
        stage_id: "news",
        stage_name: "新闻舆情",
        stage_status: "done",
        index: 3,
        total: 12,
        started_at: "2026-11-05T09:05:00+08:00",
        finished_at: "2026-11-05T09:06:00+08:00",
        duration_ms: 60_000,
      }),
    );

    job = cached(client);
    expect(job.stages[2].status).toBe("done");
    expect(job.stages[2].duration_ms).toBe(60_000);
    expect(job.current_stage).toBeNull();
  });

  it("patches stats, status and the report link", () => {
    const control = captureStream();
    const client = renderHarness();

    control.emit(
      makeEvent("stats", 1, {
        model_calls: 14,
        tokens_in: 182_430,
        tokens_out: 41_208,
        elapsed_ms: 612_000,
      }),
    );
    expect(cached(client).stats).toEqual({
      model_calls: 14,
      tokens_in: 182_430,
      tokens_out: 41_208,
      elapsed_ms: 612_000,
    });

    control.emit(
      makeEvent("status_changed", 2, {
        from: "running",
        to: "succeeded",
        reason: "worker",
        detail: null,
        pending_action: null,
        error: null,
      }),
    );
    expect(cached(client).status).toBe("succeeded");
    expect(cached(client).pending_action).toBeNull();

    control.emit(
      makeEvent("report_ready", 3, {
        report_id: "report-1",
        content_hash: "abc",
        rating: "Overweight",
        signal: "Buy",
        url: "/api/v1/reports/report-1",
      }),
    );
    expect(cached(client).report_id).toBe("report-1");
    expect(cached(client).links.report).toBe("/api/v1/reports/report-1");
  });

  it("ignores replayed frames at or below the snapshot cursor", () => {
    const control = captureStream();
    const client = renderHarness();
    const snapshotStats = {
      model_calls: 2,
      tokens_in: 10,
      tokens_out: 20,
      elapsed_ms: 1000,
    };

    control.emit(
      makeEvent("snapshot", 5, {
        job: makeJob({ stats: snapshotStats }),
        last_seq: 5,
      }),
    );
    control.emit(
      makeEvent("stats", 5, {
        model_calls: 99,
        tokens_in: 99,
        tokens_out: 99,
        elapsed_ms: 99,
      }),
    );
    expect(cached(client).stats).toEqual(snapshotStats);

    control.emit(
      makeEvent("stats", 6, {
        model_calls: 3,
        tokens_in: 30,
        tokens_out: 40,
        elapsed_ms: 2000,
      }),
    );
    expect(cached(client).stats.model_calls).toBe(3);
    expect(sessionStorage.getItem(jobCursorStorageKey("job-1"))).toBe("6");
  });

  it("continues after a non-fatal error event", () => {
    const control = captureStream();
    const client = renderHarness();

    control.emit(
      makeEvent("error", 1, {
        code: "internal_error",
        message: "暂时不可用",
        request_id: "req-1",
        fatal: false,
      }),
    );
    control.emit(
      makeEvent("stats", 2, {
        model_calls: 7,
        tokens_in: 70,
        tokens_out: 80,
        elapsed_ms: 3000,
      }),
    );

    expect(cached(client).stats.model_calls).toBe(7);
    expect(getJobMock).not.toHaveBeenCalled();
  });

  it("sends the saved cursor when the page is reopened", () => {
    sessionStorage.setItem(jobCursorStorageKey("job-1"), "9");
    captureStream();
    renderHarness();

    expect(streamMock.mock.calls[0][1].lastEventId).toBe(9);
  });

  it("reconciles once and stops when a fatal error event arrives", async () => {
    const control = captureStream();
    const terminal = makeJob({ status: "failed" });
    getJobMock.mockResolvedValue(terminal);
    const client = renderHarness();

    control.emit(
      makeEvent("error", 1, {
        code: "internal_error",
        message: "事件流暂时不可用",
        request_id: "req-1",
        fatal: true,
      }),
    );

    await vi.waitFor(() => expect(cached(client).status).toBe("failed"));
    expect(getJobMock).toHaveBeenCalledTimes(1);
    expect(control.options.signal.aborted).toBe(true);
  });

  it("reconciles instead of patching when a snapshot belongs to another job", async () => {
    const control = captureStream();
    const client = renderHarness();

    control.emit(
      makeEvent("snapshot", 1, {
        job: makeJob({ job_id: "job-2" }),
        last_seq: 1,
      }),
    );

    await vi.waitFor(() => expect(getJobMock).toHaveBeenCalledTimes(1));
    expect(cached(client).job_id).toBe("job-1");
  });
});

describe("useJobStream reconnect", () => {
  it("backs off 1s, 2s, 4s, 8s and then stays at 8s", async () => {
    vi.useFakeTimers();
    streamMock.mockImplementation(() =>
      Promise.reject(new SseFailureError({ kind: "network" })),
    );
    renderHarness();
    await act(async () => {});

    expect(screen.getByTestId("stream-state")).toHaveAttribute(
      "data-reconnecting",
      "true",
    );
    expect(streamMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(999);
    });
    expect(streamMock).toHaveBeenCalledTimes(1);

    const waits = [1, 2000, 4000, 8000, 8000];
    for (const wait of waits) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(wait === 1 ? 1 : wait);
      });
    }
    expect(streamMock).toHaveBeenCalledTimes(6);
  });

  it("resets the backoff after a successful handshake", async () => {
    vi.useFakeTimers();
    let call = 0;
    const opens: Array<() => void> = [];
    const rejects: Array<(error: unknown) => void> = [];
    streamMock.mockImplementation((_jobId, options) => {
      call += 1;
      return new Promise<void>((_resolve, reject) => {
        if (call <= 2) {
          reject(new SseFailureError({ kind: "network" }));
          return;
        }
        opens.push(() => options.onOpen?.());
        rejects.push(reject);
      });
    });
    renderHarness();
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(streamMock).toHaveBeenCalledTimes(2);
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(streamMock).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(streamMock).toHaveBeenCalledTimes(3);

    act(() => opens[0]());
    expect(screen.getByTestId("stream-state")).toHaveAttribute(
      "data-reconnecting",
      "false",
    );

    act(() => rejects[0](new SseFailureError({ kind: "network" })));
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(999);
    });
    expect(streamMock).toHaveBeenCalledTimes(3);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(streamMock).toHaveBeenCalledTimes(4);
  });

  it("opens exactly one live connection under StrictMode", () => {
    captureStream();
    captureStream();
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
    client.setQueryData(queryKeys.job("job-1"), makeJob());
    render(
      <StrictMode>
        <QueryClientProvider client={client}>
          <Harness />
        </QueryClientProvider>
      </StrictMode>,
    );

    expect(streamMock).toHaveBeenCalledTimes(2);
    expect(streamMock.mock.calls[0][1].signal.aborted).toBe(true);
    expect(streamMock.mock.calls[1][1].signal.aborted).toBe(false);
  });

  it("aborts the connection and clears the retry timer on unmount", async () => {
    vi.useFakeTimers();
    streamMock.mockImplementation(() =>
      Promise.reject(new SseFailureError({ kind: "network" })),
    );
    const { unmount } = mountHarness();
    await act(async () => {});
    expect(streamMock).toHaveBeenCalledTimes(1);

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    expect(streamMock).toHaveBeenCalledTimes(1);
    expect(streamMock.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it("clears the banner after a successful handshake", async () => {
    const control = captureStream();
    renderHarness();

    act(() => control.options.onOpen?.());
    expect(screen.getByTestId("stream-state")).toHaveAttribute(
      "data-reconnecting",
      "false",
    );
  });

  it("stops on 410 and keeps the expired banner until a refresh", async () => {
    sessionStorage.setItem(jobCursorStorageKey("job-1"), "5");
    const control = captureStream();
    renderHarness();

    control.fail(
      new SseFailureError({
        kind: "expired",
        error: new ApiError({
          code: "sse_cursor_expired",
          message: "事件流已过期，请刷新任务页",
          status: 410,
        }),
      }),
    );

    await vi.waitFor(() =>
      expect(screen.getByTestId("stream-state")).toHaveAttribute(
        "data-expired",
        "true",
      ),
    );
    expect(screen.getByTestId("stream-state")).toHaveAttribute(
      "data-reconnecting",
      "false",
    );
    expect(sessionStorage.getItem(jobCursorStorageKey("job-1"))).toBeNull();
    expect(streamMock).toHaveBeenCalledTimes(1);
  });

  it("silently stops when the job no longer exists", async () => {
    const control = captureStream();
    renderHarness();

    control.fail(
      new SseFailureError({
        kind: "not_found",
        error: new ApiError({
          code: "job_not_found",
          message: "没有找到这个任务",
          status: 404,
        }),
      }),
    );

    await act(async () => {});
    expect(screen.getByTestId("stream-state")).toHaveAttribute(
      "data-reconnecting",
      "false",
    );
    expect(screen.getByTestId("stream-state")).toHaveAttribute(
      "data-expired",
      "false",
    );
  });

  it("reconciles and stops after a protocol error", async () => {
    const control = captureStream();
    renderHarness();

    control.fail(new SseProtocolError("bad frame"));

    await vi.waitFor(() => expect(getJobMock).toHaveBeenCalledTimes(1));
  });
});

describe("useJobStream terminal handling", () => {
  it.each<JobStatus>(["succeeded", "failed", "cancelled", "interrupted"])(
    "reconciles once at EOF when the cached status is %s",
    async (status) => {
      const control = captureStream();
      getJobMock.mockResolvedValue(makeJob({ status }));
      const client = renderHarness();

      control.emit(
        makeEvent("status_changed", 1, {
          from: "running",
          to: status,
          reason: "worker",
          detail: null,
          pending_action: null,
          error: null,
        }),
      );
      control.finish();

      await vi.waitFor(() => expect(getJobMock).toHaveBeenCalledTimes(1));
      expect(cached(client).status).toBe(status);
      expect(sessionStorage.getItem(jobCursorStorageKey("job-1"))).toBeNull();
    },
  );

  it("does not start a stream while the detail is not loaded", () => {
    render(
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { queries: { retry: false, gcTime: Infinity } },
          })
        }
      >
        <Harness enabled={false} />
      </QueryClientProvider>,
    );

    expect(streamMock).not.toHaveBeenCalled();
  });

  it("removes the cursor when the terminal reconcile finishes", async () => {
    const control = captureStream();
    renderHarness();
    sessionStorage.setItem(jobCursorStorageKey("job-1"), "4");

    control.emit(
      makeEvent("snapshot", 4, {
        job: makeJob({ status: "succeeded", report_id: "report-1" }),
        last_seq: 4,
      }),
    );
    control.finish();

    await vi.waitFor(() => expect(getJobMock).toHaveBeenCalledTimes(1));
    expect(sessionStorage.getItem(jobCursorStorageKey("job-1"))).toBeNull();
  });
});
