"""Contract error bodies and handlers (error-codes-v1.md section 1)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.services.job_service import JobCreateError

CODE_STATUS: dict[str, int] = {
    "invalid_request": 400,
    "idempotency_key_required": 400,
    "method_not_allowed": 405,
    "job_not_found": 404,
    "report_not_found": 404,
    "export_not_found": 404,
    "stage_not_found": 404,
    "sse_cursor_expired": 410,
    "idempotency_mismatch": 409,
    "active_conflict": 409,
    "illegal_transition": 409,
    "resume_fingerprint_mismatch": 409,
    "export_not_ready": 409,
    "ticker_unresolved": 422,
    "ticker_ambiguous": 422,
    "invalid_date": 422,
    "config_unknown_key": 422,
    "config_invalid_value": 422,
    "rate_limited": 429,
    "internal_error": 500,
    "not_implemented": 501,
    "upstream_error": 502,
    "upstream_timeout": 504,
    "unauthorized": 401,
}

CODE_MESSAGE: dict[str, str] = {
    "invalid_request": "请求格式不正确",
    "idempotency_key_required": "缺少幂等键",
    "method_not_allowed": "不支持该请求方法",
    "job_not_found": "没有找到这个任务",
    "report_not_found": "没有找到这份报告",
    "export_not_found": "没有找到这个导出任务",
    "stage_not_found": "没有找到这个阶段",
    "sse_cursor_expired": "事件流已过期，请刷新任务页",
    "idempotency_mismatch": "该请求与之前的提交不一致",
    "active_conflict": "该股票今日已有进行中的分析",
    "illegal_transition": "当前状态不支持这个操作",
    "resume_fingerprint_mismatch": "配置已变化，无法从检查点继续",
    "export_not_ready": "导出尚未完成",
    "ticker_unresolved": "找不到这只股票",
    "ticker_ambiguous": "匹配到多只股票，请选择一只",
    "invalid_date": "分析日期不正确",
    "config_unknown_key": "不支持的配置项",
    "config_invalid_value": "配置取值不支持",
    "rate_limited": "操作太频繁，请稍后再试",
    "internal_error": "服务暂时不可用",
    "not_implemented": "该功能尚未开放",
    "upstream_error": "数据服务暂时不可用",
    "upstream_timeout": "数据服务响应超时",
    "unauthorized": "未授权",
}


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        *,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code or CODE_STATUS.get(code, 500)
        self.details = details or {}

    @classmethod
    def from_create_error(cls, exc: JobCreateError) -> "ApiError":
        return cls(exc.code, status_code=exc.status_code, details=exc.details)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or "req_unknown"


def _error_response(
    request: Request,
    code: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": CODE_MESSAGE.get(code, CODE_MESSAGE["internal_error"]),
            "request_id": _request_id(request),
        }
    }
    if details:
        # error-codes-v1.md section 1 whitelist: ids, field, allowed values.
        body["error"]["details"] = details
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers={"X-Request-Id": _request_id(request)},
    )


def _field_name(error: dict[str, Any]) -> str | None:
    loc = [part for part in error.get("loc", ()) if part != "body"]
    if not loc:
        return None
    return str(loc[0])


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(request, exc.code, exc.status_code, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        extra = next(
            (error for error in errors if error.get("type") == "extra_forbidden"),
            None,
        )
        if extra is not None:
            # api-v1.md section 0: unknown request fields are 422.
            return _error_response(
                request, "invalid_request", 422, {"field": _field_name(extra)}
            )
        field = _field_name(errors[0]) if errors else None
        details = {"field": field} if field else None
        return _error_response(request, "invalid_request", 400, details)

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, _exc: Exception) -> JSONResponse:
        return _error_response(request, "internal_error", 500)
