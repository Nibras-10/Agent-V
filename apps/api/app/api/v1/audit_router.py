from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import User
from app.auth.dependencies import require_scope, validate_customer_access
from app.schemas.audit import AuditEventResponse
from app.repositories.audit_repo import AuditRepository
from app.repositories.ticket_repo import TicketRepository

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("/{ticket_id}", response_model=List[AuditEventResponse])
async def get_ticket_audit_trail(
    ticket_id: str,
    current_user: User = Depends(require_scope("audit:read")),
    db: AsyncSession = Depends(get_db),
):
    ticket_repo = TicketRepository(db)
    ticket = await ticket_repo.get_by_id(ticket_id, load_conversations=False)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    validate_customer_access(current_user, ticket.customer_id)

    audit_repo = AuditRepository(db)
    events = await audit_repo.list_for_ticket(ticket_id)
    return [
        AuditEventResponse(
            id=e.id,
            request_id=e.request_id,
            actor_id=e.actor_id,
            actor_type=e.actor_type,
            event_type=e.event_type,
            resource_type=e.resource_type,
            resource_id=e.resource_id,
            ticket_id=e.ticket_id,
            metadata_redacted=e.metadata_redacted,
            created_at=e.created_at,
        )
        for e in events
    ]
