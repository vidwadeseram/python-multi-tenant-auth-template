# pyright: reportCallInDefaultInitializer=false
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db_session
from app.models.permission import Permission
from app.models.rbac import RolePermission, UserRole
from app.models.user import User
from app.services.token_service import TokenService
from app.utils.errors import AppError


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "AUTHENTICATION_REQUIRED", "Authentication credentials were not provided.")

    payload = TokenService().decode_token(credentials.credentials, expected_type="access")
    user = await session.scalar(select(User).where(User.id == payload.subject, User.is_active.is_(True)))
    if user is None:
        raise AppError(401, "USER_NOT_FOUND", "Authenticated user was not found.")
    return user


async def get_user_permission_names(session: AsyncSession, user_id: UUID, tenant_id: UUID | None = None) -> set[str]:
    query = (
        select(Permission.name)
        .distinct()
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
    )
    if tenant_id is None:
        query = query.where(UserRole.tenant_id.is_(None))
    else:
        query = query.where(or_(UserRole.tenant_id.is_(None), UserRole.tenant_id == tenant_id))
    permissions = await session.scalars(query)
    return set(permissions)


def require_permission(permission_name: str, *, global_only: bool = False):
    async def check_permission(
        request: Request,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_db_session),
    ) -> User:
        tenant_id = None if global_only else getattr(request.state, "tenant_id", None)
        permissions = await get_user_permission_names(session, current_user.id, tenant_id=tenant_id)
        if permission_name not in permissions:
            raise AppError(403, "FORBIDDEN", f"Permission '{permission_name}' is required.")
        return current_user

    return check_permission
