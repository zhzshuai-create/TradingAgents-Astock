/** The only module that calls fetch; every URL and header is built here. */

import {
  invalidResponseError,
  isAbortError,
  networkError,
  toApiError,
} from "./errors";

export interface ApiRequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export interface ApiEnvelope<T> {
  data: T;
  status: number;
  headers: Headers;
}

export function resolveUrl(path: string): string {
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(path)) {
    return path;
  }
  const configured = (import.meta.env.VITE_API_BASE ?? "")
    .trim()
    .replace(/\/+$/, "");
  if (configured) {
    return `${configured}${path}`;
  }
  const origin = typeof location === "undefined" ? "" : location.origin;
  return origin ? `${origin}${path}` : path;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

/**
 * Open a streaming GET without reading the body. Kept here because fetch may
 * only be called from this module; the SSE parser owns the response body.
 */
export function openEventStream(
  path: string,
  options: { signal?: AbortSignal; lastEventId?: number | null } = {},
): Promise<Response> {
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (options.lastEventId !== undefined && options.lastEventId !== null) {
    headers["Last-Event-ID"] = String(options.lastEventId);
  }
  return fetch(resolveUrl(path), {
    method: "GET",
    headers,
    signal: options.signal,
    cache: "no-store",
  });
}

export async function apiRequestEnvelope<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<ApiEnvelope<T>> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = {
    method: options.method ?? "GET",
    headers,
    signal: options.signal,
  };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  if (options.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }

  let response: Response;
  try {
    response = await fetch(resolveUrl(path), init);
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw networkError();
  }

  const payload = await readJson(response);
  if (!response.ok) {
    throw toApiError(response.status, payload);
  }
  if (payload === undefined) {
    throw invalidResponseError(response.status);
  }
  return { data: payload as T, status: response.status, headers: response.headers };
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  return (await apiRequestEnvelope<T>(path, options)).data;
}
