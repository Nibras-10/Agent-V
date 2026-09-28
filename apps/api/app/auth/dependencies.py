import time
from typing import List, Optional
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.redis import redis_client
from app.models.entities import User
from app.schemas.auth import TokenData
from app.auth.security import decode_access_token, ROLE_SCOPES

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        token_version = payload.get("ver", 0)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token claims",
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    stmt = select(User).where(User.id == user_id, User.is_active.is_(True))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user or not user.is_active or not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found, inactive, or not verified",
        )
    if token_version != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication token has been revoked")
    return user


def require_role(*roles: str):
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted for role '{current_user.role}'",
            )
        return current_user
    return role_checker


def require_scope(*scopes: str):
    def scope_checker(
        credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
        current_user: User = Depends(get_current_user),
    ) -> User:
        token = credentials.credentials if credentials else ""
        payload = decode_access_token(token)
        if payload.get("role") != current_user.role:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Role changed; sign in again")
        token_scopes = ROLE_SCOPES.get(current_user.role, [])
        for s in scopes:
            if s not in token_scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing required permission scope: {s}",
                )
        return current_user
    return scope_checker


def validate_customer_access(current_user: User, target_customer_id: str) -> None:
    """Enforce object-level access control (BOLA prevention)."""
    # Reviewers, admins, support agents can view support items across customers
    if current_user.role in ["admin", "reviewer", "support_agent", "auditor"]:
        return
    # Customer can ONLY access their own customer_id
    if current_user.role == "customer":
        if current_user.customer_id != target_customer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Customer cannot access records of another customer",
            )
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


async def enforce_rate_limit(key_prefix: str, identifier: str, max_requests: int = 30, window_seconds: int = 60):
    key = f"rate_limit:{key_prefix}:{identifier}"
    count = await redis_client.increment_window(key, window_seconds)
    if count > max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": str(window_seconds)},
        )
