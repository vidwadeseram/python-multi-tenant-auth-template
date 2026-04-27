from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret-value-that-is-long-enough-32chars")
os.environ.setdefault("JWT_ACCESS_EXPIRE_MINUTES", "15")
os.environ.setdefault("JWT_REFRESH_EXPIRE_DAYS", "7")
os.environ.setdefault("SMTP_HOST", "localhost")
os.environ.setdefault("SMTP_PORT", "1025")
os.environ.setdefault("SMTP_SENDER", "test@example.com")
os.environ.setdefault("MULTI_TENANT_MODE", "row")


def make_user(**kwargs):
    user = MagicMock()
    user.id = kwargs.get("id", uuid.uuid4())
    user.email = kwargs.get("email", "user@example.com")
    user.password_hash = kwargs.get("password_hash", "$2b$12$placeholder")
    user.first_name = kwargs.get("first_name", "Test")
    user.last_name = kwargs.get("last_name", "User")
    user.is_active = kwargs.get("is_active", True)
    user.is_verified = kwargs.get("is_verified", False)
    user.created_at = kwargs.get("created_at", datetime.now(UTC))
    return user


def make_tenant(**kwargs):
    tenant = MagicMock()
    tenant.id = kwargs.get("id", uuid.uuid4())
    tenant.name = kwargs.get("name", "Test Tenant")
    tenant.slug = kwargs.get("slug", "test-tenant")
    tenant.owner_id = kwargs.get("owner_id", uuid.uuid4())
    tenant.is_active = kwargs.get("is_active", True)
    tenant.created_at = kwargs.get("created_at", datetime.now(UTC))
    return tenant


def make_role(**kwargs):
    role = MagicMock()
    role.id = kwargs.get("id", uuid.uuid4())
    role.name = kwargs.get("name", "tenant_admin")
    return role


def make_member(**kwargs):
    member = MagicMock()
    member.id = kwargs.get("id", uuid.uuid4())
    member.tenant_id = kwargs.get("tenant_id", uuid.uuid4())
    member.user_id = kwargs.get("user_id", uuid.uuid4())
    member.role_id = kwargs.get("role_id", uuid.uuid4())
    member.is_active = kwargs.get("is_active", True)
    member.joined_at = kwargs.get("joined_at", datetime.now(UTC))
    return member


def make_refresh_token(**kwargs):
    token = MagicMock()
    token.token_hash = kwargs.get("token_hash", "hash")
    token.user_id = kwargs.get("user_id", uuid.uuid4())
    token.tenant_id = kwargs.get("tenant_id", None)
    token.revoked_at = kwargs.get("revoked_at", None)
    token.expires_at = kwargs.get("expires_at", datetime.now(UTC) + timedelta(days=7))
    return token


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    return session


@pytest.fixture
def app():
    from app.main import app as _app
    return _app


@pytest_asyncio.fixture
async def client(app, mock_session) -> AsyncGenerator[AsyncClient, None]:
    from app.deps import get_db_session

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db_session] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
