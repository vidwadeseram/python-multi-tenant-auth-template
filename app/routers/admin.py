# pyright: reportCallInDefaultInitializer=false, reportUnusedCallResult=false
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db_session
from app.middleware.auth import get_user_permission_names, require_permission
from app.models.permission import Permission
from app.models.rbac import RolePermission, UserRole
from app.models.role import Role
from app.models.tenant_member import TenantMember
from app.models.user import User
from app.schemas.rbac import (
    PermissionCreateRequest,
    PermissionResponse,
    PermissionUpdateRequest,
    RoleCreateRequest,
    RolePermissionRequest,
    RoleResponse,
    RoleUpdateRequest,
    UserListResponse,
    UserRoleRequest,
    UserUpdateRequest,
)
from app.utils.errors import AppError


SYSTEM_ROLE_NAMES = {"super_admin", "admin", "user", "tenant_admin", "tenant_member"}

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _tenant_id_from_request(request: Request) -> UUID | None:
    return getattr(request.state, "tenant_id", None)


async def _get_role(session: AsyncSession, role_id: UUID) -> Role:
    role = await session.scalar(select(Role).where(Role.id == role_id))
    if role is None:
        raise AppError(404, "ROLE_NOT_FOUND", "Role not found.")
    return role


async def _get_permission(session: AsyncSession, permission_id: UUID) -> Permission:
    permission = await session.scalar(select(Permission).where(Permission.id == permission_id))
    if permission is None:
        raise AppError(404, "PERMISSION_NOT_FOUND", "Permission not found.")
    return permission


async def _get_tenant_membership(session: AsyncSession, user_id: UUID, tenant_id: UUID) -> TenantMember:
    membership = await session.scalar(
        select(TenantMember).where(
            TenantMember.user_id == user_id,
            TenantMember.tenant_id == tenant_id,
        )
    )
    if membership is None:
        raise AppError(404, "TENANT_MEMBER_NOT_FOUND", "Tenant member not found.")
    return membership


async def _get_user_for_scope(session: AsyncSession, user_id: UUID, tenant_id: UUID | None) -> User:
    if tenant_id is None:
        user = await session.scalar(select(User).where(User.id == user_id))
    else:
        user = await session.scalar(
            select(User)
            .join(TenantMember, TenantMember.user_id == User.id)
            .where(
                User.id == user_id,
                TenantMember.tenant_id == tenant_id,
                TenantMember.is_active.is_(True),
            )
        )
    if user is None:
        raise AppError(404, "USER_NOT_FOUND", "User not found.")
    return user


async def _serialize_user(session: AsyncSession, user: User, tenant_id: UUID | None) -> UserListResponse:
    global_roles = await session.scalars(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id, UserRole.tenant_id.is_(None))
        .order_by(Role.name)
    )
    tenant_role_name = None
    if tenant_id is not None:
        tenant_role_name = await session.scalar(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id, UserRole.tenant_id == tenant_id, Role.is_tenant_role.is_(True))
            .order_by(Role.name)
        )
    return UserListResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
        updated_at=user.updated_at,
        tenant_id=tenant_id,
        tenant_role_name=tenant_role_name,
        global_roles=list(global_roles),
    )


async def _get_scoped_permissions(session: AsyncSession, user_id: UUID, tenant_id: UUID | None) -> list[Permission]:
    permission_names = await get_user_permission_names(session, user_id, tenant_id=tenant_id)
    if not permission_names:
        return []
    permissions = await session.scalars(select(Permission).where(Permission.name.in_(permission_names)).order_by(Permission.name))
    return list(permissions)


async def _ensure_role_matches_scope(session: AsyncSession, role_id: UUID, tenant_id: UUID | None) -> Role:
    role = await _get_role(session, role_id)
    if tenant_id is None and role.is_tenant_role:
        raise AppError(400, "INVALID_ROLE_SCOPE", "Tenant roles can only be assigned in tenant context.")
    if tenant_id is not None and not role.is_tenant_role:
        raise AppError(400, "INVALID_ROLE_SCOPE", "Global roles cannot be assigned in tenant context.")
    return role


async def _get_default_tenant_member_role(session: AsyncSession) -> Role:
    role = await session.scalar(select(Role).where(Role.name == "tenant_member", Role.is_tenant_role.is_(True)))
    if role is None:
        raise AppError(500, "ROLE_NOT_FOUND", "Default tenant member role has not been seeded.")
    return role


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage", global_only=True)),
):
    roles = await session.scalars(select(Role).order_by(Role.is_tenant_role, Role.name))
    return list(roles)


@router.post("/roles", response_model=RoleResponse)
async def create_role(
    payload: RoleCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage", global_only=True)),
):
    name = payload.name.strip().lower()
    exists = await session.scalar(select(Role).where(Role.name == name))
    if exists is not None:
        raise AppError(409, "ROLE_ALREADY_EXISTS", "A role with this name already exists.")
    role = Role(name=name, description=payload.description.strip(), is_tenant_role=payload.is_tenant_role)
    session.add(role)
    await session.commit()
    await session.refresh(role)
    return role


