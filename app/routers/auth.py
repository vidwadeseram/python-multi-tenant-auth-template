from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db_session
from app.middleware.auth import get_current_user
from app.models.user import User
from app.schemas.auth import AuthUserResponse, LoginRequest, LogoutRequest, MessageResponse, RefreshTokenRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=AuthUserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_db_session)):
    user = await AuthService(session).register(payload)
    return {"data": {"user": user, "message": "Registration successful. Verification email sent."}}


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_db_session)):
    tokens = await AuthService(session).login(payload)
    return {"data": tokens.model_dump()}


@router.post("/logout", response_model=MessageResponse)
async def logout(payload: LogoutRequest, session: AsyncSession = Depends(get_db_session)):
    await AuthService(session).logout(payload.refresh_token)
    return {"data": {"message": "Logout successful."}}


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshTokenRequest, session: AsyncSession = Depends(get_db_session)):
    tokens = await AuthService(session).refresh(payload.refresh_token)
    return {"data": tokens.model_dump()}


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return {"data": current_user}
