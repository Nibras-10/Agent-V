from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from app.core.config import settings

ph = PasswordHasher()

ROLE_SCOPES: Dict[str, List[str]] = {
    "customer": ["ticket:read", "ticket:write"],
    "support_agent": ["ticket:read", "ticket:write", "approval:read"],
    "reviewer": ["ticket:read", "approval:read", "approval:decide", "audit:read"],
    "auditor": ["ticket:read", "approval:read", "audit:read"],
    "admin": ["ticket:read", "ticket:write", "approval:read", "approval:decide", "audit:read"],
}


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, Exception):
        return False


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    customer_id: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)

    scopes = ROLE_SCOPES.get(role, [])

    payload: Dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "role": role,
        "customer_id": customer_id,
        "scopes": scopes,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "exp": int(expire.timestamp()),
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }

    return jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    return jwt.decode(
        token,
        settings.JWT_SIGNING_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
    )
