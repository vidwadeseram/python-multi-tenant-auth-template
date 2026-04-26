from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenData
from app.services.token_service import TokenService
from app.utils.email import send_email
from app.utils.errors import AppError
from app.utils.security import hash_password, verify_password


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.token_service = TokenService()

    async def register(self, payload: RegisterRequest) -> User:
        existing = await self.session.scalar(select(User).where(User.email == payload.email.lower()))
        if existing:
            raise AppError(400, "EMAIL_ALREADY_EXISTS", "A user with this email already exists.")

        user = User(
            email=payload.email.lower(),
            password_hash=hash_password(payload.password),
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip(),
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)

        verification_token = self.token_service.create_verification_token(str(user.id), user.email)
        await send_email(
            recipient=user.email,
            subject="Verify your account",
            body=f"Welcome {user.first_name}, your verification token is: {verification_token}",
        )
        return user

    async def login(self, payload: LoginRequest) -> TokenData:
        user = await self.session.scalar(select(User).where(User.email == payload.email.lower()))
        if not user or not verify_password(payload.password, user.password_hash):
            raise AppError(401, "INVALID_CREDENTIALS", "Invalid email or password.")
        if not user.is_active:
            raise AppError(403, "USER_INACTIVE", "User account is inactive.")

        tokens = await self.token_service.issue_token_pair(self.session, user.id)
        await self.session.commit()
        return tokens

    async def logout(self, refresh_token: str) -> None:
        payload = self.token_service.decode_token(refresh_token, expected_type="refresh")
        hashed = self.token_service.hash_token(refresh_token)
        token_record = await self.session.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hashed,
                RefreshToken.user_id == payload.subject,
                RefreshToken.revoked_at.is_(None),
            )
        )
        if token_record is None:
            raise AppError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid.")

        token_record.revoked_at = datetime.now(UTC)
        await self.session.commit()

    async def refresh(self, refresh_token: str) -> TokenData:
        payload = self.token_service.decode_token(refresh_token, expected_type="refresh")
        hashed = self.token_service.hash_token(refresh_token)
        token_record = await self.session.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hashed,
                RefreshToken.user_id == payload.subject,
                RefreshToken.revoked_at.is_(None),
            )
        )
        if token_record is None or token_record.expires_at <= datetime.now(UTC):
            raise AppError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired.")

        token_record.revoked_at = datetime.now(UTC)
        await self.session.flush()
        tokens = await self.token_service.issue_token_pair(self.session, payload.subject)
        await self.session.commit()
        return tokens
