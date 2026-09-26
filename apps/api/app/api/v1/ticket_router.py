from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import User
from app.auth.dependencies import (
    require_scope,
    validate_customer_access,
)
from app.schemas.ticket import SupportTicketResponse, ConversationResponse, MessageResponse
from app.repositories.ticket_repo import TicketRepository

router = APIRouter(prefix="/tickets", tags=["Tickets"])


@router.get("/{id}", response_model=SupportTicketResponse)
async def get_ticket(
    id: str,
    current_user: User = Depends(require_scope("ticket:read")),
    db: AsyncSession = Depends(get_db),
):
    ticket_repo = TicketRepository(db)
    ticket = await ticket_repo.get_by_id(id, load_conversations=True)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    # Object-level authorization check
    validate_customer_access(current_user, ticket.customer_id)

    conversations_res = []
    for c in ticket.conversations:
        messages_res = [
            MessageResponse(
                id=m.id,
                conversation_id=m.conversation_id,
                actor_type=m.actor_type,
                actor_id=m.actor_id,
                content=m.content,
                created_at=m.created_at,
            )
            for m in c.messages
        ]
        conversations_res.append(
            ConversationResponse(
                id=c.id,
                ticket_id=c.ticket_id,
                channel=c.channel,
                created_at=c.created_at,
                messages=messages_res,
            )
        )

    return SupportTicketResponse(
        id=ticket.id,
        customer_id=ticket.customer_id,
        status=ticket.status,
        priority=ticket.priority,
        subject=ticket.subject,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        conversations=conversations_res,
    )