@router.get("/roles/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage", global_only=True)),
):
    return await _get_role(session, role_id)


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: UUID,
    payload: RoleUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage", global_only=True)),
):
    role = await _get_role(session, role_id)
    if role.name in SYSTEM_ROLE_NAMES and payload.name and payload.name.strip().lower() != role.name:
        raise AppError(400, "SYSTEM_ROLE_LOCKED", "System role names cannot be changed.")
    if payload.name is not None:
        new_name = payload.name.strip().lower()
        existing = await session.scalar(select(Role).where(Role.name == new_name, Role.id != role.id))
        if existing is not None:
            raise AppError(409, "ROLE_ALREADY_EXISTS", "A role with this name already exists.")
        role.name = new_name
    if payload.description is not None:
        role.description = payload.description.strip()
    await session.commit()
    await session.refresh(role)
    return role


@router.delete("/roles/{role_id}", response_model=dict)
async def delete_role(
    role_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage", global_only=True)),
):
    role = await _get_role(session, role_id)
    if role.name in SYSTEM_ROLE_NAMES:
        raise AppError(400, "SYSTEM_ROLE_LOCKED", "System roles cannot be deleted.")
    await session.delete(role)
    await session.commit()
    return {"data": {"message": "Role deleted."}}


@router.get("/roles/{role_id}/permissions", response_model=list[PermissionResponse])
async def get_role_permissions(
    role_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage", global_only=True)),
):
    await _get_role(session, role_id)
    permissions = await session.scalars(
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.name)
    )
    return list(permissions)


@router.post("/roles/permissions", response_model=dict)
async def assign_permission_to_role(
    payload: RolePermissionRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage", global_only=True)),
):
    await _get_role(session, payload.role_id)
    await _get_permission(session, payload.permission_id)
    exists = await session.scalar(
        select(RolePermission).where(
            RolePermission.role_id == payload.role_id,
            RolePermission.permission_id == payload.permission_id,
        )
    )
    if exists is not None:
        raise AppError(409, "ALREADY_EXISTS", "Permission already assigned to this role.")
    session.add(RolePermission(role_id=payload.role_id, permission_id=payload.permission_id))
    await session.commit()
    return {"data": {"message": "Permission assigned to role."}}


@router.delete("/roles/permissions", response_model=dict)
async def remove_permission_from_role(
    payload: RolePermissionRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage", global_only=True)),
):
    await session.execute(
        delete(RolePermission).where(
            RolePermission.role_id == payload.role_id,
            RolePermission.permission_id == payload.permission_id,
        )
    )
    await session.commit()
    return {"data": {"message": "Permission removed from role."}}


@router.get("/permissions", response_model=list[PermissionResponse])
async def list_permissions(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("permissions.manage", global_only=True)),
):
    permissions = await session.scalars(select(Permission).order_by(Permission.name))
    return list(permissions)


@router.post("/permissions", response_model=PermissionResponse)
async def create_permission(
    payload: PermissionCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("permissions.manage", global_only=True)),
):
    name = payload.name.strip().lower()
    exists = await session.scalar(select(Permission).where(Permission.name == name))
    if exists is not None:
        raise AppError(409, "PERMISSION_ALREADY_EXISTS", "A permission with this name already exists.")
    permission = Permission(name=name, description=payload.description.strip())
    session.add(permission)
    await session.commit()
    await session.refresh(permission)
    return permission


@router.get("/permissions/{permission_id}", response_model=PermissionResponse)
async def get_permission(
    permission_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("permissions.manage", global_only=True)),
):
    return await _get_permission(session, permission_id)


@router.patch("/permissions/{permission_id}", response_model=PermissionResponse)
async def update_permission(
    permission_id: UUID,
    payload: PermissionUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("permissions.manage", global_only=True)),
):
    permission = await _get_permission(session, permission_id)
    if payload.name is not None:
        new_name = payload.name.strip().lower()
        existing = await session.scalar(select(Permission).where(Permission.name == new_name, Permission.id != permission.id))
        if existing is not None:
            raise AppError(409, "PERMISSION_ALREADY_EXISTS", "A permission with this name already exists.")
        permission.name = new_name
    if payload.description is not None:
        permission.description = payload.description.strip()
    await session.commit()
    await session.refresh(permission)
    return permission


@router.delete("/permissions/{permission_id}", response_model=dict)
async def delete_permission(
    permission_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("permissions.manage", global_only=True)),
):
    permission = await _get_permission(session, permission_id)
    await session.delete(permission)
    await session.commit()
    return {"data": {"message": "Permission deleted."}}


@router.get("/users", response_model=list[UserListResponse])
async def list_users(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("users.read")),
):
    tenant_id = _tenant_id_from_request(request)
    if tenant_id is None:
        users = list(await session.scalars(select(User).order_by(User.created_at.desc())))
    else:
        result = await session.execute(
            select(User)
            .join(TenantMember, TenantMember.user_id == User.id)
            .where(TenantMember.tenant_id == tenant_id, TenantMember.is_active.is_(True))
            .order_by(TenantMember.joined_at.desc())
        )
        users = list(result.scalars().unique().all())
    return [await _serialize_user(session, user, tenant_id) for user in users]


