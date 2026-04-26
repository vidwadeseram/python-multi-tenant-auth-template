from datetime import UTC, datetime

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.models.tenant_member import TenantMember
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenData
from app.services.email_verification_service import EmailVerificationService
from app.services.password_reset_service import PasswordResetService
from app.services.token_service import TokenService
from app.utils.errors import AppError
from app.utils.security import hash_password, verify_password


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session
        self.token_service: TokenService = TokenService()
        self.email_verification_service: EmailVerificationService = EmailVerificationService(session, self.token_service)
        self.password_reset_service: PasswordResetService = PasswordResetService(session, self.token_service)

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
        await self.session.flush()
        await self.email_verification_service.issue_token(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def login(self, payload: LoginRequest, tenant_id: UUID | None = None) -> TokenData:
        user = await self.session.scalar(select(User).where(User.email == payload.email.lower()))
        if not user or not verify_password(payload.password, user.password_hash):
            raise AppError(401, "INVALID_CREDENTIALS", "Invalid email or password.")
        if not user.is_active:
            raise AppError(403, "USER_INACTIVE", "User account is inactive.")

        if tenant_id is not None:
            await self._require_active_tenant_membership(user.id, tenant_id)

        tokens = await self.token_service.issue_token_pair(self.session, user.id, tenant_id=tenant_id)
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

        if token_record.tenant_id is not None:
            await self._require_active_tenant_membership(payload.subject, token_record.tenant_id)

        token_record.revoked_at = datetime.now(UTC)
        await self.session.flush()
        tokens = await self.token_service.issue_token_pair(self.session, payload.subject, tenant_id=token_record.tenant_id)
        await self.session.commit()
        return tokens

    async def _require_active_tenant_membership(self, user_id: UUID, tenant_id: UUID) -> None:
        membership = await self.session.scalar(
            select(TenantMember).where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id == user_id,
                TenantMember.is_active.is_(True),
            )
        )
        if membership is None:
            raise AppError(403, "TENANT_ACCESS_DENIED", "User does not belong to this tenant.")

    async def verify_email(self, token: str) -> None:
        user_id = await self.email_verification_service.verify_token(token)
        user = await self.session.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise AppError(404, "USER_NOT_FOUND", "User not found.")
        if user.is_verified:
            raise AppError(400, "ALREADY_VERIFIED", "Email is already verified.")
        user.is_verified = True
        await self.session.commit()

    async def forgot_password(self, email: str) -> None:
        user = await self.session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            return
        await self.password_reset_service.issue_token(user)
        await self.session.commit()

    async def reset_password(self, token: str, new_password: str) -> None:
        user = await self.password_reset_service.consume_token(token)
        user.password_hash = hash_password(new_password)
        await self.session.commit()
