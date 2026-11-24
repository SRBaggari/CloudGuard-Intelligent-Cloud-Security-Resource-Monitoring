"""Simple in-memory sliding-window rate limiter middleware (per client IP)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float = 60.0) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                retry = int(window - (now - q[0])) + 1
                return False, retry
            q.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_limit: int, default_limit: int):
        super().__init__(app)
        self.auth_limit = auth_limit
        self.default_limit = default_limit

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"
        if path.startswith("/api/auth/login") or path.startswith("/api/auth/register"):
            ok, retry = limiter.allow(f"auth:{ip}", self.auth_limit)
        else:
            ok, retry = limiter.allow(f"api:{ip}", self.default_limit)
        if not ok:
            return JSONResponse(
                {"detail": "Too many requests. Please slow down."},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
        return await call_next(request)
