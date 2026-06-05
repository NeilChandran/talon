"""Require Supabase JWT on all API routes except health/docs."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth import verify_access_token

PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if path in PUBLIC_PATHS:
            return await call_next(request)

        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            try:
                request.state.user_id = verify_access_token(auth[7:].strip())
            except Exception:
                pass
        return await call_next(request)
