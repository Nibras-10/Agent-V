import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import User
from app.auth.dependencies import (
    require_role,
    require_scope,
    enforce_rate_limit,
)
from app.schemas.approval import ApprovalResponse, ApprovalDecisionRequest
from app.repositories.approval_repo import ApprovalRepository
from app.services.approval_service import ApprovalService
from app.models.entities import Approval, Conversation, Message
from app.repositories.audit_repo import AuditRepository

router = APIRouter(prefix="/approvals", tags=["Approvals"])


def map_approval_to_response(appr) -> ApprovalResponse:
    proposal = appr.proposal
    return ApprovalResponse(
        id=appr.id,
        proposal_id=appr.proposal_id,
        ticket_id=appr.ticket_id,
        action_type=proposal.type if proposal else "unknown",
        proposal_payload=proposal.payload_json if proposal else {},
        proposal_hash=proposal.proposal_hash if proposal else "",
        requested_by_run_id=proposal.run_id if proposal else "",
        status=appr.status,
        reviewer_id=appr.reviewer_id,
        reviewer_comment=appr.comment,
        created_at=appr.created_at,
        decided_at=appr.decided_at,
        expires_at=appr.expires_at,
    )


@router.get("", response_model=List[ApprovalResponse])
async def list_approvals(
    current_user: User = Depends(require_scope("approval:read")),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in {"reviewer", "admin", "auditor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approval queue access is restricted")
    repo = ApprovalRepository(db)
    approvals = await repo.list_all_approvals()
    return [map_approval_to_response(a) for a in approvals]


@router.get("/{id}", response_model=ApprovalResponse)
async def get_approval(
    id: str,
    current_user: User = Depends(require_scope("approval:read")),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in {"reviewer", "admin", "auditor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approval access is restricted")
    repo = ApprovalRepository(db)
    approval = await repo.get_approval(id)
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return map_approval_to_response(approval)


@router.post("/{id}/decision")
async def decide_approval(
    id: str,
    decision_req: ApprovalDecisionRequest,
    current_user: User = Depends(require_scope("approval:decide")),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limit("approval_decision", current_user.id, max_requests=30, window_seconds=60)
    service = ApprovalService(db)
    result = await service.decide_and_execute(
        approval_id=id,
        decision=decision_req.decision,
        reviewer=current_user,
        comment=decision_req.comment,
    )
    approval = await db.get(Approval, id)
    if approval and result.get("status") in {"APPROVED", "REJECTED"}:
        conversation = await db.scalar(
            select(Conversation)
            .where(Conversation.ticket_id == approval.ticket_id)
            .order_by(Conversation.created_at.desc())
        )
        if conversation:
            outcome = result.get("message", "Your support request was reviewed.")
            content = f"Support team update (request {id[:8]}): {outcome}"
            existing = await db.scalar(
                select(Message.id).where(Message.conversation_id == conversation.id, Message.content == content)
            )
            if not existing:
                db.add(Message(conversation_id=conversation.id, actor_type="agent", actor_id=None, content=content))
                await AuditRepository(db).log_event(
                    request_id=str(uuid.uuid4()), actor_id=current_user.id, actor_type=current_user.role,
                    event_type="CUSTOMER_NOTIFIED_OF_REVIEW", resource_type="approval", resource_id=id,
                    ticket_id=approval.ticket_id, metadata={"decision": result.get("status")},
                )
    return result