@router.get("/users/{user_id}", response_model=UserListResponse)
async def get_user(
    user_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("users.read")),
):
    tenant_id = _tenant_id_from_request(request)
    user = await _get_user_for_scope(session, user_id, tenant_id)
    return await _serialize_user(session, user, tenant_id)


@router.patch("/users/{user_id}", response_model=UserListResponse)
async def update_user(
    user_id: UUID,
    payload: UserUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("users.write")),
):
    tenant_id = _tenant_id_from_request(request)
    user = await _get_user_for_scope(session, user_id, tenant_id)
    if payload.first_name is not None:
        user.first_name = payload.first_name.strip()
    if payload.last_name is not None:
        user.last_name = payload.last_name.strip()
    if tenant_id is None:
        if payload.is_active is not None:
            user.is_active = payload.is_active
    else:
        membership = await _get_tenant_membership(session, user_id, tenant_id)
        if payload.is_active is not None:
            membership.is_active = payload.is_active
    await session.commit()
    await session.refresh(user)
    return await _serialize_user(session, user, tenant_id)


@router.delete("/users/{user_id}", response_model=dict)
async def delete_user(
    user_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("users.delete")),
):
    tenant_id = _tenant_id_from_request(request)
    if tenant_id is None:
        user = await _get_user_for_scope(session, user_id, None)
        await session.delete(user)
        message = "User deleted."
    else:
        membership = await _get_tenant_membership(session, user_id, tenant_id)
        membership.is_active = False
        await session.execute(delete(UserRole).where(UserRole.user_id == user_id, UserRole.tenant_id == tenant_id))
        message = "User removed from tenant."
    await session.commit()
    return {"data": {"message": message}}


@router.post("/users/roles", response_model=dict)
async def assign_role_to_user(
    payload: UserRoleRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage")),
):
    tenant_id = _tenant_id_from_request(request)
    await _get_user_for_scope(session, payload.user_id, tenant_id)
    role = await _ensure_role_matches_scope(session, payload.role_id, tenant_id)

    if tenant_id is None:
        exists = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == payload.user_id,
                UserRole.role_id == payload.role_id,
                UserRole.tenant_id.is_(None),
            )
        )
        if exists is not None:
            raise AppError(409, "ALREADY_EXISTS", "Role already assigned to this user.")
        session.add(UserRole(user_id=payload.user_id, role_id=payload.role_id, tenant_id=None))
    else:
        membership = await _get_tenant_membership(session, payload.user_id, tenant_id)
        current_assignment = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == payload.user_id,
                UserRole.role_id == payload.role_id,
                UserRole.tenant_id == tenant_id,
            )
        )
        if current_assignment is not None and membership.role_id == payload.role_id:
            raise AppError(409, "ALREADY_EXISTS", "Role already assigned to this tenant member.")
        await session.execute(delete(UserRole).where(UserRole.user_id == payload.user_id, UserRole.tenant_id == tenant_id))
        session.add(UserRole(user_id=payload.user_id, role_id=payload.role_id, tenant_id=tenant_id))
        membership.role_id = role.id

    await session.commit()
    return {"data": {"message": "Role assigned to user."}}


@router.delete("/users/roles", response_model=dict)
async def remove_role_from_user(
    payload: UserRoleRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage")),
):
    tenant_id = _tenant_id_from_request(request)

    if tenant_id is None:
        assignment = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == payload.user_id,
                UserRole.role_id == payload.role_id,
                UserRole.tenant_id.is_(None),
            )
        )
        if assignment is None:
            raise AppError(404, "USER_ROLE_NOT_FOUND", "Role assignment not found.")
        await session.delete(assignment)
        message = "Role removed from user."
    else:
        membership = await _get_tenant_membership(session, payload.user_id, tenant_id)
        fallback_role = await _get_default_tenant_member_role(session)
        if payload.role_id == fallback_role.id and membership.role_id == fallback_role.id:
            raise AppError(400, "BASE_TENANT_ROLE_REQUIRED", "Tenant members must keep a tenant role assignment.")
        await session.execute(delete(UserRole).where(UserRole.user_id == payload.user_id, UserRole.role_id == payload.role_id, UserRole.tenant_id == tenant_id))
        await session.execute(delete(UserRole).where(UserRole.user_id == payload.user_id, UserRole.tenant_id == tenant_id))
        session.add(UserRole(user_id=payload.user_id, role_id=fallback_role.id, tenant_id=tenant_id))
        membership.role_id = fallback_role.id
        message = "Tenant role reset to tenant_member."

    await session.commit()
    return {"data": {"message": message}}


@router.get("/users/{user_id}/permissions", response_model=list[PermissionResponse])
async def get_user_permissions(
    user_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("users.read")),
):
    tenant_id = _tenant_id_from_request(request)
    await _get_user_for_scope(session, user_id, tenant_id)
    return await _get_scoped_permissions(session, user_id, tenant_id)
