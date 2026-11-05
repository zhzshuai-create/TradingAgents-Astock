import { describe, expect, it } from "vitest";

import {
  ApiError,
  CODE_MESSAGES,
  NETWORK_ERROR_MESSAGE,
  UNKNOWN_ERROR_MESSAGE,
  displayErrorMessage,
  toApiError,
} from "./errors";

function body(overrides: Record<string, unknown>) {
  return { error: { request_id: "req_1", ...overrides } };
}

describe("toApiError", () => {
  it("keeps the server code, message and whitelisted details", () => {
    const error = toApiError(
      409,
      body({
        code: "active_conflict",
        message: "该股票今日已有进行中的分析",
        details: { active_job_id: "job-2" },
      }),
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("active_conflict");
    expect(error.status).toBe(409);
    expect(error.message).toBe("该股票今日已有进行中的分析");
    expect(error.details).toEqual({ active_job_id: "job-2" });
    expect(error.requestId).toBe("req_1");
  });

  it("falls back to the local copy for a known code without a message", () => {
    const error = toApiError(404, body({ code: "job_not_found" }));
    expect(error.message).toBe(CODE_MESSAGES.job_not_found);
  });

  it("uses the generic copy for an unknown code without a message", () => {
    const error = toApiError(400, body({ code: "mystery_code" }));
    expect(error.code).toBe("mystery_code");
    expect(error.message).toBe(UNKNOWN_ERROR_MESSAGE);
  });

  it("keeps a safe server message for an unknown code", () => {
    const error = toApiError(
      400,
      body({ code: "mystery_code", message: "请稍后重试" }),
    );
    expect(error.message).toBe("请稍后重试");
  });

  it("maps bodyless statuses without inventing resource codes", () => {
    expect(toApiError(502, undefined).code).toBe("upstream_error");
    expect(toApiError(502, undefined).message).toBe("数据服务暂时不可用");
    expect(toApiError(404, undefined).code).toBe("unknown_error");
    expect(toApiError(404, undefined).message).toBe(UNKNOWN_ERROR_MESSAGE);
  });

  it("drops detail keys outside the contract whitelist", () => {
    const error = toApiError(
      409,
      body({
        code: "active_conflict",
        message: "冲突",
        details: {
          active_job_id: "job-2",
          raw_body: "{\"secret\":true}",
          traceback: "Traceback (most recent call last)",
        },
      }),
    );
    expect(error.details).toEqual({ active_job_id: "job-2" });
  });

  it("replaces unsafe server messages instead of echoing them", () => {
    for (const message of [
      'Traceback (most recent call last):\n  File "app.py", line 3',
      "C:\\Users\\secret\\app.py failed",
      "/home/deploy/app/main.py failed",
      "api_key=sk-live-123",
      "x".repeat(500),
    ]) {
      const error = toApiError(
        500,
        body({ code: "internal_error", message }),
      );
      expect(error.message).toBe(CODE_MESSAGES.internal_error);
      expect(error.message).not.toContain("Traceback");
      expect(error.message).not.toContain("secret");
      expect(error.message.length).toBeLessThanOrEqual(200);
    }
  });

  it("exposes 429 back-off in milliseconds and seconds", () => {
    const error = toApiError(
      429,
      body({
        code: "rate_limited",
        message: "操作太频繁，请稍后再试",
        details: { retry_after_ms: 2500 },
      }),
    );
    expect(error.retryAfterMs).toBe(2500);
    expect(error.retryAfterSeconds).toBe(3);
  });

  it("returns null back-off when the detail is missing or invalid", () => {
    expect(toApiError(429, body({ code: "rate_limited" })).retryAfterMs).toBeNull();
    expect(
      toApiError(429, body({ code: "rate_limited", details: { retry_after_ms: -1 } }))
        .retryAfterMs,
    ).toBeNull();
  });

  it("marks 410 as needing a full page rebuild", () => {
    expect(toApiError(410, body({ code: "sse_cursor_expired" })).needsFullPageRebuild)
      .toBe(true);
    expect(toApiError(409, body({ code: "active_conflict" })).needsFullPageRebuild)
      .toBe(false);
  });

  it("defaults details to an empty object when missing", () => {
    const error = toApiError(409, { error: { code: "active_conflict" } });
    expect(error.details).toEqual({});
  });
});

describe("displayErrorMessage", () => {
  it("prints ApiError text only", () => {
    const error = new ApiError({
      code: "internal_error",
      message: "服务暂时不可用",
      status: 500,
    });
    expect(displayErrorMessage(error)).toBe("服务暂时不可用");
  });

  it("never echoes thrown values or raw payloads", () => {
    expect(displayErrorMessage(new Error("C:\\secret\\stack"))).toBe(
      UNKNOWN_ERROR_MESSAGE,
    );
    expect(displayErrorMessage({ response: "raw" })).toBe(UNKNOWN_ERROR_MESSAGE);
    expect(displayErrorMessage(null)).toBe(UNKNOWN_ERROR_MESSAGE);
  });

  it("uses a generic sentence for a network failure", () => {
    const network = new ApiError({
      code: "network_error",
      message: NETWORK_ERROR_MESSAGE,
      status: 0,
    });
    expect(network.isNetworkError).toBe(true);
    expect(displayErrorMessage(network)).toBe(NETWORK_ERROR_MESSAGE);
  });
});
