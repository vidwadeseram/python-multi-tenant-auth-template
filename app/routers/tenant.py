from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db_session
from app.middleware.auth import get_current_user
from app.models.tenant_member import TenantMember
from app.models.user import User
from app.schemas.tenant import (
    TenantCreateRequest,
    TenantInviteAcceptRequest,
    TenantInviteRequest,
    TenantListResponse,
    TenantMemberListResponse,
    TenantMemberRoleUpdateRequest,
    TenantMemberResponse,
    TenantRead,
    TenantResponse,
    TenantUpdateRequest,
)
from app.services.audit_service import AuditLogger
from app.services.tenant_service import TenantService
from app.utils.errors import AppError


router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


async def require_tenant_admin(tenant_id: UUID, user: User, session: AsyncSession) -> TenantMember:
    svc = TenantService(session)
    membership = await svc.get_membership(tenant_id, user.id)
    if membership is None:
        raise AppError(403, "FORBIDDEN", "You are not a member of this tenant.")
    await session.refresh(membership, ["role"])
    if membership.role.name not in ("tenant_admin", "super_admin"):
        raise AppError(403, "FORBIDDEN", "Only tenant admins can perform this action.")
    return membership


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    svc = TenantService(session)
    tenant = await svc.create_tenant(payload.name, payload.slug, current_user.id)
    await AuditLogger(session).log(
        action="tenant.created",
        tenant_id=tenant.id,
        user_id=current_user.id,
        details={"name": tenant.name, "slug": tenant.slug},
    )
    return {"data": tenant}


@router.get("", response_model=TenantListResponse)
async def list_my_tenants(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    svc = TenantService(session)
    tenants = await svc.list_user_tenants(current_user.id)
    return {"data": tenants}


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    svc = TenantService(session)
    membership = await svc.get_membership(tenant_id, current_user.id)
    if membership is None:
        raise AppError(403, "FORBIDDEN", "You are not a member of this tenant.")
    tenant = await svc.get_tenant(tenant_id)
    if tenant is None:
        raise AppError(404, "TENANT_NOT_FOUND", "Tenant not found.")
    return {"data": tenant}


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: UUID,
    payload: TenantUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_tenant_admin(tenant_id, current_user, session)
    svc = TenantService(session)
    tenant = await svc.update_tenant(tenant_id, name=payload.name, is_active=payload.is_active)
    await AuditLogger(session).log(
        action="tenant.updated",
        tenant_id=tenant_id,
        user_id=current_user.id,
        details={"name": payload.name, "is_active": payload.is_active},
    )
    return {"data": tenant}


@router.delete("/{tenant_id}", status_code=status.HTTP_200_OK)
async def delete_tenant(
    tenant_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_tenant_admin(tenant_id, current_user, session)
    svc = TenantService(session)
    await svc.delete_tenant(tenant_id)
    await AuditLogger(session).log(
        action="tenant.deleted",
        tenant_id=tenant_id,
        user_id=current_user.id,
    )
    return {"data": {"message": "Tenant deactivated."}}


@router.get("/{tenant_id}/members", response_model=TenantMemberListResponse)
async def list_members(
    tenant_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    membership = await TenantService(session).get_membership(tenant_id, current_user.id)
    if membership is None:
        raise AppError(403, "FORBIDDEN", "You are not a member of this tenant.")
    svc = TenantService(session)
    members = await svc.list_members(tenant_id)
    out = []
    for m in members:
        await session.refresh(m, ["user", "role"])
        out.append({
            "id": m.id,
            "tenant_id": m.tenant_id,
            "user_id": m.user_id,
            "role_id": m.role_id,
            "is_active": m.is_active,
            "joined_at": m.joined_at,
            "user_email": m.user.email if m.user else None,
            "role_name": m.role.name if m.role else None,
        })
    return {"data": out}


@router.post("/{tenant_id}/invitations", status_code=status.HTTP_201_CREATED)
async def invite_member(
    tenant_id: UUID,
    payload: TenantInviteRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_tenant_admin(tenant_id, current_user, session)
    svc = TenantService(session)
    invitation = await svc.invite_member(tenant_id, payload.email, payload.role_id)
    await AuditLogger(session).log(
        action="tenant.invitation.created",
        tenant_id=tenant_id,
        user_id=current_user.id,
        details={"email": payload.email, "role_id": str(payload.role_id)},
    )
    return {
        "data": {
            "id": str(invitation.id),
            "tenant_id": str(invitation.tenant_id),
            "email": invitation.email,
            "role_id": str(invitation.role_id),
            "expires_at": invitation.expires_at.isoformat(),
            "token": getattr(invitation, "_raw_token", None),
        }
    }


@router.post("/{tenant_id}/invitations/accept", status_code=status.HTTP_200_OK)
async def accept_invitation(
    tenant_id: UUID,
    payload: TenantInviteAcceptRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    svc = TenantService(session)
    member = await svc.accept_invitation(payload.token, current_user.id)
    await AuditLogger(session).log(
        action="tenant.invitation.accepted",
        tenant_id=tenant_id,
        user_id=current_user.id,
        details={"member_id": str(member.id)},
    )
    return {"data": {"message": "Invitation accepted.", "member_id": str(member.id)}}


@router.patch("/{tenant_id}/members/{user_id}/role", status_code=status.HTTP_200_OK)
async def update_member_role(
    tenant_id: UUID,
    user_id: UUID,
    payload: TenantMemberRoleUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_tenant_admin(tenant_id, current_user, session)
    svc = TenantService(session)
    member = await svc.update_member_role(tenant_id, user_id, payload.role_id)
    await AuditLogger(session).log(
        action="tenant.member.role_changed",
        tenant_id=tenant_id,
        user_id=current_user.id,
        details={"target_user_id": str(user_id), "new_role_id": str(payload.role_id)},
    )
    return {"data": {"message": "Member role updated.", "member_id": str(member.id)}}


@router.delete("/{tenant_id}/members/{user_id}", status_code=status.HTTP_200_OK)
async def remove_member(
    tenant_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    await require_tenant_admin(tenant_id, current_user, session)
    svc = TenantService(session)
    await svc.remove_member(tenant_id, user_id)
    await AuditLogger(session).log(
        action="tenant.member.removed",
        tenant_id=tenant_id,
        user_id=current_user.id,
        details={"removed_user_id": str(user_id)},
    )
    return {"data": {"message": "Member removed from tenant."}}
