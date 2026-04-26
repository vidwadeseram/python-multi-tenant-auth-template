"""add rbac tables

Revision ID: 202604260950
Revises: 202604260900
Create Date: 2026-04-26 09:50:00.000000
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202604260950"
down_revision: str | None = "202604260900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

permission_table = sa.table(
    "permissions",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("name", sa.String(length=100)),
    sa.column("description", sa.String(length=255)),
    sa.column("created_at", sa.DateTime(timezone=True)),
)

role_permission_table = sa.table(
    "role_permissions",
    sa.column("role_id", postgresql.UUID(as_uuid=True)),
    sa.column("permission_id", postgresql.UUID(as_uuid=True)),
)


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_permissions_name"), "permissions", ["name"], unique=True)

    op.create_table(
        "role_permissions",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )

    op.create_table(
        "user_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_user_roles_tenant_id"), "user_roles", ["tenant_id"], unique=False)
    op.create_index(
        "uq_user_roles_global_scope",
        "user_roles",
        ["user_id", "role_id"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    op.create_index(
        "uq_user_roles_tenant_scope",
        "user_roles",
        ["user_id", "role_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )

    op.bulk_insert(
        permission_table,
        [
            {"id": uuid.UUID("aaaa0001-0001-0001-0001-000000000001"), "name": "users.read", "description": "View users", "created_at": datetime.utcnow()},
            {"id": uuid.UUID("aaaa0001-0001-0001-0001-000000000002"), "name": "users.write", "description": "Create and update users", "created_at": datetime.utcnow()},
            {"id": uuid.UUID("aaaa0001-0001-0001-0001-000000000003"), "name": "users.delete", "description": "Delete users", "created_at": datetime.utcnow()},
            {"id": uuid.UUID("aaaa0001-0001-0001-0001-000000000004"), "name": "roles.manage", "description": "Manage role assignments", "created_at": datetime.utcnow()},
            {"id": uuid.UUID("aaaa0001-0001-0001-0001-000000000005"), "name": "permissions.manage", "description": "Manage permission definitions", "created_at": datetime.utcnow()},
            {"id": uuid.UUID("aaaa0001-0001-0001-0001-000000000006"), "name": "tenant:create", "description": "Create tenants", "created_at": datetime.utcnow()},
            {"id": uuid.UUID("aaaa0001-0001-0001-0001-000000000007"), "name": "tenant:manage", "description": "Manage tenant settings", "created_at": datetime.utcnow()},
            {"id": uuid.UUID("aaaa0001-0001-0001-0001-000000000008"), "name": "tenant:invite", "description": "Invite tenant members", "created_at": datetime.utcnow()},
            {"id": uuid.UUID("aaaa0001-0001-0001-0001-000000000009"), "name": "tenant:members:read", "description": "View tenant members", "created_at": datetime.utcnow()},
        ],
    )

    super_admin = uuid.UUID("11111111-1111-1111-1111-111111111111")
    admin = uuid.UUID("22222222-2222-2222-2222-222222222222")
    user_role = uuid.UUID("33333333-3333-3333-3333-333333333333")
    tenant_admin = uuid.UUID("44444444-4444-4444-4444-444444444444")
    tenant_member = uuid.UUID("55555555-5555-5555-5555-555555555555")
    p_read = uuid.UUID("aaaa0001-0001-0001-0001-000000000001")
    p_write = uuid.UUID("aaaa0001-0001-0001-0001-000000000002")
    p_delete = uuid.UUID("aaaa0001-0001-0001-0001-000000000003")
    p_roles = uuid.UUID("aaaa0001-0001-0001-0001-000000000004")
    p_permissions = uuid.UUID("aaaa0001-0001-0001-0001-000000000005")
    p_tenant_create = uuid.UUID("aaaa0001-0001-0001-0001-000000000006")
    p_tenant_manage = uuid.UUID("aaaa0001-0001-0001-0001-000000000007")
    p_tenant_invite = uuid.UUID("aaaa0001-0001-0001-0001-000000000008")
    p_tenant_members_read = uuid.UUID("aaaa0001-0001-0001-0001-000000000009")

    op.bulk_insert(
        role_permission_table,
        [
            {"role_id": super_admin, "permission_id": p_read},
            {"role_id": super_admin, "permission_id": p_write},
            {"role_id": super_admin, "permission_id": p_delete},
            {"role_id": super_admin, "permission_id": p_roles},
            {"role_id": super_admin, "permission_id": p_permissions},
            {"role_id": super_admin, "permission_id": p_tenant_create},
            {"role_id": super_admin, "permission_id": p_tenant_manage},
            {"role_id": super_admin, "permission_id": p_tenant_invite},
            {"role_id": super_admin, "permission_id": p_tenant_members_read},
            {"role_id": admin, "permission_id": p_read},
            {"role_id": admin, "permission_id": p_write},
            {"role_id": admin, "permission_id": p_roles},
            {"role_id": admin, "permission_id": p_permissions},
            {"role_id": admin, "permission_id": p_tenant_create},
            {"role_id": admin, "permission_id": p_tenant_manage},
            {"role_id": admin, "permission_id": p_tenant_members_read},
            {"role_id": tenant_admin, "permission_id": p_read},
            {"role_id": tenant_admin, "permission_id": p_write},
            {"role_id": tenant_admin, "permission_id": p_roles},
            {"role_id": tenant_admin, "permission_id": p_tenant_manage},
            {"role_id": tenant_admin, "permission_id": p_tenant_invite},
            {"role_id": tenant_admin, "permission_id": p_tenant_members_read},
            {"role_id": tenant_member, "permission_id": p_tenant_members_read},
        ],
    )


def downgrade() -> None:
    op.drop_index("uq_user_roles_tenant_scope", table_name="user_roles")
    op.drop_index("uq_user_roles_global_scope", table_name="user_roles")
    op.drop_index(op.f("ix_user_roles_tenant_id"), table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_index(op.f("ix_permissions_name"), table_name="permissions")
    op.drop_table("permissions")
