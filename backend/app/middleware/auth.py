import os

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"
EXCLUDED_PATH_PREFIXES = ("/api/health", "/docs", "/openapi.json", "/redoc")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (
            not AUTH_ENABLED
            or request.method == "OPTIONS"
            or not path.startswith("/api")
            or path.startswith(EXCLUDED_PATH_PREFIXES)
        ):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"detail": "Missing or invalid authorization header"},
                status_code=401,
            )

        return await call_next(request)
