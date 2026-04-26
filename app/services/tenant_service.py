from __future__ import annotations

import hashlib
import secrets
import subprocess
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.tenant_invitation import TenantInvitation
from app.models.tenant_member import TenantMember
from app.utils.errors import AppError


class TenantSchemaService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def build_schema_name(tenant_id: UUID) -> str:
        return f"tenant_{tenant_id.hex}"

    async def create_schema(self, tenant_id: UUID) -> str:
        schema_name = self.build_schema_name(tenant_id)
        await self.session.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
        await self.session.flush()
        return schema_name

    async def run_migrations_for_schema(self, tenant_id: UUID) -> str:
        schema_name = self.build_schema_name(tenant_id)
        subprocess.run(
            ["alembic", "-x", f"tenant_schema={schema_name}", "upgrade", "head"],
            check=True,
            cwd=Path(__file__).resolve().parents[2],
        )
        return schema_name


class TenantService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()
        self.schema_service = TenantSchemaService(session)

    async def create_tenant(self, name: str, slug: str, owner_id: UUID) -> Tenant:
        tenant = Tenant(name=name.strip(), slug=slug.strip().lower(), owner_id=owner_id)
        self.session.add(tenant)
        await self.session.flush()

        tenant_admin_role = await self.session.scalar(select(Role).where(Role.name == "tenant_admin"))
        if tenant_admin_role is None:
            raise AppError(500, "ROLE_NOT_FOUND", "Tenant admin role has not been seeded.")

        self.session.add(TenantMember(tenant_id=tenant.id, user_id=owner_id, role_id=tenant_admin_role.id))

        if self.settings.multi_tenant_mode == "schema":
            await self.schema_service.create_schema(tenant.id)
            await self.session.commit()
            await self.schema_service.run_migrations_for_schema(tenant.id)
            await self.session.refresh(tenant)
            return tenant

        await self.session.commit()
        await self.session.refresh(tenant)
        return tenant

    async def get_tenant(self, tenant_id: UUID) -> Tenant | None:
        return await self.session.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active.is_(True)))

    async def get_membership(self, tenant_id: UUID, user_id: UUID) -> TenantMember | None:
        return await self.session.scalar(
            select(TenantMember).where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id == user_id,
                TenantMember.is_active.is_(True),
            )
        )

    async def list_user_tenants(self, user_id: UUID) -> list[Tenant]:
        result = await self.session.execute(
            select(Tenant)
            .join(TenantMember, TenantMember.tenant_id == Tenant.id)
            .where(TenantMember.user_id == user_id, TenantMember.is_active.is_(True), Tenant.is_active.is_(True))
            .order_by(Tenant.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_tenant(self, tenant_id: UUID, name: str | None = None, is_active: bool | None = None) -> Tenant:
        tenant = await self.get_tenant(tenant_id)
        if tenant is None:
            raise AppError(404, "TENANT_NOT_FOUND", "Tenant not found.")
        if name is not None:
            tenant.name = name.strip()
        if is_active is not None:
            tenant.is_active = is_active
        await self.session.commit()
        await self.session.refresh(tenant)
        return tenant

    async def delete_tenant(self, tenant_id: UUID) -> None:
        tenant = await self.get_tenant(tenant_id)
        if tenant is None:
            raise AppError(404, "TENANT_NOT_FOUND", "Tenant not found.")
        tenant.is_active = False
        await self.session.commit()

    async def list_members(self, tenant_id: UUID) -> list[TenantMember]:
        result = await self.session.execute(
            select(TenantMember)
            .where(TenantMember.tenant_id == tenant_id, TenantMember.is_active.is_(True))
            .order_by(TenantMember.joined_at.desc())
        )
        members = list(result.scalars().all())
        for m in members:
            await self.session.refresh(m, ["user", "role"])
        return members

    async def invite_member(self, tenant_id: UUID, email: str, role_id: UUID) -> TenantInvitation:
        role = await self.session.scalar(select(Role).where(Role.id == role_id))
        if role is None:
            raise AppError(404, "ROLE_NOT_FOUND", "Role not found.")
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        from datetime import datetime, timedelta, timezone

        invitation = TenantInvitation(
            tenant_id=tenant_id,
            email=email.strip().lower(),
            role_id=role_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        self.session.add(invitation)
        await self.session.commit()
        await self.session.refresh(invitation)
        invitation._raw_token = token
        return invitation

    async def accept_invitation(self, token: str, user_id: UUID) -> TenantMember:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        from datetime import datetime, timezone

        invitation = await self.session.scalar(
            select(TenantInvitation).where(
                TenantInvitation.token_hash == token_hash,
                TenantInvitation.accepted_at.is_(None),
            )
        )
        if invitation is None:
            raise AppError(404, "INVITATION_NOT_FOUND", "Invitation not found or already accepted.")
        if invitation.expires_at < datetime.now(timezone.utc):
            raise AppError(400, "INVITATION_EXPIRED", "Invitation has expired.")
        invitation.accepted_at = datetime.now(timezone.utc)
        existing = await self.get_membership(invitation.tenant_id, user_id)
        if existing:
            raise AppError(409, "ALREADY_MEMBER", "User is already a member of this tenant.")
        member = TenantMember(
            tenant_id=invitation.tenant_id,
            user_id=user_id,
            role_id=invitation.role_id,
        )
        self.session.add(member)
        await self.session.commit()
        await self.session.refresh(member)
        return member

    async def update_member_role(self, tenant_id: UUID, user_id: UUID, role_id: UUID) -> TenantMember:
        member = await self.get_membership(tenant_id, user_id)
        if member is None:
            raise AppError(404, "MEMBER_NOT_FOUND", "Member not found.")
        role = await self.session.scalar(select(Role).where(Role.id == role_id))
        if role is None:
            raise AppError(404, "ROLE_NOT_FOUND", "Role not found.")
        member.role_id = role_id
        await self.session.commit()
        await self.session.refresh(member)
        return member

    async def remove_member(self, tenant_id: UUID, user_id: UUID) -> None:
        member = await self.get_membership(tenant_id, user_id)
        if member is None:
            raise AppError(404, "MEMBER_NOT_FOUND", "Member not found.")
        member.is_active = False
        await self.session.commit()
