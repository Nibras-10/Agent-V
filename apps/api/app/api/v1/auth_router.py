import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.models.entities import Customer, User
from app.schemas.auth import Token, LoginRequest, RegisterRequest, UserResponse
from app.auth.security import verify_password, create_access_token, hash_password
from app.auth.dependencies import get_current_user, enforce_rate_limit

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register_customer(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a customer account; privileged roles are provisioned by an administrator."""
    email = str(request.email).strip().lower()
    await enforce_rate_limit("auth-register", email, max_requests=5, window_seconds=3600)

    existing = await db.execute(select(User.id).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    customer = Customer(
        external_ref=f"web_{uuid.uuid4().hex[:16]}",
        display_name=request.name.strip(),
        email=email,
    )
    try:
        db.add(customer)
        await db.flush()
        user = User(
            email=email,
            password_hash=hash_password(request.password),
            role="customer",
            customer_id=customer.id,
            is_active=True,
        )
        db.add(user)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    return Token(
        access_token=create_access_token(user.id, user.email, user.role, user.customer_id),
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_MINUTES * 60,
    )


@router.post("/token", response_model=Token)
async def login_for_access_token(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    email = str(request.email).strip().lower()
    await enforce_rate_limit("auth", email, max_requests=10, window_seconds=60)

    stmt = select(User).where(User.email == email, User.is_active.is_(True))
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
        expires_in=settings.ACCESS_TOKEN_MINUTES * 60,
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
