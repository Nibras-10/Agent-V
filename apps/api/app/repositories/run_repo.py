from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.entities import AgentRun


class AgentRunRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_run(
        self,
        ticket_id: str,
        model_alias: str = "default",
    ) -> AgentRun:
        run = AgentRun(
            ticket_id=ticket_id,
            model_alias=model_alias,
            graph_status="RUNNING",
            retry_count=0,
            token_counts={},
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def update_run(
        self,
        run_id: str,
        status: str,
        retry_count: int,
        token_counts: Dict[str, Any],
    ) -> Optional[AgentRun]:
        stmt = select(AgentRun).where(AgentRun.id == run_id)
        res = await self.db.execute(stmt)
        run = res.scalar_one_or_none()
        if not run:
            return None

        run.graph_status = status
        run.retry_count = retry_count
        run.token_counts = token_counts
        if status in ["COMPLETED", "HANDED_OFF", "FAILED"]:
            run.ended_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def get_by_id(self, run_id: str) -> Optional[AgentRun]:
        stmt = select(AgentRun).where(AgentRun.id == run_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
