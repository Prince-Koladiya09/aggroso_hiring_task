"""Standard error body (SRS section 12):
{ "error": {"code", "message", "rule_ids", "correlation_id"}, "detail": "<message>" }
`detail` is kept for backwards compatibility with simple clients.
"""
from typing import List, Optional
from fastapi import Request as FastAPIRequest
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.logging import logger

STATUS_CODE_NAMES = {
    400: "BAD_REQUEST", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND",
    409: "CONFLICT", 422: "VALIDATION_ERROR", 502: "UPSTREAM_FAILURE",
}


class AppError(Exception):
    def __init__(self, message: str, code: str = "BAD_REQUEST", status_code: int = 400,
                 rule_ids: Optional[List[str]] = None, fields: Optional[List[dict]] = None):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.rule_ids = rule_ids or []
        self.fields = fields or []
        super().__init__(message)


def _cid(request: FastAPIRequest) -> str:
    return getattr(request.state, "correlation_id", "corr-system")


def error_response(request: FastAPIRequest, status_code: int, code: str, message: str,
                   rule_ids: Optional[List[str]] = None, fields: Optional[List[dict]] = None) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "rule_ids": rule_ids or [],
            "correlation_id": _cid(request),
        },
        "detail": message,
    }
    if fields:
        body["error"]["fields"] = fields
    return JSONResponse(status_code=status_code, content=body)


def register_error_handlers(app) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: FastAPIRequest, exc: AppError):
        return error_response(request, exc.status_code, exc.code, exc.message, exc.rule_ids, exc.fields)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: FastAPIRequest, exc: StarletteHTTPException):
        code = STATUS_CODE_NAMES.get(exc.status_code, "HTTP_ERROR")
        return error_response(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: FastAPIRequest, exc: RequestValidationError):
        fields = []
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
            fields.append({"field": ".".join(loc), "message": err.get("msg", "invalid")})
        summary = "; ".join(f"{f['field'] or 'request'}: {f['message']}" for f in fields) or "Validation failed"
        return error_response(request, 422, "VALIDATION_ERROR", summary, fields=fields)

    @app.exception_handler(Exception)
    async def _unhandled(request: FastAPIRequest, exc: Exception):
        logger.error("unhandled_exception", component="api", path=request.url.path,
                     correlation_id=_cid(request), error=repr(exc))
        # Never leak internals to the client.
        return error_response(request, 500, "INTERNAL_SERVER_ERROR",
                              "An unexpected error occurred. Quote the correlation ID when reporting it.")
