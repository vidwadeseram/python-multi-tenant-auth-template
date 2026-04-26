from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.user import UserRead


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(RefreshTokenRequest):
    pass


class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class TokenResponse(BaseModel):
    data: TokenData


class UserEnvelope(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserRead
    message: str


class AuthUserResponse(BaseModel):
    data: UserEnvelope


class MessageData(BaseModel):
    message: str


class MessageResponse(BaseModel):
    data: MessageData
