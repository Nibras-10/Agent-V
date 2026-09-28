import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import enforce_rate_limit, get_current_user
from app.auth.security import create_access_token, hash_password, verify_password
from app.core.config import settings
from app.core.database import get_db
from app.core.email import EmailDeliveryError, send_account_link
from app.models.entities import AuthToken, Customer, User
from app.schemas.auth import (
    EmailRequest,
    EmailTokenRequest,
    LoginRequest,
    PasswordResetRequest,
    RegisterRequest,
    Token,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _issue_token(db: AsyncSession, user: User, purpose: str) -> str:
    raw_token = secrets.token_urlsafe(48)
    ttl = settings.AUTH_TOKEN_TTL_MINUTES if purpose == "verify_email" else settings.PASSWORD_RESET_TTL_MINUTES
    await db.execute(
        AuthToken.__table__.update()
        .where(
            AuthToken.user_id == user.id,
            AuthToken.purpose == purpose,
            AuthToken.consumed_at.is_(None),
        )
        .values(consumed_at=datetime.now(timezone.utc))
    )
    db.add(AuthToken(
        user_id=user.id,
        purpose=purpose,
        token_hash=_digest(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl),
    ))
    await db.flush()
    return raw_token


def _access_token(user: User) -> Token:
    return Token(
        access_token=create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
            customer_id=user.customer_id,
            token_version=user.token_version,
        ),
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_MINUTES * 60,
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_customer(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Public signup always creates a customer; privileged roles are never self-assignable."""
    email = str(request.email).strip().lower()
    await enforce_rate_limit("auth-register", email, max_requests=5, window_seconds=3600)

    customer = Customer(
        external_ref=f"web_{secrets.token_hex(8)}",
        display_name=request.name,
        email=email,
    )
    user = User(
        email=email,
        password_hash=hash_password(request.password),
        role="customer",
        customer=customer,
        is_active=True,
        is_verified=not settings.is_production,
        token_version=0,
    )
    db.add(user)
    try:
        await db.flush()
        if settings.is_production:
            raw_token = await _issue_token(db, user, "verify_email")
            await db.commit()
            try:
                await send_account_link(user.email, "verify_email", raw_token)
            except EmailDeliveryError as exc:
                raise HTTPException(status_code=503, detail="Account created. Verification email delivery is temporarily unavailable; request a new verification email.") from exc
            return {"detail": "Account created. Check your email to verify it before signing in."}
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
    return {**_access_token(user).model_dump(), "detail": "Account created."}


@router.post("/token", response_model=Token)
async def login_for_access_token(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = str(request.email).strip().lower()
    await enforce_rate_limit("auth", email, max_requests=10, window_seconds=60)

    result = await db.execute(select(User).where(User.email == email, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Verify your email address before signing in")
    return _access_token(user)


@router.post("/verify-email")
async def verify_email(request: EmailTokenRequest, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(AuthToken).where(
            AuthToken.token_hash == _digest(request.token),
            AuthToken.purpose == "verify_email",
            AuthToken.consumed_at.is_(None),
            AuthToken.expires_at > now,
        ).with_for_update()
    )
    token_record = result.scalar_one_or_none()
    if not token_record:
        raise HTTPException(status_code=400, detail="Verification link is invalid or expired")
    user = await db.get(User, token_record.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Verification link is invalid or expired")
    token_record.consumed_at = now
    user.is_verified = True
    await db.commit()
    return {"detail": "Email verified. You can now sign in."}


@router.post("/verification/resend")
async def resend_verification(request: EmailRequest, db: AsyncSession = Depends(get_db)):
    email = str(request.email).strip().lower()
    await enforce_rate_limit("auth-resend", email, max_requests=3, window_seconds=3600)
    result = await db.execute(select(User).where(User.email == email, User.is_active.is_(True), User.is_verified.is_(False)))
    user = result.scalar_one_or_none()
    if user:
        raw_token = await _issue_token(db, user, "verify_email")
        await db.commit()
        if settings.is_production:
            try:
                await send_account_link(user.email, "verify_email", raw_token)
            except EmailDeliveryError:
                pass
    return {"detail": "If the account needs verification, an email will be sent."}


@router.post("/password/forgot")
async def forgot_password(request: EmailRequest, db: AsyncSession = Depends(get_db)):
    email = str(request.email).strip().lower()
    await enforce_rate_limit("password-reset", email, max_requests=3, window_seconds=3600)
    result = await db.execute(select(User).where(User.email == email, User.is_active.is_(True), User.is_verified.is_(True)))
    user = result.scalar_one_or_none()
    if user:
        raw_token = await _issue_token(db, user, "password_reset")
        await db.commit()
        if settings.is_production:
            try:
                await send_account_link(user.email, "password_reset", raw_token)
            except EmailDeliveryError:
                pass
    return {"detail": "If an active account matches that email, a password reset link will be sent."}


@router.post("/password/reset")
async def reset_password(request: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(AuthToken).where(
            AuthToken.token_hash == _digest(request.token),
            AuthToken.purpose == "password_reset",
            AuthToken.consumed_at.is_(None),
            AuthToken.expires_at > now,
        ).with_for_update()
    )
    token_record = result.scalar_one_or_none()
    if not token_record:
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired")
    user = await db.get(User, token_record.user_id)
    if not user or not user.is_active or not user.is_verified:
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired")
    user.password_hash = hash_password(request.new_password)
    user.token_version += 1
    token_record.consumed_at = now
    await db.execute(
        AuthToken.__table__.update()
        .where(AuthToken.user_id == user.id, AuthToken.purpose == "password_reset", AuthToken.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    await db.commit()
    return {"detail": "Password changed. Please sign in with your new password."}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        customer_id=current_user.customer_id,
        is_active=current_user.is_active,
    )
