import uuid
from datetime import datetime

from pydantic import BaseModel


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PermissionResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


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

    model_config = {"from_attributes": True}


class UserUpdateRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool | None = None
