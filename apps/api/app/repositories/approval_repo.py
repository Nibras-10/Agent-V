from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from app.models.entities import ActionProposal, Approval
from app.schemas.actions import compute_proposal_hash
from app.core.config import settings


class ApprovalRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_proposal(
        self,
        run_id: str,
        action_type: str,
        payload_json: Dict[str, Any],
        risk_level: str = "HIGH",
    ) -> ActionProposal:
        proposal_hash = compute_proposal_hash(action_type, payload_json)
        proposal = ActionProposal(
            run_id=run_id,
            type=action_type,
            payload_json=payload_json,
            risk_level=risk_level,
            proposal_hash=proposal_hash,
            status="PENDING",
        )
        self.db.add(proposal)
        await self.db.commit()
        await self.db.refresh(proposal)
        return proposal

    async def get_proposal(self, proposal_id: str) -> Optional[ActionProposal]:
        stmt = (
            select(ActionProposal)
            .where(ActionProposal.id == proposal_id)
            .options(selectinload(ActionProposal.approval), selectinload(ActionProposal.executed_action))
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def create_approval(self, proposal_id: str, ticket_id: str) -> Approval:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.APPROVAL_EXPIRY_MINUTES)
        approval = Approval(
            proposal_id=proposal_id,
            ticket_id=ticket_id,
            status="PENDING",
            expires_at=expires_at,
        )
        self.db.add(approval)
        await self.db.commit()
        await self.db.refresh(approval)
        return approval

    async def get_approval(self, approval_id: str) -> Optional[Approval]:
        stmt = (
            select(Approval)
            .where(Approval.id == approval_id)
            .options(selectinload(Approval.proposal), selectinload(Approval.reviewer))
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_pending_approvals(self) -> List[Approval]:
        stmt = (
            select(Approval)
            .where(Approval.status == "PENDING")
            .options(selectinload(Approval.proposal))
            .order_by(Approval.created_at.desc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def list_all_approvals(self, limit: int = 50) -> List[Approval]:
        stmt = (
            select(Approval)
            .options(selectinload(Approval.proposal))
            .order_by(Approval.created_at.desc())
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def decide_approval(
        self,
        approval_id: str,
        decision: str,  # APPROVED or REJECTED
        reviewer_id: str,
        comment: Optional[str] = None,
    ) -> Optional[Approval]:
        approval = await self.get_approval(approval_id)
        if not approval:
            return None

        # Check expiration
        now = datetime.now(timezone.utc)
        expires_at = approval.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            approval.status = "EXPIRED"
            if approval.proposal:
                approval.proposal.status = "EXPIRED"
            await self.db.commit()
            await self.db.refresh(approval)
            return approval

        if approval.status != "PENDING":
            return approval

        approval.status = decision
        approval.reviewer_id = reviewer_id
        approval.comment = comment
        approval.decided_at = now

        if approval.proposal:
            approval.proposal.status = decision

        await self.db.commit()
        await self.db.refresh(approval)
        return approval

    async def claim_decision(
        self,
        approval_id: str,
        decision: str,
        reviewer_id: str,
        comment: Optional[str] = None,
    ) -> Optional[Approval]:
        """Compare-and-set a single reviewer decision and proposal status in one transaction."""
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("Unsupported approval decision")
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(Approval)
            .where(
                Approval.id == approval_id,
                Approval.status == "PENDING",
                Approval.expires_at >= now,
            )
            .values(
                status=decision,
                reviewer_id=reviewer_id,
                comment=comment,
                decided_at=now,
            )
        )
        if result.rowcount != 1:
            await self.db.rollback()
            return None
        approval = await self.get_approval(approval_id)
        if approval and approval.proposal:
            approval.proposal.status = decision
        await self.db.commit()
        if approval:
            await self.db.refresh(approval)
        return approval

    async def claim_for_approval(
        self,
        approval_id: str,
        reviewer_id: str,
        comment: Optional[str] = None,
    ) -> Optional[Approval]:
        return await self.claim_decision(approval_id, "APPROVED", reviewer_id, comment)
