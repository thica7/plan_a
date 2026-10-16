"""Optional shared admission limit applied after authentication, before costly work."""

import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from packages.infrastructure.redis_config import get_redis_runtime, redis_options
from packages.infrastructure.redis_runtime import RedisBackendUnavailable

PAID_ENTRY_PATHS = {
    "/api/runs",
    "/api/workflows/competitive-intel",
    "/api/runtime/commands",
    "/api/workflows/scheduled-scan",
    "/api/workflows/monitor",
    "/api/smoke/llm",
    "/api/smoke/search",
}


class RedisRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path.rstrip("/")
        limited = request.method == "POST" and (
            path in PAID_ENTRY_PATHS
            or path.startswith("/api/runs/")
            and path.endswith(("/recover", "/redo", "/resume"))
        )
        options = redis_options()
        if not options.rate_limit_enabled or not limited:
            return await call_next(request)
        subject = getattr(request.state, "enterprise_user", None)
        scope = (
            ["authenticated", subject.get("workspace_id"), subject.get("user_id")]
            if isinstance(subject, dict)
            else ["peer", request.client.host if request.client else "unknown"]
        )
        try:
            decision = await get_redis_runtime().check_rate_limit(
                json.dumps(scope, separators=(",", ":")),
                limit=options.rate_limit_requests,
                window_seconds=options.rate_limit_window_seconds,
            )
        except RedisBackendUnavailable:
            return JSONResponse(
                {"detail": "调用限流服务暂不可用，请稍后重试。"},
                status_code=503,
                headers={"Retry-After": "1"},
            )
        if not decision.allowed:
            return JSONResponse(
                {"detail": "请求过于频繁，请稍后重试。"},
                status_code=429,
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        response = await call_next(request)
        response.headers["X-Shared-RateLimit-Remaining"] = str(decision.remaining)
        return response
