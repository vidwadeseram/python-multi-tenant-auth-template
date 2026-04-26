from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db_session
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
