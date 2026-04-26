from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User
from app.services.token_service import TokenService
from app.utils.email import send_email
from app.utils.errors import AppError


class EmailVerificationService:
    def __init__(self, session: AsyncSession, token_service: TokenService):
        self.session: AsyncSession = session
        self.token_service: TokenService = token_service

    async def issue_token(self, user: User) -> None:
        raw_token = self.token_service.generate_opaque_token()
        token_record = EmailVerificationToken(
            user_id=user.id,
            token_hash=self.token_service.hash_token(raw_token),
            expires_at=self.token_service.email_verification_expires_at(),
        )
        self.session.add(token_record)
        await self.session.flush()
        await send_email(
            recipient=user.email,
            subject="Verify your account",
            body=f"Welcome {user.first_name}, your verification token is: {raw_token}",
        )

    async def verify_token(self, token: str) -> UUID:
        token_record = await self.session.scalar(
            select(EmailVerificationToken).where(EmailVerificationToken.token_hash == self.token_service.hash_token(token))
        )
        if token_record is None:
            raise AppError(401, "INVALID_TOKEN", "Token is invalid.")
        if token_record.used_at is not None:
            raise AppError(400, "TOKEN_ALREADY_USED", "Token has already been used.")
        if token_record.expires_at <= datetime.now(UTC):
            raise AppError(401, "TOKEN_EXPIRED", "Token has expired.")

        token_record.used_at = datetime.now(UTC)
        await self.session.flush()
        return token_record.user_id
