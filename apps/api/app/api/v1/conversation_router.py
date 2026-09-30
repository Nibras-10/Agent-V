from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import User
from app.auth.dependencies import (
    get_current_user,
    require_scope,
    validate_customer_access,
    enforce_rate_limit,
)
from app.schemas.ticket import (
    ConversationCreate,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
)
from app.repositories.ticket_repo import TicketRepository, ConversationRepository
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(require_scope("ticket:write")),
    db: AsyncSession = Depends(get_db),
):
    ticket_repo = TicketRepository(db)
    conv_repo = ConversationRepository(db)
    if current_user.role != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only customer accounts can start a customer conversation")

    # If ticket_id not provided, create a new ticket for the customer
    if payload.ticket_id:
        ticket = await ticket_repo.get_by_id(payload.ticket_id, load_conversations=False)
        if not ticket:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
        validate_customer_access(current_user, ticket.customer_id)
        ticket_id = ticket.id
    else:
        if not current_user.customer_id and current_user.role == "customer":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer record missing")
        if not current_user.customer_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer account is not linked to a customer record")
        ticket = await ticket_repo.create_ticket(
            customer_id=current_user.customer_id,
            subject=payload.subject or "Support Inquiry",
        )
        ticket_id = ticket.id

    conv = await conv_repo.create_conversation(ticket_id=ticket_id, channel="web")

    if payload.initial_message:
        workflow_service = WorkflowService(db)
        await workflow_service.handle_customer_message(
            conversation_id=conv.id,
            content=payload.initial_message,
            user=current_user,
        )
        # Reload conversation with messages
        conv = await conv_repo.get_by_id(conv.id)

    return ConversationResponse(
        id=conv.id,
        ticket_id=conv.ticket_id,
        channel=conv.channel,
        created_at=conv.created_at,
        messages=[
            MessageResponse(
                id=m.id,
                conversation_id=m.conversation_id,
                actor_type=m.actor_type,
                actor_id=m.actor_id,
                content=m.content,
                created_at=m.created_at,
            )
            for m in conv.messages
        ],
    )


@router.post("/{id}/messages", response_model=MessageResponse)
async def post_message(
    id: str,
    payload: MessageCreate,
    current_user: User = Depends(require_scope("ticket:write")),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limit("message", current_user.id, max_requests=20, window_seconds=60)

    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_by_id(id)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    ticket_repo = TicketRepository(db)
    ticket = await ticket_repo.get_by_id(conv.ticket_id, load_conversations=False)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated ticket not found")

    if current_user.role != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only customer accounts can submit customer messages")
    validate_customer_access(current_user, ticket.customer_id)

    workflow_service = WorkflowService(db)
    result = await workflow_service.handle_customer_message(
        conversation_id=conv.id,
        content=payload.content,
        user=current_user,
    )

    agent_msg = result["agent_message"]
    return MessageResponse(
        id=agent_msg.id,
        conversation_id=agent_msg.conversation_id,
        actor_type=agent_msg.actor_type,
        actor_id=agent_msg.actor_id,
        content=agent_msg.content,
        created_at=agent_msg.created_at,
        workflow_status=result.get("workflow_status"),
        intent=result.get("intent"),
        approval_id=result.get("approval_id"),
        recommended_action=result.get("proposed_action"),
    )
