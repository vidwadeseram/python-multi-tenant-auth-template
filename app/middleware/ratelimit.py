import time
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class _Bucket:
    __slots__ = ("tokens", "last_refill")

    def __init__(self, burst: float) -> None:
        self.tokens = burst
        self.last_refill = time.monotonic()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rate: float = 1 / 60, burst: float = 5, prefix: str = "/api/v1/auth") -> None:
        super().__init__(app)
        self.rate = rate
        self.burst = burst
        self.prefix = prefix
        self._buckets: dict[str, _Bucket] = defaultdict(lambda: _Bucket(burst))

    def _allow(self, ip: str) -> bool:
        bucket = self._buckets[ip]
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        bucket.tokens = min(self.burst, bucket.tokens + elapsed * self.rate)
        bucket.last_refill = now
        if bucket.tokens < 1:
            return False
        bucket.tokens -= 1
        return True

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith(self.prefix):
            ip = request.client.host if request.client else "unknown"
            if not self._allow(ip):
                return JSONResponse(
                    status_code=429,
                    content={"error": {"code": "RATE_LIMITED", "message": "Too many requests. Please try again later."}},
                )
        return await call_next(request)
