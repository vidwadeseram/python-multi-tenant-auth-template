# pyright: reportUnannotatedClassAttribute=false, reportUnknownMemberType=false, reportAny=false
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import secrets
from uuid import UUID

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.refresh_token import RefreshToken
from app.schemas.auth import TokenData
from app.utils.errors import AppError


@dataclass(slots=True)
class TokenPayload:
    subject: UUID
    token_type: str
    tenant_id: UUID | None = None


class TokenService:
    def __init__(self):
        self.settings = get_settings()
        self.verification_token_lifetime = timedelta(hours=24)
        self.password_reset_token_lifetime = timedelta(hours=2)

    def create_access_token(self, user_id: str, tenant_id: UUID | None = None) -> tuple[str, datetime]:
        expires_at = datetime.now(UTC) + timedelta(minutes=self.settings.jwt_access_expire_minutes)
        payload = {"sub": user_id, "type": "access", "exp": expires_at}
        if tenant_id is not None:
            payload["tenant_id"] = str(tenant_id)
        token = jwt.encode(payload, self.settings.jwt_secret, algorithm=self.settings.jwt_algorithm)
        return token, expires_at

    def create_refresh_token(self, user_id: str, tenant_id: UUID | None = None) -> tuple[str, datetime]:
        expires_at = datetime.now(UTC) + timedelta(days=self.settings.jwt_refresh_expire_days)
        payload = {"sub": user_id, "type": "refresh", "exp": expires_at}
        if tenant_id is not None:
            payload["tenant_id"] = str(tenant_id)
        token = jwt.encode(payload, self.settings.jwt_secret, algorithm=self.settings.jwt_algorithm)
        return token, expires_at

    def create_one_time_token(self) -> str:
        return secrets.token_urlsafe(32)

    async def issue_token_pair(self, session: AsyncSession, user_id: UUID, tenant_id: UUID | None = None) -> TokenData:
        access_token, _ = self.create_access_token(str(user_id), tenant_id=tenant_id)
        refresh_token, refresh_expires_at = self.create_refresh_token(str(user_id), tenant_id=tenant_id)
        session.add(
            RefreshToken(
                user_id=user_id,
                tenant_id=tenant_id,
                token_hash=self.hash_token(refresh_token),
                expires_at=refresh_expires_at,
            )
        )
        await session.flush()
        return TokenData(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            expires_in=self.settings.jwt_access_expire_minutes * 60,
        )

    def decode_token(self, token: str, expected_type: str | None = None) -> TokenPayload:
        try:
            payload = jwt.decode(token, self.settings.jwt_secret, algorithms=[self.settings.jwt_algorithm])
        except jwt.ExpiredSignatureError as exc:
            raise AppError(401, "TOKEN_EXPIRED", "Token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise AppError(401, "INVALID_TOKEN", "Token is invalid.") from exc

        token_type = payload.get("type", "access")
        if expected_type and token_type != expected_type:
            raise AppError(401, "INVALID_TOKEN_TYPE", "Token type is invalid.")

        subject = payload.get("sub")
        if subject is None:
            raise AppError(401, "INVALID_TOKEN", "Token subject is missing.")

        tenant_id = payload.get("tenant_id")

        return TokenPayload(
            subject=UUID(subject),
            token_type=token_type,
            tenant_id=UUID(tenant_id) if tenant_id else None,
        )

    def hash_token(self, token: str) -> str:
        return sha256(token.encode("utf-8")).hexdigest()
