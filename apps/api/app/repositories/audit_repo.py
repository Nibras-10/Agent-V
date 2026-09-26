from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.entities import AuditEvent
from app.observability.redaction import redact_data


class AuditRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_event(
        self,
        request_id: str,
        actor_id: str,
        actor_type: str,
        event_type: str,
        resource_type: str,
        resource_id: str,
        ticket_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        safe_meta = redact_data(metadata or {})
        event = AuditEvent(
            request_id=request_id,
            actor_id=actor_id,
            actor_type=actor_type,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            ticket_id=ticket_id,
            metadata_redacted=safe_meta,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def list_for_ticket(self, ticket_id: str, limit: int = 50) -> List[AuditEvent]:
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.ticket_id == ticket_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())
