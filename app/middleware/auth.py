from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
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


def require_permission(permission_name: str):
    async def check_permission(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_db_session),
    ) -> User:
        result = await session.scalar(
            select(Permission.name)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == current_user.id, Permission.name == permission_name)
        )
        if result is None:
            raise AppError(403, "FORBIDDEN", f"Permission '{permission_name}' is required.")
        return current_user
    return check_permission
