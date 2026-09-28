from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.entities import Transaction


class TransactionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, transaction_id: str, for_update: bool = False) -> Optional[Transaction]:
        stmt = select(Transaction).where(Transaction.id == transaction_id)
        if for_update:
            stmt = stmt.with_for_update()
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_recent(self, customer_id: str, limit: int = 10) -> List[Transaction]:
        stmt = (
            select(Transaction)
            .where(Transaction.customer_id == customer_id)
            .order_by(Transaction.occurred_at.desc())
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def apply_refund(
        self,
        transaction_id: str,
        refund_amount_minor: int,
        expected_version: int,
        commit: bool = True,
    ) -> Optional[Transaction]:
        """Atomically deduct refundable amount with optimistic version checking."""
        stmt = select(Transaction).where(Transaction.id == transaction_id).with_for_update()
        res = await self.db.execute(stmt)
        txn = res.scalar_one_or_none()

        if not txn:
            return None
        if txn.version != expected_version:
            raise ValueError(f"Transaction version mismatch (expected {expected_version}, got {txn.version})")
        if txn.refundable_minor < refund_amount_minor:
            raise ValueError(f"Requested refund {refund_amount_minor} exceeds refundable balance {txn.refundable_minor}")

        txn.refundable_minor -= refund_amount_minor
        if txn.refundable_minor == 0:
            txn.status = "refunded"
        txn.version += 1

        if commit:
            await self.db.commit()
            await self.db.refresh(txn)
        return txn
