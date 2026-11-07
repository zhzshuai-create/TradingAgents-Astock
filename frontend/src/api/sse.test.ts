import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  parseSseEvent,
  SseFailureError,
  SseFrameParser,
  SseProtocolError,
  streamJobEvents,
  type JobEventStreamOptions,
  type SseFrame,
} from "./sse";
import type { JobSseEvent } from "./types";

const ORIGIN = "http://localhost:3000";
const EVENTS_URL = `${ORIGIN}/api/v1/jobs/job-1/events`;

const SNAPSHOT = {
  seq: 3,
  job_id: "job-1",
  type: "snapshot",
  at: "2026-11-05T09:03:00+08:00",
  payload: {
    job: { job_id: "job-1", status: "running" },
    last_seq: 3,
  },
} as const;

function frame(event: string, data: unknown, id: string | null = null): SseFrame {
  return {
    id,
    event,
    data: typeof data === "string" ? data : JSON.stringify(data),
  };
}

function encoder(): TextEncoder {
  return new TextEncoder();
}

function streamResponse(
  chunks: Array<string | Uint8Array>,
  init: { status?: number; headers?: Record<string, string> } = {},
): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(
          typeof chunk === "string" ? encoder().encode(chunk) : chunk,
        );
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status: init.status ?? 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      ...init.headers,
    },
  });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function options(
  overrides: Partial<JobEventStreamOptions> = {},
): JobEventStreamOptions & { events: JobSseEvent[] } {
  const events: JobSseEvent[] = [];
  return {
    signal: new AbortController().signal,
    onEvent: (event) => events.push(event),
    events,
    ...overrides,
  };
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SseFrameParser", () => {
  it("reassembles frames split at arbitrary character boundaries", () => {
    const parser = new SseFrameParser();
    const text =
      "retry: 3000\n\n" +
      ": ping\n\n" +
      'id: 1\nevent: status_changed\ndata: {"seq":1}\n\n';
    const frames: SseFrame[] = [];
    for (const char of text) {
      frames.push(...parser.feed(char));
    }
    expect(frames).toEqual([{ id: "1", event: "status_changed", data: '{"seq":1}' }]);
  });

  it("accepts CRLF, joins multi-line data, and ignores comments", () => {
    const parser = new SseFrameParser();
    const frames = parser.feed(
      ": comment\r\n\r\n" +
        'event: stats\r\ndata: {"model_calls":1,\r\ndata: "tokens_in":2}\r\n\r\n',
    );
    expect(frames).toHaveLength(1);
    expect(frames[0].event).toBe("stats");
    expect(frames[0].data).toBe('{"model_calls":1,\n"tokens_in":2}');
  });

  it("keeps a trailing frame without a blank line for end()", () => {
    const parser = new SseFrameParser();
    expect(parser.feed('id: 4\nevent: stats\ndata: {"seq":4}')).toEqual([]);
    expect(parser.end()).toEqual([
      { id: "4", event: "stats", data: '{"seq":4}' },
    ]);
    expect(parser.end()).toEqual([]);
  });
});

describe("parseSseEvent", () => {
  it("accepts a valid snapshot envelope", () => {
    expect(parseSseEvent(frame("snapshot", SNAPSHOT, "3"))).toEqual(SNAPSHOT);
  });

  it("accepts a frame with no event line when data.type is known", () => {
    expect(parseSseEvent({ id: null, event: null, data: JSON.stringify(SNAPSHOT) }))
      .toEqual(SNAPSHOT);
  });

  it("rejects an event line that disagrees with data.type", () => {
    expect(() => parseSseEvent(frame("stats", SNAPSHOT, "3"))).toThrow(
      SseProtocolError,
    );
  });

  it("rejects non-JSON data", () => {
    expect(() => parseSseEvent(frame("stats", "not json"))).toThrow(
      SseProtocolError,
    );
  });

  it.each([
    ["unknown type", { ...SNAPSHOT, type: "created" }],
    ["missing job id", { ...SNAPSHOT, job_id: undefined }],
    ["fractional seq", { ...SNAPSHOT, seq: 1.5 }],
    ["negative seq", { ...SNAPSHOT, seq: -1 }],
    ["missing timestamp", { ...SNAPSHOT, at: undefined }],
    ["bad payload", { ...SNAPSHOT, payload: { last_seq: "3" } }],
  ])("rejects an envelope with %s", (_label, data) => {
    expect(() => parseSseEvent(frame("snapshot", data))).toThrow(
      SseProtocolError,
    );
  });

  it.each([
    ["stage_changed", { stage_id: "news", stage_status: "jumping", index: 3 }],
    ["stage_changed", { stage_id: "news", stage_status: "started" }],
    ["stats", { model_calls: 1, tokens_in: 2, tokens_out: 3 }],
    ["status_changed", { from: "running" }],
    ["report_ready", { url: "/api/v1/reports/1" }],
    ["error", { code: "internal_error", fatal: "yes" }],
  ])("rejects a malformed %s payload", (type, payload) => {
    expect(() =>
      parseSseEvent(
        frame(type, { ...SNAPSHOT, type, payload }),
      ),
    ).toThrow(SseProtocolError);
  });
});

