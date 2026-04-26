# pyright: reportUnannotatedClassAttribute=false
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    is_tenant_role: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=50)
    description: str = Field(min_length=3, max_length=255)
    is_tenant_role: bool = False


class RoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=50)
    description: str | None = Field(default=None, min_length=3, max_length=255)


class PermissionResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PermissionCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    description: str = Field(min_length=3, max_length=255)


class PermissionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=100)
    description: str | None = Field(default=None, min_length=3, max_length=255)


class RolePermissionRequest(BaseModel):
    role_id: uuid.UUID
    permission_id: uuid.UUID


class UserRoleRequest(BaseModel):
    user_id: uuid.UUID
    role_id: uuid.UUID


class UserListResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: uuid.UUID | None = None
    tenant_role_name: str | None = None
    global_roles: list[str] = Field(default_factory=list)


class UserUpdateRequest(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None
