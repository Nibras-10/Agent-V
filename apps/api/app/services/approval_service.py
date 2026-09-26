import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.entities import Approval, User
from app.repositories.approval_repo import ApprovalRepository
from app.repositories.ticket_repo import TicketRepository
from app.repositories.transaction_repo import TransactionRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.audit_repo import AuditRepository
from app.tools.action_tools import ActionTools
from app.schemas.actions import compute_proposal_hash, ActionResult
from app.observability.logging import logger
from app.agents.graph import build_support_graph
from langgraph.types import Command


class ApprovalService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.approval_repo = ApprovalRepository(db)
        self.ticket_repo = TicketRepository(db)
        self.txn_repo = TransactionRepository(db)
        self.sub_repo = SubscriptionRepository(db)
        self.audit_repo = AuditRepository(db)

    async def decide_and_execute(
        self,
        approval_id: str,
        decision: str,  # "APPROVE" or "REJECT"
        reviewer: User,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        approval = await self.approval_repo.get_approval(approval_id)
        if not approval:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")

        # 1. Verify not expired
        now = datetime.now(timezone.utc)
        expires_at = approval.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            await self.approval_repo.decide_approval(approval_id, "EXPIRED", reviewer.id, "Approval window expired")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Approval request has expired")

        if approval.status != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Approval has already been resolved with status: {approval.status}",
            )

        # 2. Check if customer is attempting to approve their own request (Strict prohibition)
        ticket = await self.ticket_repo.get_by_id(approval.ticket_id, load_conversations=False)
        if ticket and reviewer.customer_id == ticket.customer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Security violation: Customers cannot approve their own high-risk actions",
            )

        proposal = approval.proposal
        if not proposal:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Proposal associated with approval not found")

        # 3. Verify proposal canonical hash
        canonical_hash = compute_proposal_hash(proposal.type, proposal.payload_json)
        if proposal.proposal_hash != canonical_hash:
            await self.audit_repo.log_event(
                request_id=str(uuid.uuid4()),
                actor_id=reviewer.id,
                actor_type="reviewer",
                event_type="APPROVAL_TAMPERING_DETECTED",
                resource_type="action_proposal",
                resource_id=proposal.id,
                ticket_id=approval.ticket_id,
                metadata={"reason": "Proposal hash mismatch"},
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Proposal integrity check failed")

        if decision == "REJECT":
            updated = await self.approval_repo.decide_approval(approval_id, "REJECTED", reviewer.id, comment)
            await self.ticket_repo.update_status(approval.ticket_id, "resolved")
            await self.audit_repo.log_event(
                request_id=str(uuid.uuid4()),
                actor_id=reviewer.id,
                actor_type="reviewer",
                event_type="PROPOSAL_REJECTED",
                resource_type="approval",
                resource_id=approval_id,
                ticket_id=approval.ticket_id,
                metadata={"comment": comment},
            )
            graph = build_support_graph(self.db)
            await graph.ainvoke(
                Command(resume={"decision": "REJECT", "reviewer_id": reviewer.id}),
                config={"configurable": {"thread_id": f"thread_{proposal.run_id}"}},
            )
            return {"status": "REJECTED", "message": "Proposal was rejected by reviewer", "approval": updated}

        # If decision is APPROVE:
        # 4. Revalidate customer ownership, transaction/subscription version/status and policy
        if proposal.type == "refund":
            txn_id = proposal.payload_json["transaction_id"]
            txn = await self.txn_repo.get_by_id(txn_id)
            if not txn:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transaction no longer exists")
            if txn.customer_id != ticket.customer_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Transaction customer mismatch")
            if txn.refundable_minor < proposal.payload_json["amount_minor"]:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transaction balance no longer sufficient")

        elif proposal.type == "cancellation":
            sub_id = proposal.payload_json["subscription_id"]
            sub = await self.sub_repo.get_by_id(sub_id)
            if not sub or sub.status != "active":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Subscription is no longer active")
            if sub.customer_id != ticket.customer_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Subscription customer mismatch")

        # Claim the approval atomically after all pre-execution checks.
        claimed = await self.approval_repo.claim_for_approval(approval_id, reviewer.id, comment)
        if not claimed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Approval was already resolved or expired",
            )

        graph = build_support_graph(self.db)
        final_state = await graph.ainvoke(
            Command(resume={"decision": "APPROVE", "reviewer_id": reviewer.id}),
            config={"configurable": {"thread_id": f"thread_{proposal.run_id}"}},
        )
        action_result = final_state.get("action_result") or {}
        exec_success = action_result.get("success", action_result.get("status") == "SUCCESS")

        if exec_success:
            await self.ticket_repo.update_status(approval.ticket_id, "resolved")
        else:
            await self.ticket_repo.update_status(approval.ticket_id, "failed")

        return {
            "status": "APPROVED",
            "message": action_result.get("message", "Approval resumed through the workflow"),
            "action_result": action_result,
        }