describe("streamJobEvents", () => {
  it("requests the job event stream without a cursor on first connect", async () => {
    fetchMock.mockResolvedValue(streamResponse([]));
    const opts = options();

    await streamJobEvents("job-1", opts);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(EVENTS_URL);
    expect(init).toMatchObject({
      method: "GET",
      cache: "no-store",
      headers: { Accept: "text/event-stream" },
    });
    expect(init?.headers).not.toHaveProperty("Last-Event-ID");
    expect(opts.events).toEqual([]);
  });

  it("sends Last-Event-ID when a cursor exists", async () => {
    fetchMock.mockResolvedValue(streamResponse([]));

    await streamJobEvents("job-1", options({ lastEventId: 7 }));

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).toMatchObject({ "Last-Event-ID": "7" });
  });

  it("dispatches events in order and reports the open state first", async () => {
    const stats = {
      seq: 4,
      job_id: "job-1",
      type: "stats",
      at: "2026-11-05T09:04:00+08:00",
      payload: {
        model_calls: 2,
        tokens_in: 10,
        tokens_out: 20,
        elapsed_ms: 1000,
      },
    };
    const order: string[] = [];
    fetchMock.mockResolvedValue(
      streamResponse([
        "retry: 3000\n\n",
        `id: 3\nevent: snapshot\ndata: ${JSON.stringify(SNAPSHOT)}\n\n`,
        `id: 4\nevent: stats\ndata: ${JSON.stringify(stats)}\n\n`,
      ]),
    );

    await streamJobEvents(
      "job-1",
      options({
        onOpen: () => order.push("open"),
        onEvent: (event) => order.push(event.type),
      }),
    );

    expect(order).toEqual(["open", "snapshot", "stats"]);
  });

  it("decodes a UTF-8 code point split across chunks", async () => {
    const event = {
      seq: 5,
      job_id: "job-1",
      type: "stage_changed",
      at: "2026-11-05T09:05:00+08:00",
      payload: {
        stage_id: "news",
        stage_name: "新闻舆情",
        stage_status: "done",
        index: 3,
        total: 12,
        started_at: null,
        finished_at: null,
        duration_ms: 1000,
      },
    };
    const text =
      `id: 5\nevent: stage_changed\ndata: ${JSON.stringify(event)}\n\n`;
    const bytes = encoder().encode(text);
    const cut = bytes.indexOf(0xe8) + 1;
    fetchMock.mockResolvedValue(
      streamResponse([bytes.slice(0, cut), bytes.slice(cut)]),
    );

    const opts = options();
    await streamJobEvents("job-1", opts);

    expect(opts.events).toHaveLength(1);
    expect(opts.events[0]).toMatchObject({
      type: "stage_changed",
      payload: { stage_name: "新闻舆情" },
    });
  });

  it.each([
    [410, { error: { code: "sse_cursor_expired", message: "cursor expired" } }, "expired"],
    [404, { error: { code: "job_not_found", message: "missing" } }, "not_found"],
    [500, { error: { code: "internal_error", message: "boom" } }, "http"],
  ])("maps HTTP %s to %s", async (status, body, kind) => {
    fetchMock.mockResolvedValue(jsonResponse(status, body));

    const error = await streamJobEvents("job-1", options()).catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(SseFailureError);
    expect((error as SseFailureError).failure.kind).toBe(kind);
  });

  it("keeps the expired code on the mapped ApiError", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(410, {
        error: { code: "sse_cursor_expired", message: "cursor expired" },
      }),
    );

    const error = await streamJobEvents("job-1", options()).catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(SseFailureError);
    expect((error as SseFailureError).failure).toMatchObject({
      kind: "expired",
      error: { code: "sse_cursor_expired", status: 410 },
    });
  });

  it("rejects a 200 response that is not an event stream", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, {}));

    await expect(streamJobEvents("job-1", options())).rejects.toMatchObject({
      failure: { kind: "protocol" },
    });
  });

  it("maps a transport failure to a network failure", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(streamJobEvents("job-1", options())).rejects.toMatchObject({
      failure: { kind: "network" },
    });
  });

  it("rethrows the abort error unchanged", async () => {
    const abort = new DOMException("aborted", "AbortError");
    fetchMock.mockRejectedValue(abort);

    await expect(streamJobEvents("job-1", options())).rejects.toBe(abort);
  });

  it("maps a read failure after the handshake to a network failure", async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder().encode(": ping\n\n"));
        controller.error(new Error("socket closed"));
      },
    });
    fetchMock.mockResolvedValue(
      new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    await expect(streamJobEvents("job-1", options())).rejects.toMatchObject({
      failure: { kind: "network" },
    });
  });

  it("propagates a protocol error instead of retrying silently", async () => {
    fetchMock.mockResolvedValue(
      streamResponse(['event: stats\ndata: {"seq":1}\n\n']),
    );

    await expect(streamJobEvents("job-1", options())).rejects.toBeInstanceOf(
      SseProtocolError,
    );
  });
});

