from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from tests.conftest import make_user


@pytest.mark.asyncio
class TestRateLimitMiddleware:
    def _make_app_with_rate_limit(self, rate: float, burst: float):
        from fastapi import FastAPI
        from app.middleware.ratelimit import RateLimitMiddleware

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rate=rate, burst=burst, prefix="/api/v1/auth")

        @app.get("/api/v1/auth/test")
        async def test_endpoint():
            return {"ok": True}

        return app

    async def test_requests_within_burst_allowed(self):
        app = self._make_app_with_rate_limit(rate=1.0, burst=5)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for _ in range(5):
                resp = await client.get("/api/v1/auth/test", headers={"X-Forwarded-For": "1.2.3.4"})
                assert resp.status_code == 200

    async def test_burst_exceeded_returns_429(self):
        app = self._make_app_with_rate_limit(rate=0.0, burst=2)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for _ in range(2):
                await client.get("/api/v1/auth/test", headers={"X-Forwarded-For": "9.9.9.9"})
            resp = await client.get("/api/v1/auth/test", headers={"X-Forwarded-For": "9.9.9.9"})
            assert resp.status_code == 429
            assert resp.json()["error"]["code"] == "RATE_LIMITED"

    async def test_non_auth_path_not_rate_limited(self):
        from fastapi import FastAPI
        from app.middleware.ratelimit import RateLimitMiddleware

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rate=0.0, burst=0, prefix="/api/v1/auth")

        @app.get("/health")
        async def health():
            return {"ok": True}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for _ in range(10):
                resp = await client.get("/health")
                assert resp.status_code == 200

    async def test_different_ips_have_separate_buckets(self):
        from app.middleware.ratelimit import RateLimitMiddleware, _Bucket

        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        middleware.rate = 0.0
        middleware.burst = 1
        from collections import defaultdict
        middleware._buckets = defaultdict(lambda: _Bucket(1))

        assert middleware._allow("10.0.0.1") is True
        assert middleware._allow("10.0.0.2") is True
        assert middleware._allow("10.0.0.1") is False
        assert middleware._allow("10.0.0.2") is False


@pytest.mark.asyncio
class TestAuthMiddleware:
    async def test_missing_token_returns_401(self, client):
        resp = await client.get("/api/v1/tenants")
        assert resp.status_code == 401

    async def test_invalid_token_returns_401(self, client):
        resp = await client.get(
            "/api/v1/tenants",
            headers={"Authorization": "Bearer not.a.valid.token"},
        )
        assert resp.status_code == 401

    async def test_wrong_scheme_returns_401(self, client):
        resp = await client.get(
            "/api/v1/tenants",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 401

    async def test_valid_token_passes_auth(self, client, mock_session):
        from app.services.token_service import TokenService

        user = make_user()
        mock_session.scalar.return_value = user

        ts = TokenService()
        token, _ = ts.create_access_token(str(user.id))

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = result_mock

        resp = await client.get(
            "/api/v1/tenants",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
