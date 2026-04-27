from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_member, make_role, make_tenant, make_user


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    return session


@pytest.mark.asyncio
class TestTenantServiceCreate:
    async def test_create_tenant_row_mode(self, mock_session):
        from app.services.tenant_service import TenantService

        owner_id = uuid.uuid4()
        tenant = make_tenant(owner_id=owner_id)
        role = make_role(name="tenant_admin")

        mock_session.scalar.side_effect = [role]
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=lambda obj, *a, **kw: None)

        with patch("app.services.tenant_service.Tenant", return_value=tenant):
            with patch("app.services.tenant_service.TenantMember"):
                svc = TenantService(mock_session)
                svc.settings = MagicMock(multi_tenant_mode="row")
                result = await svc.create_tenant("My Tenant", "my-tenant", owner_id)

        assert result is tenant
        mock_session.commit.assert_called_once()

    async def test_create_tenant_missing_role_raises(self, mock_session):
        from app.services.tenant_service import TenantService
        from app.utils.errors import AppError

        owner_id = uuid.uuid4()
        tenant = make_tenant(owner_id=owner_id)
        mock_session.scalar.return_value = None

        with patch("app.services.tenant_service.Tenant", return_value=tenant):
            svc = TenantService(mock_session)
            svc.settings = MagicMock(multi_tenant_mode="row")
            with pytest.raises(AppError) as exc_info:
                await svc.create_tenant("My Tenant", "my-tenant", owner_id)
        assert exc_info.value.code == "ROLE_NOT_FOUND"


@pytest.mark.asyncio
class TestTenantServiceGet:
    async def test_get_tenant_found(self, mock_session):
        from app.services.tenant_service import TenantService

        tenant = make_tenant()
        mock_session.scalar.return_value = tenant

        svc = TenantService(mock_session)
        result = await svc.get_tenant(tenant.id)
        assert result is tenant

    async def test_get_tenant_not_found(self, mock_session):
        from app.services.tenant_service import TenantService

        mock_session.scalar.return_value = None
        svc = TenantService(mock_session)
        result = await svc.get_tenant(uuid.uuid4())
        assert result is None

    async def test_get_membership_found(self, mock_session):
        from app.services.tenant_service import TenantService

        member = make_member()
        mock_session.scalar.return_value = member

        svc = TenantService(mock_session)
        result = await svc.get_membership(member.tenant_id, member.user_id)
        assert result is member


@pytest.mark.asyncio
class TestTenantServiceUpdate:
    async def test_update_tenant_name(self, mock_session):
        from app.services.tenant_service import TenantService

        tenant = make_tenant(name="Old Name")
        mock_session.scalar.return_value = tenant
        mock_session.refresh = AsyncMock(side_effect=lambda obj, *a, **kw: None)

        svc = TenantService(mock_session)
        result = await svc.update_tenant(tenant.id, name="New Name")
        assert tenant.name == "New Name"
        mock_session.commit.assert_called_once()

    async def test_update_tenant_not_found_raises(self, mock_session):
        from app.services.tenant_service import TenantService
        from app.utils.errors import AppError

        mock_session.scalar.return_value = None
        svc = TenantService(mock_session)
        with pytest.raises(AppError) as exc_info:
            await svc.update_tenant(uuid.uuid4(), name="X")
        assert exc_info.value.code == "TENANT_NOT_FOUND"

    async def test_delete_tenant_soft_deletes(self, mock_session):
        from app.services.tenant_service import TenantService

        tenant = make_tenant(is_active=True)
        mock_session.scalar.return_value = tenant

        svc = TenantService(mock_session)
        await svc.delete_tenant(tenant.id)
        assert tenant.is_active is False
        mock_session.commit.assert_called_once()

    async def test_delete_tenant_not_found_raises(self, mock_session):
        from app.services.tenant_service import TenantService
        from app.utils.errors import AppError

        mock_session.scalar.return_value = None
        svc = TenantService(mock_session)
        with pytest.raises(AppError) as exc_info:
            await svc.delete_tenant(uuid.uuid4())
        assert exc_info.value.code == "TENANT_NOT_FOUND"


