from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.entities import User
from app.schemas.auth import Token, LoginRequest, UserResponse
from app.auth.security import verify_password, create_access_token
from app.auth.dependencies import get_current_user, enforce_rate_limit

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/token", response_model=Token)
async def login_for_access_token(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limit("auth", request.email, max_requests=10, window_seconds=60)

    stmt = select(User).where(User.email == request.email, User.is_active.is_(True))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        customer_id=user.customer_id,
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=3600,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        customer_id=current_user.customer_id,
        is_active=current_user.is_active,
    )
