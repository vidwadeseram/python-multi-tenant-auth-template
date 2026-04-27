from __future__ import annotations

import uuid

import pytest


class TestUserModel:
    def test_user_tablename(self):
        from app.models.user import User
        assert User.__tablename__ == "users"

    def test_user_has_required_columns(self):
        from app.models.user import User
        cols = {c.name for c in User.__table__.columns}
        assert {"id", "email", "password_hash", "first_name", "last_name", "is_active", "is_verified"}.issubset(cols)

    def test_user_email_is_unique(self):
        from app.models.user import User
        email_col = User.__table__.columns["email"]
        assert email_col.unique is True

    def test_user_is_active_default_true(self):
        from app.models.user import User
        col = User.__table__.columns["is_active"]
        assert col.default.arg is True

    def test_user_is_verified_default_false(self):
        from app.models.user import User
        col = User.__table__.columns["is_verified"]
        assert col.default.arg is False


class TestTenantModel:
    def test_tenant_tablename(self):
        from app.models.tenant import Tenant
        assert Tenant.__tablename__ == "tenants"

    def test_tenant_has_required_columns(self):
        from app.models.tenant import Tenant
        cols = {c.name for c in Tenant.__table__.columns}
        assert {"id", "name", "slug", "owner_id", "is_active"}.issubset(cols)

    def test_tenant_slug_is_unique(self):
        from app.models.tenant import Tenant
        slug_col = Tenant.__table__.columns["slug"]
        assert slug_col.unique is True

    def test_tenant_is_active_default_true(self):
        from app.models.tenant import Tenant
        col = Tenant.__table__.columns["is_active"]
        assert col.default.arg is True


class TestTenantMemberModel:
    def test_tenant_member_tablename(self):
        from app.models.tenant_member import TenantMember
        assert TenantMember.__tablename__ == "tenant_members"

    def test_tenant_member_has_required_columns(self):
        from app.models.tenant_member import TenantMember
        cols = {c.name for c in TenantMember.__table__.columns}
        assert {"id", "tenant_id", "user_id", "role_id", "is_active"}.issubset(cols)

    def test_tenant_member_is_active_default_true(self):
        from app.models.tenant_member import TenantMember
        col = TenantMember.__table__.columns["is_active"]
        assert col.default.arg is True

    def test_tenant_member_unique_constraint(self):
        from app.models.tenant_member import TenantMember
        constraint_names = {c.name for c in TenantMember.__table__.constraints}
        assert any("tenant_id" in (n or "") and "user_id" in (n or "") for n in constraint_names)


class TestRefreshTokenModel:
    def test_refresh_token_tablename(self):
        from app.models.refresh_token import RefreshToken
        assert RefreshToken.__tablename__ == "refresh_tokens"

    def test_refresh_token_has_required_columns(self):
        from app.models.refresh_token import RefreshToken
        cols = {c.name for c in RefreshToken.__table__.columns}
        assert {"id", "user_id", "token_hash", "expires_at"}.issubset(cols)


class TestTenantInvitationModel:
    def test_invitation_tablename(self):
        from app.models.tenant_invitation import TenantInvitation
        assert TenantInvitation.__tablename__ == "tenant_invitations"

    def test_invitation_has_required_columns(self):
        from app.models.tenant_invitation import TenantInvitation
        cols = {c.name for c in TenantInvitation.__table__.columns}
        assert {"id", "tenant_id", "email", "role_id", "token_hash", "expires_at"}.issubset(cols)