@pytest.mark.asyncio
class TestTenantServiceMembers:
    async def test_update_member_role_success(self, mock_session):
        from app.services.tenant_service import TenantService

        member = make_member()
        new_role = make_role(name="member")
        mock_session.scalar.side_effect = [member, new_role]
        mock_session.refresh = AsyncMock(side_effect=lambda obj, *a, **kw: None)

        svc = TenantService(mock_session)
        result = await svc.update_member_role(member.tenant_id, member.user_id, new_role.id)
        assert member.role_id == new_role.id

    async def test_update_member_role_member_not_found_raises(self, mock_session):
        from app.services.tenant_service import TenantService
        from app.utils.errors import AppError

        mock_session.scalar.return_value = None
        svc = TenantService(mock_session)
        with pytest.raises(AppError) as exc_info:
            await svc.update_member_role(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        assert exc_info.value.code == "MEMBER_NOT_FOUND"

    async def test_remove_member_success(self, mock_session):
        from app.services.tenant_service import TenantService

        member = make_member(is_active=True)
        mock_session.scalar.return_value = member

        svc = TenantService(mock_session)
        await svc.remove_member(member.tenant_id, member.user_id)
        assert member.is_active is False

    async def test_remove_member_not_found_raises(self, mock_session):
        from app.services.tenant_service import TenantService
        from app.utils.errors import AppError

        mock_session.scalar.return_value = None
        svc = TenantService(mock_session)
        with pytest.raises(AppError) as exc_info:
            await svc.remove_member(uuid.uuid4(), uuid.uuid4())
        assert exc_info.value.code == "MEMBER_NOT_FOUND"


@pytest.mark.asyncio
class TestTenantServiceInvitations:
    async def test_invite_member_success(self, mock_session):
        from app.services.tenant_service import TenantService

        role = make_role()
        invitation = MagicMock()
        invitation.id = uuid.uuid4()
        invitation.tenant_id = uuid.uuid4()
        invitation.email = "invite@example.com"
        invitation.role_id = role.id
        invitation.expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        mock_session.scalar.return_value = role
        mock_session.refresh = AsyncMock(side_effect=lambda obj, *a, **kw: None)

        with patch("app.services.tenant_service.TenantInvitation", return_value=invitation):
            svc = TenantService(mock_session)
            result = await svc.invite_member(uuid.uuid4(), "invite@example.com", role.id)

        assert result is invitation
        mock_session.commit.assert_called_once()

    async def test_invite_member_role_not_found_raises(self, mock_session):
        from app.services.tenant_service import TenantService
        from app.utils.errors import AppError

        mock_session.scalar.return_value = None
        svc = TenantService(mock_session)
        with pytest.raises(AppError) as exc_info:
            await svc.invite_member(uuid.uuid4(), "x@y.com", uuid.uuid4())
        assert exc_info.value.code == "ROLE_NOT_FOUND"

    async def test_accept_invitation_email_mismatch_raises(self, mock_session):
        from app.services.tenant_service import TenantService
        from app.utils.errors import AppError

        invitation = MagicMock()
        invitation.accepted_at = None
        invitation.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        invitation.email = "other@example.com"

        user = make_user(email="user@example.com")
        mock_session.scalar.side_effect = [invitation, user]

        svc = TenantService(mock_session)
        with pytest.raises(AppError) as exc_info:
            await svc.accept_invitation("some-token", user.id)
        assert exc_info.value.code == "INVITATION_EMAIL_MISMATCH"

    async def test_accept_invitation_not_found_raises(self, mock_session):
        from app.services.tenant_service import TenantService
        from app.utils.errors import AppError

        mock_session.scalar.return_value = None
        svc = TenantService(mock_session)
        with pytest.raises(AppError) as exc_info:
            await svc.accept_invitation("bad-token", uuid.uuid4())
        assert exc_info.value.code == "INVITATION_NOT_FOUND"

    async def test_accept_invitation_expired_raises(self, mock_session):
        from app.services.tenant_service import TenantService
        from app.utils.errors import AppError

        invitation = MagicMock()
        invitation.accepted_at = None
        invitation.expires_at = datetime.now(timezone.utc) - timedelta(days=1)

        mock_session.scalar.return_value = invitation
        svc = TenantService(mock_session)
        with pytest.raises(AppError) as exc_info:
            await svc.accept_invitation("some-token", uuid.uuid4())
        assert exc_info.value.code == "INVITATION_EXPIRED"