describe("last connection result (C8)", () => {
  // The record is module state; every case starts from a fresh module.
  beforeEach(() => {
    vi.resetModules();
  });

  it("starts at none, records success on the handshake and notifies once", async () => {
    const sse = await import("./sse");
    expect(sse.readLastSseResult()).toBe("none");

    const listener = vi.fn();
    const unsubscribe = sse.subscribeLastSseResult(listener);
    fetchMock.mockResolvedValue(streamResponse([]));

    await sse.streamJobEvents("job-1", {
      signal: new AbortController().signal,
      onEvent: () => {},
    });

    expect(sse.readLastSseResult()).toBe("success");
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("records failure when the handshake is rejected", async () => {
    const sse = await import("./sse");
    fetchMock.mockResolvedValue(
      jsonResponse(500, {
        error: { code: "internal_error", message: "boom" },
      }),
    );

    await expect(
      sse.streamJobEvents("job-1", {
        signal: new AbortController().signal,
        onEvent: () => {},
      }),
    ).rejects.toBeInstanceOf(sse.SseFailureError);

    expect(sse.readLastSseResult()).toBe("failure");
  });

  it("records failure for a broken frame after a successful handshake", async () => {
    const sse = await import("./sse");
    fetchMock.mockResolvedValue(
      streamResponse(['event: stats\ndata: {"seq":1}\n\n']),
    );

    await expect(
      sse.streamJobEvents("job-1", {
        signal: new AbortController().signal,
        onEvent: () => {},
      }),
    ).rejects.toBeInstanceOf(sse.SseProtocolError);

    expect(sse.readLastSseResult()).toBe("failure");
  });

  it("keeps the previous result when the caller aborts", async () => {
    const sse = await import("./sse");
    fetchMock.mockResolvedValue(streamResponse([]));
    await sse.streamJobEvents("job-1", {
      signal: new AbortController().signal,
      onEvent: () => {},
    });
    expect(sse.readLastSseResult()).toBe("success");

    const abort = new DOMException("aborted", "AbortError");
    fetchMock.mockRejectedValue(abort);

    await expect(
      sse.streamJobEvents("job-1", {
        signal: new AbortController().signal,
        onEvent: () => {},
      }),
    ).rejects.toBe(abort);

    expect(sse.readLastSseResult()).toBe("success");
  });
});
