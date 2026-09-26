from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import User
from app.auth.dependencies import require_role
from app.schemas.handoff import HumanQueueResponse
from app.repositories.handoff_repo import HandoffRepository

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
