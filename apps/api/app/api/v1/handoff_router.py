from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.core.database import get_db
from app.models.entities import User
from app.auth.dependencies import require_role
from app.schemas.handoff import HumanQueueResponse
from app.repositories.handoff_repo import HandoffRepository
from app.repositories.audit_repo import AuditRepository
from app.models.entities import HumanQueue, SupportTicket

router = APIRouter(prefix="/handoffs", tags=["Human Handoff"])


@router.get("", response_model=List[HumanQueueResponse])
async def list_handoffs(
    current_user: User = Depends(require_role("support_agent", "reviewer", "admin")),
    db: AsyncSession = Depends(get_db),
):
    repo = HandoffRepository(db)
    items = await repo.list_pending()
    return [
        HumanQueueResponse(
            id=item.id,
            ticket_id=item.ticket_id,
            reason_code=item.reason_code,
            summary=item.summary,
            status=item.status,
            assigned_to=item.assigned_to,
            created_at=item.created_at,
        )
        for item in items
    ]


@router.post("/{handoff_id}/assign")
async def assign_handoff(
    handoff_id: str,
    current_user: User = Depends(require_role("support_agent", "reviewer", "admin")),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(HumanQueue, handoff_id, with_for_update=True)
    if not item or item.status == "RESOLVED":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Open handoff not found")
    item.assigned_to = current_user.id
    item.status = "ASSIGNED"
    await db.flush()
    await AuditRepository(db).log_event(
        request_id=str(uuid.uuid4()), actor_id=current_user.id, actor_type=current_user.role,
        event_type="HANDOFF_ASSIGNED", resource_type="human_queue", resource_id=item.id,
        ticket_id=item.ticket_id, metadata={"status": "ASSIGNED"},
    )
    return {"id": item.id, "ticket_id": item.ticket_id, "status": item.status, "assigned_to": item.assigned_to}


@router.post("/{handoff_id}/resolve")
async def resolve_handoff(
    handoff_id: str,
    current_user: User = Depends(require_role("support_agent", "reviewer", "admin")),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(HumanQueue, handoff_id, with_for_update=True)
    if not item or item.status == "RESOLVED":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Open handoff not found")
    item.status = "RESOLVED"
    ticket = await db.get(SupportTicket, item.ticket_id, with_for_update=True)
    if ticket:
        ticket.status = "resolved"
    await db.flush()
    await AuditRepository(db).log_event(
        request_id=str(uuid.uuid4()), actor_id=current_user.id, actor_type=current_user.role,
        event_type="HANDOFF_RESOLVED", resource_type="human_queue", resource_id=item.id,
        ticket_id=item.ticket_id, metadata={"status": "RESOLVED"},
    )
    return {"id": item.id, "ticket_id": item.ticket_id, "status": item.status}
