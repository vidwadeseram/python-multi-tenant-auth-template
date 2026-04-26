from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.role import Role
from app.models.tenant import Tenant
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
