from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.entities import ExecutedAction


class ActionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_idempotency_key(self, idempotency_key: str) -> Optional[ExecutedAction]:
        stmt = select(ExecutedAction).where(ExecutedAction.idempotency_key == idempotency_key)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_proposal_id(self, proposal_id: str) -> Optional[ExecutedAction]:
        stmt = select(ExecutedAction).where(ExecutedAction.proposal_id == proposal_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def record_execution(
        self,
        proposal_id: str,
        idempotency_key: str,
        result_json: Dict[str, Any],
        status: str = "SUCCESS",
    ) -> ExecutedAction:
        existing = await self.get_by_idempotency_key(idempotency_key)
        if existing:
            return existing

        action = ExecutedAction(
            proposal_id=proposal_id,
            idempotency_key=idempotency_key,
            result_json=result_json,
            status=status,
        )
        self.db.add(action)
        await self.db.commit()
        await self.db.refresh(action)
        return action
