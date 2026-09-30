from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_role
from app.core.database import get_db
from app.models.entities import Conversation, Customer, HumanQueue, SupportTicket, User
from app.repositories.ticket_repo import ConversationRepository
from app.repositories.audit_repo import AuditRepository
from app.schemas.staff import StaffTicketUpdate
from app.schemas.ticket import MessageCreate
import uuid

router = APIRouter(prefix="/staff", tags=["Staff Workspace"])
READ_ROLES = ("support_agent", "reviewer", "admin", "auditor")
WORK_ROLES = ("support_agent", "reviewer", "admin")


@router.get("/tickets")
async def list_staff_tickets(
    current_user: User = Depends(require_role(*READ_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    tickets = await db.scalars(
        select(SupportTicket)
        .options(selectinload(SupportTicket.customer), selectinload(SupportTicket.conversations))
        .order_by(SupportTicket.updated_at.desc())
        .limit(100)
    )
    result = []
    for ticket in tickets:
        queue_item = await db.scalar(
            select(HumanQueue)
            .where(HumanQueue.ticket_id == ticket.id, HumanQueue.status.in_(["PENDING", "ASSIGNED"]))
            .order_by(HumanQueue.created_at.desc())
        )
        result.append({
            "id": ticket.id, "subject": ticket.subject, "status": ticket.status,
            "priority": ticket.priority, "created_at": ticket.created_at, "updated_at": ticket.updated_at,
            "customer": {"id": ticket.customer.id, "display_name": ticket.customer.display_name, "email": ticket.customer.email},
            "conversation_count": len(ticket.conversations),
            "handoff": ({"id": queue_item.id, "status": queue_item.status, "assigned_to": queue_item.assigned_to,
                         "reason_code": queue_item.reason_code} if queue_item else None),
        })
    return result


@router.get("/tickets/{ticket_id}")
async def get_staff_ticket(
    ticket_id: str,
    current_user: User = Depends(require_role(*READ_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.scalar(
        select(SupportTicket)
        .where(SupportTicket.id == ticket_id)
        .options(selectinload(SupportTicket.conversations).selectinload(Conversation.messages))
    )
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    customer = await db.get(Customer, ticket.customer_id)
    handoff = await db.scalar(
        select(HumanQueue)
        .where(HumanQueue.ticket_id == ticket.id, HumanQueue.status.in_(["PENDING", "ASSIGNED"]))
        .order_by(HumanQueue.created_at.desc())
    )
    return {
        "id": ticket.id, "subject": ticket.subject, "status": ticket.status,
        "priority": ticket.priority, "created_at": ticket.created_at, "updated_at": ticket.updated_at,
        "customer": {"id": customer.id, "display_name": customer.display_name, "email": customer.email, "phone": customer.phone} if customer else None,
        "handoff": ({"id": handoff.id, "status": handoff.status, "assigned_to": handoff.assigned_to,
                     "reason_code": handoff.reason_code} if handoff else None),
        "conversations": [
            {"id": conversation.id, "channel": conversation.channel, "created_at": conversation.created_at,
             "messages": [
                 {"id": message.id, "actor_type": message.actor_type, "content": message.content, "created_at": message.created_at}
                 for message in conversation.messages
             ]}
            for conversation in ticket.conversations
        ],
    }


@router.post("/tickets/{ticket_id}/reply")
async def reply_to_staff_ticket(
    ticket_id: str,
    payload: MessageCreate,
    current_user: User = Depends(require_role(*WORK_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    conversation = await db.scalar(
        select(Conversation).where(Conversation.ticket_id == ticket.id).order_by(Conversation.created_at.desc())
    )
    repo = ConversationRepository(db)
    if not conversation:
        conversation = await repo.create_conversation(ticket_id=ticket.id, channel="web")
    message = await repo.add_message(
        conversation_id=conversation.id, actor_type="support_agent", actor_id=current_user.id, content=payload.content,
    )
    await AuditRepository(db).log_event(
        request_id=str(uuid.uuid4()), actor_id=current_user.id, actor_type=current_user.role,
        event_type="STAFF_REPLY_SENT", resource_type="conversation", resource_id=conversation.id,
        ticket_id=ticket.id, metadata={"message_id": message.id},
    )
    return {"id": message.id, "conversation_id": conversation.id, "actor_type": message.actor_type,
            "content": message.content, "created_at": message.created_at}


@router.patch("/tickets/{ticket_id}")
async def update_staff_ticket(
    ticket_id: str,
    payload: StaffTicketUpdate,
    current_user: User = Depends(require_role(*WORK_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.get(SupportTicket, ticket_id, with_for_update=True)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide a ticket status or priority to update")
    for field, value in changes.items():
        setattr(ticket, field, value)
    if changes.get("status") == "resolved":
        open_handoffs = await db.scalars(
            select(HumanQueue).where(HumanQueue.ticket_id == ticket.id, HumanQueue.status.in_(["PENDING", "ASSIGNED"]))
        )
        for handoff in open_handoffs:
            handoff.status = "RESOLVED"
    await db.flush()
    await AuditRepository(db).log_event(
        request_id=str(uuid.uuid4()), actor_id=current_user.id, actor_type=current_user.role,
        event_type="TICKET_UPDATED", resource_type="ticket", resource_id=ticket.id,
        ticket_id=ticket.id, metadata=changes,
    )
    return {"id": ticket.id, "status": ticket.status, "priority": ticket.priority}
