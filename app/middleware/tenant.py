# pyright: reportUnknownVariableType=false
from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.tenant import Tenant
from app.models.tenant_member import TenantMember
from app.services.token_service import TokenService
from app.utils.errors import AppError, build_error_response


def _parse_tenant_id(value: str | None) -> UUID | None:
    if value is None or not value.strip():
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise AppError(400, "INVALID_TENANT_ID", "Tenant ID is invalid.") from exc


async def tenant_context_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    request.state.tenant = None
    request.state.tenant_id = None
    request.state.tenant_member = None

    auth_header = request.headers.get("Authorization")
    header_tenant_id = _parse_tenant_id(request.headers.get("X-Tenant-ID"))
    user_id: UUID | None = None
    token_tenant_id: UUID | None = None

    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        try:
            payload = TokenService().decode_token(token, expected_type="access")
            user_id = payload.subject
            token_tenant_id = payload.tenant_id
        except AppError as exc:
            if header_tenant_id is not None:
                return build_error_response(exc.status_code, exc.code, exc.message)

    if token_tenant_id and header_tenant_id and token_tenant_id != header_tenant_id:
        return build_error_response(400, "TENANT_CONTEXT_MISMATCH", "Tenant context does not match the access token.")

    tenant_id = token_tenant_id or header_tenant_id
    if tenant_id is None:
        return await call_next(request)

    if user_id is None:
        if request.url.path == "/api/v1/auth/login":
            return await call_next(request)
        return build_error_response(401, "AUTHENTICATION_REQUIRED", "Authentication credentials were not provided.")

    async with AsyncSessionLocal() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active.is_(True)))
        if tenant is None:
            return build_error_response(404, "TENANT_NOT_FOUND", "Tenant was not found.")

        membership = await session.scalar(
            select(TenantMember).where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id == user_id,
                TenantMember.is_active.is_(True),
            )
        )
        if membership is None:
            return build_error_response(403, "TENANT_ACCESS_DENIED", "User does not belong to this tenant.")

        request.state.tenant = tenant
        request.state.tenant_id = tenant.id
        request.state.tenant_member = membership

    return await call_next(request)
