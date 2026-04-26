from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TenantCreateRequest(BaseModel):
    name: str
    slug: str


class TenantUpdateRequest(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    owner_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TenantResponse(BaseModel):
    data: TenantRead


class TenantListResponse(BaseModel):
    data: list[TenantRead]


class TenantMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: UUID
    role_id: UUID
    is_active: bool
    joined_at: datetime
    user_email: str | None = None
    role_name: str | None = None


class TenantMemberResponse(BaseModel):
    data: TenantMemberRead


class TenantMemberListResponse(BaseModel):
    data: list[TenantMemberRead]


class TenantInviteRequest(BaseModel):
    email: str
    role_id: UUID


class TenantInviteAcceptRequest(BaseModel):
    token: str


class TenantMemberRoleUpdateRequest(BaseModel):
    role_id: UUID
