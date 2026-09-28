from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.entities import ExecutedAction


class ActionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_idempotency_key(self, idempotency_key: str) -> Optional[ExecutedAction]:
        stmt = select(ExecutedAction).where(ExecutedAction.idempotency_key == idempotency_key)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_proposal_id(self, proposal_id: str) -> Optional[ExecutedAction]:
        stmt = select(ExecutedAction).where(ExecutedAction.proposal_id == proposal_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def reserve_execution(self, proposal_id: str, idempotency_key: str) -> ExecutedAction:
        """Persist intent before a gateway call; the same key is used for safe recovery."""
        existing = await self.get_by_proposal_id(proposal_id)
        if existing:
            return existing
        action = ExecutedAction(
            proposal_id=proposal_id,
            idempotency_key=idempotency_key,
            result_json={},
            status="PENDING",
        )
        self.db.add(action)
        try:
            await self.db.commit()
            await self.db.refresh(action)
            return action
        except IntegrityError:
            await self.db.rollback()
            existing = await self.get_by_proposal_id(proposal_id)
            if existing:
                return existing
            raise

    async def complete_execution(
        self,
        action: ExecutedAction,
        result_json: Dict[str, Any],
        status: str = "SUCCESS",
    ) -> None:
        action.result_json = result_json
        action.status = status

    async def record_execution(
        self,
        proposal_id: str,
        idempotency_key: str,
        result_json: Dict[str, Any],
        status: str = "SUCCESS",
    ) -> ExecutedAction:
        action = await self.reserve_execution(proposal_id, idempotency_key)
        if action.status != "SUCCESS":
            await self.complete_execution(action, result_json, status)
            await self.db.commit()
        return action
