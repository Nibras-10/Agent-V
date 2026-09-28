"""Create a verified staff account from a trusted deployment shell."""
import argparse
import asyncio
import getpass

from sqlalchemy import select
from app.auth.security import hash_password, ROLE_SCOPES
from app.core.database import async_session_factory
from app.models.entities import User

STAFF_ROLES = {"support_agent", "reviewer", "auditor", "admin"}

async def main() -> None:
    parser = argparse.ArgumentParser(description="Provision a staff account; never expose passwords in command arguments.")
    parser.add_argument("email")
    parser.add_argument("role", choices=sorted(STAFF_ROLES))
    args = parser.parse_args()
    email = args.email.strip().lower()
    password = getpass.getpass("Temporary password (12+ chars): ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm or len(password) < 12:
        raise SystemExit("Passwords must match and contain at least 12 characters.")
    async with async_session_factory() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing:
            raise SystemExit("An account with that email already exists; no changes made.")
        user = User(email=email, password_hash=hash_password(password), role=args.role,
                    customer_id=None, is_active=True, is_verified=True, token_version=0)
        db.add(user)
        await db.commit()
    print(f"Provisioned {args.role} account {email}; deliver its password through your approved secure channel.")

if __name__ == "__main__":
    asyncio.run(main())
