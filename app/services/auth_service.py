# pyright: reportUnannotatedClassAttribute=false, reportUnusedCallResult=false
from datetime import UTC, datetime

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_verification_token import EmailVerificationToken
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.rbac import UserRole
from app.models.role import Role
from app.models.tenant_member import TenantMember
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
        await self.session.flush()

        default_role = await self.session.scalar(select(Role).where(Role.name == "user"))
        if default_role is None:
            raise AppError(500, "ROLE_NOT_FOUND", "Default user role has not been seeded.")
        self.session.add(UserRole(user_id=user.id, role_id=default_role.id, tenant_id=None))

        verification_token = await self._issue_email_verification_token(user.id)
        await self.session.commit()
        await self.session.refresh(user)
        await send_email(
            recipient=user.email,
            subject="Verify your account",
            body=f"Welcome {user.first_name}, your verification token is: {verification_token}",
        )
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
        token_record = await self._get_valid_email_verification_token(token)
        user = await self.session.scalar(select(User).where(User.id == token_record.user_id))
        if user is None:
            raise AppError(404, "USER_NOT_FOUND", "User not found.")
        if user.is_verified:
            raise AppError(400, "ALREADY_VERIFIED", "Email is already verified.")
        user.is_verified = True
        token_record.used_at = datetime.now(UTC)
        await self.session.commit()

    async def forgot_password(self, email: str) -> None:
        user = await self.session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            return
        reset_token = await self._issue_password_reset_token(user.id)
        await self.session.commit()
        await send_email(
            recipient=user.email,
            subject="Password Reset",
            body=f"Your password reset token is: {reset_token}",
        )

    async def reset_password(self, token: str, new_password: str) -> None:
        token_record = await self._get_valid_password_reset_token(token)
        user = await self.session.scalar(select(User).where(User.id == token_record.user_id))
        if user is None:
            raise AppError(404, "USER_NOT_FOUND", "User not found.")
        user.password_hash = hash_password(new_password)
        token_record.used_at = datetime.now(UTC)
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await self.session.commit()

    async def _issue_email_verification_token(self, user_id: UUID) -> str:
        token = self.token_service.create_one_time_token()
        self.session.add(
            EmailVerificationToken(
                user_id=user_id,
                token_hash=self.token_service.hash_token(token),
                expires_at=datetime.now(UTC) + self.token_service.verification_token_lifetime,
            )
        )
        await self.session.flush()
        return token

    async def _issue_password_reset_token(self, user_id: UUID) -> str:
        token = self.token_service.create_one_time_token()
        self.session.add(
            PasswordResetToken(
                user_id=user_id,
                token_hash=self.token_service.hash_token(token),
                expires_at=datetime.now(UTC) + self.token_service.password_reset_token_lifetime,
            )
        )
        await self.session.flush()
        return token

    async def _get_valid_email_verification_token(self, token: str) -> EmailVerificationToken:
        token_record = await self.session.scalar(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == self.token_service.hash_token(token),
                EmailVerificationToken.used_at.is_(None),
            )
        )
        if token_record is None or token_record.expires_at <= datetime.now(UTC):
            raise AppError(400, "INVALID_VERIFICATION_TOKEN", "Verification token is invalid or expired.")
        return token_record

    async def _get_valid_password_reset_token(self, token: str) -> PasswordResetToken:
        token_record = await self.session.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == self.token_service.hash_token(token),
                PasswordResetToken.used_at.is_(None),
            )
        )
        if token_record is None or token_record.expires_at <= datetime.now(UTC):
            raise AppError(400, "INVALID_PASSWORD_RESET_TOKEN", "Password reset token is invalid or expired.")
        return token_record
