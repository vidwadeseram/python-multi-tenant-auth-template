from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.token_service import TokenService
from app.utils.email import send_email
from app.utils.errors import AppError


class PasswordResetService:
    def __init__(self, session: AsyncSession, token_service: TokenService):
        self.session: AsyncSession = session
        self.token_service: TokenService = token_service

    async def issue_token(self, user: User) -> None:
        raw_token = self.token_service.generate_opaque_token()
        token_record = PasswordResetToken(
            user_id=user.id,
            token_hash=self.token_service.hash_token(raw_token),
            expires_at=self.token_service.password_reset_expires_at(),
        )
        self.session.add(token_record)
        await self.session.flush()
        await send_email(
            recipient=user.email,
            subject="Password Reset",
            body=f"Your password reset token is: {raw_token}",
        )

    async def consume_token(self, token: str) -> User:
        token_record = await self.session.scalar(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == self.token_service.hash_token(token))
        )
        if token_record is None:
            raise AppError(401, "INVALID_TOKEN", "Token is invalid.")
        if token_record.used_at is not None:
            raise AppError(400, "TOKEN_ALREADY_USED", "Token has already been used.")
        if token_record.expires_at <= datetime.now(UTC):
            raise AppError(401, "TOKEN_EXPIRED", "Token has expired.")

        user = await self.session.scalar(select(User).where(User.id == token_record.user_id))
        if user is None:
            raise AppError(404, "USER_NOT_FOUND", "User not found.")

        token_record.used_at = datetime.now(UTC)
        _ = await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await self.session.flush()
        return user
