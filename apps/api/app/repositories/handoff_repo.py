from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.entities import HumanQueue


class HandoffRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def enqueue(
        self,
        ticket_id: str,
        reason_code: str,
        summary: str,
    ) -> HumanQueue:
        # Check if already enqueued to prevent duplicate handoffs
        stmt = (
            select(HumanQueue)
            .where(HumanQueue.ticket_id == ticket_id, HumanQueue.status == "PENDING")
        )
        res = await self.db.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing:
            return existing

        item = HumanQueue(
            ticket_id=ticket_id,
            reason_code=reason_code,
            summary=summary,
            status="PENDING",
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def list_pending(self, limit: int = 50) -> List[HumanQueue]:
        stmt = (
            select(HumanQueue)
            .where(HumanQueue.status == "PENDING")
            .order_by(HumanQueue.created_at.desc())
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())
