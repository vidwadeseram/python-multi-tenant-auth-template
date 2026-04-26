from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db_session
from app.middleware.auth import get_current_user, require_permission
from app.models.permission import Permission
from app.models.rbac import RolePermission, UserRole
from app.models.role import Role
from app.models.user import User
from app.schemas.rbac import (
    PermissionResponse,
    RolePermissionRequest,
    RoleResponse,
    UserListResponse,
    UserRoleRequest,
    UserUpdateRequest,
)
from app.utils.errors import AppError

router = APIRouter(prefix="/api/v1", tags=["admin"])


@router.get("/admin/roles", response_model=list[RoleResponse])
async def list_roles(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage")),
):
    roles = await session.scalars(select(Role).order_by(Role.name))
    return list(roles)


@router.get("/admin/roles/{role_id}/permissions", response_model=list[PermissionResponse])
async def get_role_permissions(
    role_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage")),
):
    permissions = await session.scalars(
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
    )
    return list(permissions)


@router.post("/admin/roles/permissions", response_model=dict)
async def assign_permission_to_role(
    payload: RolePermissionRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage")),
):
    exists = await session.scalar(
        select(RolePermission).where(
            RolePermission.role_id == payload.role_id,
            RolePermission.permission_id == payload.permission_id,
        )
    )
    if exists:
        raise AppError(409, "ALREADY_EXISTS", "Permission already assigned to this role.")
    session.add(RolePermission(role_id=payload.role_id, permission_id=payload.permission_id))
    await session.commit()
    return {"data": {"message": "Permission assigned to role."}}


@router.delete("/admin/roles/permissions", response_model=dict)
async def remove_permission_from_role(
    payload: RolePermissionRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage")),
):
    await session.execute(
        delete(RolePermission).where(
            RolePermission.role_id == payload.role_id,
            RolePermission.permission_id == payload.permission_id,
        )
    )
    await session.commit()
    return {"data": {"message": "Permission removed from role."}}


@router.get("/admin/permissions", response_model=list[PermissionResponse])
async def list_permissions(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage")),
):
    permissions = await session.scalars(select(Permission).order_by(Permission.name))
    return list(permissions)


@router.get("/admin/users", response_model=list[UserListResponse])
async def list_users(
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("users.read")),
):
    users = await session.scalars(select(User).order_by(User.created_at.desc()))
    return list(users)


@router.get("/admin/users/{user_id}", response_model=UserListResponse)
async def get_user(
    user_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("users.read")),
):
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise AppError(404, "USER_NOT_FOUND", "User not found.")
    return user


@router.patch("/admin/users/{user_id}", response_model=UserListResponse)
async def update_user(
    user_id: UUID,
    payload: UserUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("users.write")),
):
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise AppError(404, "USER_NOT_FOUND", "User not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await session.commit()
    await session.refresh(user)
    return user


@router.delete("/admin/users/{user_id}", response_model=dict)
async def delete_user(
    user_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("users.delete")),
):
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise AppError(404, "USER_NOT_FOUND", "User not found.")
    await session.delete(user)
    await session.commit()
    return {"data": {"message": "User deleted."}}


@router.post("/admin/users/roles", response_model=dict)
async def assign_role_to_user(
    payload: UserRoleRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage")),
):
    exists = await session.scalar(
        select(UserRole).where(
            UserRole.user_id == payload.user_id,
            UserRole.role_id == payload.role_id,
        )
    )
    if exists:
        raise AppError(409, "ALREADY_EXISTS", "Role already assigned to this user.")
    session.add(UserRole(user_id=payload.user_id, role_id=payload.role_id))
    await session.commit()
    return {"data": {"message": "Role assigned to user."}}


@router.delete("/admin/users/roles", response_model=dict)
async def remove_role_from_user(
    payload: UserRoleRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("roles.manage")),
):
    await session.execute(
        delete(UserRole).where(
            UserRole.user_id == payload.user_id,
            UserRole.role_id == payload.role_id,
        )
    )
    await session.commit()
    return {"data": {"message": "Role removed from user."}}


@router.get("/admin/users/{user_id}/permissions", response_model=list[PermissionResponse])
async def get_user_permissions(
    user_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_permission("users.read")),
):
    permissions = await session.scalars(
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
    )
    return list(permissions)
