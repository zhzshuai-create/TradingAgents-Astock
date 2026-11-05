/** The only module that opens the read-only job event stream. */

import { openEventStream } from "./client";
import { isAbortError, toApiError, type ApiError } from "./errors";
import type { JobSseEvent, JobSseEventType } from "./types";

const EVENT_TYPES = new Set<string>([
  "snapshot",
  "stage_changed",
  "stats",
  "status_changed",
  "report_ready",
  "error",
]);

const STAGE_WIRE_STATUSES = new Set(["started", "done", "failed", "skipped"]);

const STATS_KEYS = ["model_calls", "tokens_in", "tokens_out", "elapsed_ms"] as const;

export class SseProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SseProtocolError";
  }
}

export type SseFailure =
  | { kind: "expired"; error: ApiError }
  | { kind: "not_found"; error: ApiError }
  | { kind: "http"; error: ApiError }
  | { kind: "network" }
  | { kind: "protocol" };

export class SseFailureError extends Error {
  readonly failure: SseFailure;

  constructor(failure: SseFailure) {
    super(failure.kind);
    this.name = "SseFailureError";
    this.failure = failure;
  }
}

export interface SseFrame {
  id: string | null;
  event: string | null;
  data: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isEventType(value: unknown): value is JobSseEventType {
  return typeof value === "string" && EVENT_TYPES.has(value);
}

function validPayload(type: JobSseEventType, payload: unknown): boolean {
  if (!isRecord(payload)) {
    return false;
  }
  switch (type) {
    case "snapshot":
      return isRecord(payload.job) && typeof payload.last_seq === "number";
    case "stage_changed":
      return (
        typeof payload.stage_id === "string" &&
        typeof payload.stage_status === "string" &&
        STAGE_WIRE_STATUSES.has(payload.stage_status) &&
        typeof payload.index === "number"
      );
    case "stats":
      return STATS_KEYS.every((key) => typeof payload[key] === "number");
    case "status_changed":
      return typeof payload.to === "string";
    case "report_ready":
      return typeof payload.report_id === "string";
    case "error":
      return typeof payload.code === "string" && typeof payload.fatal === "boolean";
    default:
      return false;
  }
}

/** Parse one SSE block; comments and retry-only blocks yield null. */
function parseBlock(block: string): SseFrame | null {
  let id: string | null = null;
  let event: string | null = null;
  const data: string[] = [];
  for (const line of block.split(/\r\n|\n|\r/)) {
    if (line === "" || line.startsWith(":")) {
      continue;
    }
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }
    if (field === "id") {
      id = value === "" ? null : value;
    } else if (field === "event") {
      event = value === "" ? null : value;
    } else if (field === "data") {
      data.push(value);
    }
  }
  if (data.length === 0) {
    return null;
  }
  return { id, event, data: data.join("\n") };
}

/** Incremental parser: chunks may split a frame, a line or a UTF-8 code point. */
export class SseFrameParser {
  private buffer = "";

  feed(chunk: string): SseFrame[] {
    this.buffer += chunk;
    const frames: SseFrame[] = [];
    for (;;) {
      const separator = /\r\n\r\n|\n\n|\r\r/.exec(this.buffer);
      if (separator === null) {
        break;
      }
      const block = this.buffer.slice(0, separator.index);
      this.buffer = this.buffer.slice(separator.index + separator[0].length);
      const frame = parseBlock(block);
      if (frame !== null) {
        frames.push(frame);
      }
    }
    return frames;
  }

  /** Flush a final frame that arrived without a trailing blank line. */
  end(): SseFrame[] {
    const block = this.buffer;
    this.buffer = "";
    const frame = parseBlock(block);
    return frame === null ? [] : [frame];
  }
}

export function parseSseEvent(frame: SseFrame): JobSseEvent {
  let data: unknown;
  try {
    data = JSON.parse(frame.data);
  } catch {
    throw new SseProtocolError("event data is not JSON");
  }
  if (!isRecord(data)) {
    throw new SseProtocolError("event data is not an object");
  }
  const { seq, job_id: jobId, type, payload } = data;
  if (
    typeof seq !== "number" ||
    !Number.isInteger(seq) ||
    seq < 0 ||
    typeof jobId !== "string" ||
    !isEventType(type) ||
    typeof data.at !== "string" ||
    !validPayload(type, payload)
  ) {
    throw new SseProtocolError("event envelope is invalid");
  }
  if (frame.event !== null && frame.event !== type) {
    throw new SseProtocolError("event name does not match data.type");
  }
  return data as unknown as JobSseEvent;
}

export interface JobEventStreamOptions {
  signal: AbortSignal;
  lastEventId?: number | null;
  onOpen?: () => void;
  onEvent: (event: JobSseEvent) => void;
}

async function readErrorBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

function failureForResponse(status: number, payload: unknown): SseFailure {
  const error = toApiError(status, payload);
  if (status === 410 || error.code === "sse_cursor_expired") {
    return { kind: "expired", error };
  }
  if (status === 404) {
    return { kind: "not_found", error };
  }
  return { kind: "http", error };
}

/**
 * Open one SSE connection. Resolves on EOF; throws SseFailureError for
 * handshake/transport failures and SseProtocolError for a broken frame.
 */
export async function streamJobEvents(
  jobId: string,
  options: JobEventStreamOptions,
): Promise<void> {
  let response: Response;
  try {
    response = await openEventStream(
      `/api/v1/jobs/${encodeURIComponent(jobId)}/events`,
      { signal: options.signal, lastEventId: options.lastEventId },
    );
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new SseFailureError({ kind: "network" });
  }

  if (!response.ok) {
    throw new SseFailureError(
      failureForResponse(response.status, await readErrorBody(response)),
    );
  }

  const contentType = response.headers.get("Content-Type") ?? "";
  if (!contentType.toLowerCase().includes("text/event-stream") || response.body === null) {
    throw new SseFailureError({ kind: "protocol" });
  }

  options.onOpen?.();

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  const parser = new SseFrameParser();
  const dispatch = (frames: SseFrame[]): void => {
    for (const frame of frames) {
      options.onEvent(parseSseEvent(frame));
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      dispatch(parser.feed(decoder.decode(value, { stream: true })));
    }
    dispatch(parser.feed(decoder.decode()));
    dispatch(parser.end());
  } catch (error) {
    if (isAbortError(error) || error instanceof SseProtocolError) {
      throw error;
    }
    throw new SseFailureError({ kind: "network" });
  } finally {
    reader.releaseLock();
  }
}
