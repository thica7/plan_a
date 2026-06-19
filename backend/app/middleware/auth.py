from __future__ import annotations

import json
import os
import secrets

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"
EXCLUDED_PATH_PREFIXES = ("/api/health", "/docs", "/openapi.json", "/redoc")
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "competiscope_api_token")


def _configured_token_subjects() -> dict[str, dict[str, str | None]]:
    raw_subjects = os.getenv("AUTH_TOKEN_SUBJECTS")
    if raw_subjects:
        try:
            parsed = json.loads(raw_subjects)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            subjects: dict[str, dict[str, str | None]] = {}
            for token, value in parsed.items():
                if not isinstance(token, str) or not token:
                    continue
                if isinstance(value, dict):
                    subjects[token] = {
                        "user_id": _string_or_none(value.get("user_id")),
                        "role": _string_or_none(value.get("role")),
                        "workspace_id": _string_or_none(value.get("workspace_id")),
                    }
            if subjects:
                return subjects

    raw_tokens = os.getenv("AUTH_BEARER_TOKENS") or os.getenv("AUTH_BEARER_TOKEN") or ""
    tokens = [item.strip() for item in raw_tokens.split(",") if item.strip()]
    if not tokens:
        return {}
    subject = {
        "user_id": os.getenv("AUTH_USER_ID", "api-user"),
        "role": os.getenv("AUTH_USER_ROLE", "viewer"),
        "workspace_id": os.getenv("AUTH_WORKSPACE_ID") or None,
    }
    return {token: subject for token in tokens}


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    return cookie_token.strip() if cookie_token else None


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

        token_subjects = _configured_token_subjects()
        if not token_subjects:
            return JSONResponse(
                {"detail": "Authentication is enabled but no bearer tokens are configured"},
                status_code=503,
            )

        token = _bearer_token(request)
        if not token:
            return JSONResponse(
                {"detail": "Missing or invalid authorization header"},
                status_code=401,
            )

        subject = next(
            (
                configured_subject
                for configured_token, configured_subject in token_subjects.items()
                if secrets.compare_digest(token, configured_token)
            ),
            None,
        )
        if subject is None:
            return JSONResponse({"detail": "Invalid bearer token"}, status_code=401)

        request.state.enterprise_user = subject
        return await call_next(request)
