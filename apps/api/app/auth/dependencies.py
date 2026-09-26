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
from app.auth.security import decode_access_token

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
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
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
        token_scopes = payload.get("scopes", [])
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
    current_val = await redis_client.get(key)
    if current_val is not None and int(current_val) >= max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
        )
    new_val = 1 if current_val is None else int(current_val) + 1
    await redis_client.set(key, str(new_val), ex=window_seconds)
