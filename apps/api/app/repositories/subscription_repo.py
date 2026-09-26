from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.entities import Subscription


class SubscriptionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, subscription_id: str) -> Optional[Subscription]:
        stmt = select(Subscription).where(Subscription.id == subscription_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_active_by_customer(self, customer_id: str) -> Optional[Subscription]:
        stmt = (
            select(Subscription)
            .where(Subscription.customer_id == customer_id, Subscription.status == "active")
            .order_by(Subscription.started_at.desc())
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_by_customer(self, customer_id: str) -> List[Subscription]:
        stmt = (
            select(Subscription)
            .where(Subscription.customer_id == customer_id)
            .order_by(Subscription.started_at.desc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def cancel_subscription(
        self,
        subscription_id: str,
        expected_version: int,
        cancel_at: Optional[datetime] = None,
    ) -> Optional[Subscription]:
        stmt = select(Subscription).where(Subscription.id == subscription_id).with_for_update()
        res = await self.db.execute(stmt)
        sub = res.scalar_one_or_none()

        if not sub:
            return None
        if sub.version != expected_version:
            raise ValueError(f"Subscription version mismatch (expected {expected_version}, got {sub.version})")
        if sub.status == "canceled":
            raise ValueError("Subscription is already canceled")

        sub.status = "canceled"
        sub.cancel_at = cancel_at or datetime.now(timezone.utc)
        sub.version += 1

        await self.db.commit()
        await self.db.refresh(sub)
        return sub
