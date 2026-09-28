import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.models.entities import Approval, User, AgentRun
from app.repositories.approval_repo import ApprovalRepository
from app.repositories.action_repo import ActionRepository
from app.repositories.ticket_repo import TicketRepository
from app.repositories.transaction_repo import TransactionRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.audit_repo import AuditRepository
from app.tools.action_tools import ActionTools
from app.schemas.actions import compute_proposal_hash, RefundProposalPayload, CancellationProposalPayload
from app.policies.refund_policy import RefundPolicy
from app.policies.cancellation_policy import CancellationPolicy
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
        self.action_repo = ActionRepository(db)

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
        retrying_approved = approval.status == "APPROVED" and approval.reviewer_id == reviewer.id
        if not retrying_approved and expires_at < now:
            await self.approval_repo.decide_approval(approval_id, "EXPIRED", reviewer.id, "Approval window expired")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Approval request has expired")

        if approval.status != "PENDING" and not retrying_approved:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Approval has already been resolved with status: {approval.status}",
            )

        # 2. Check if customer is attempting to approve their own request (Strict prohibition)
        ticket = await self.ticket_repo.get_by_id(approval.ticket_id, load_conversations=False)
        if not ticket:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval ticket not found")
        if reviewer.role not in {"reviewer", "admin"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only reviewers and administrators can decide approvals")
        if reviewer.customer_id and reviewer.customer_id == ticket.customer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Security violation: Customers cannot approve their own high-risk actions",
            )

        proposal = approval.proposal
        if not proposal:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Proposal associated with approval not found")
        run = await self.db.get(AgentRun, proposal.run_id)
        if not run or run.ticket_id != approval.ticket_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Approval is not bound to its originating ticket")

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

        if decision == "APPROVE" and retrying_approved:
            completed_action = await self.action_repo.get_by_proposal_id(proposal.id)
            if completed_action and completed_action.status == "SUCCESS":
                await self.ticket_repo.update_status(ticket.id, "resolved")
                run.graph_status = "COMPLETED"
                run.ended_at = datetime.now(timezone.utc)
                await self.db.commit()
                return {"status": "APPROVED", "message": "Action already completed", "action_result": completed_action.result_json}

        if decision == "REJECT":
            updated = await self.approval_repo.claim_decision(approval_id, "REJECTED", reviewer.id, comment)
            if not updated:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval was already decided or expired")
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
            if txn.customer_id != ticket.customer_id or proposal.payload_json.get("customer_id") != ticket.customer_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Transaction customer mismatch")
            if proposal.payload_json.get("expected_version") is not None and txn.version != proposal.payload_json["expected_version"]:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transaction changed after proposal creation")
            payload = RefundProposalPayload.model_validate(proposal.payload_json)
            decision_check = RefundPolicy.evaluate(ticket.customer_id, txn, payload)
            if not decision_check.allowed:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Refund proposal no longer passes current policy")

        elif proposal.type == "cancellation":
            sub_id = proposal.payload_json["subscription_id"]
            sub = await self.sub_repo.get_by_id(sub_id)
            if not sub or sub.status != "active":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Subscription is no longer active")
            if sub.customer_id != ticket.customer_id or proposal.payload_json.get("customer_id") != ticket.customer_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Subscription customer mismatch")
            if proposal.payload_json.get("expected_version") is not None and sub.version != proposal.payload_json["expected_version"]:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Subscription changed after proposal creation")
            payload = CancellationProposalPayload.model_validate(proposal.payload_json)
            decision_check = CancellationPolicy.evaluate(ticket.customer_id, sub, payload)
            if not decision_check.allowed:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cancellation proposal no longer passes current policy")

        # Claims are atomic. A retry is allowed only for the reviewer who made the decision.
        if retrying_approved:
            existing_action = await self.action_repo.get_by_proposal_id(proposal.id)
            if existing_action and existing_action.status == "PENDING":
                # The prior graph resume may have ended after an uncertain provider response.
                # Re-enter the idempotent executor directly using the same durable proposal key.
                tools = ActionTools(self.db, reviewer.id, ticket.customer_id, ticket.id, run.id)
                if proposal.type == "refund":
                    recovered = await tools.execute_approved_refund(approval_id)
                elif proposal.type == "cancellation":
                    recovered = await tools.execute_approved_cancellation(approval_id)
                else:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported recovery action")
                if recovered.success:
                    await self.ticket_repo.update_status(ticket.id, "resolved")
                    run.graph_status = "COMPLETED"
                    run.ended_at = datetime.now(timezone.utc)
                    await self.db.commit()
                else:
                    await self.ticket_repo.update_status(ticket.id, "action_reconciliation")
                    run.graph_status = "ACTION_RECONCILIATION"
                    await self.db.commit()
                return {"status": "APPROVED", "message": recovered.message, "action_result": recovered.model_dump()}
        else:
            claimed = await self.approval_repo.claim_for_approval(approval_id, reviewer.id, comment)
            if not claimed:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval was already resolved or expired")

        graph = build_support_graph(self.db)
        final_state = await graph.ainvoke(
            Command(resume={"decision": "APPROVE", "reviewer_id": reviewer.id}),
            config={"configurable": {"thread_id": f"thread_{proposal.run_id}"}},
        )
        action_result = final_state.get("action_result") or {}
        exec_success = action_result.get("success", action_result.get("status") == "SUCCESS")

        if exec_success:
            await self.ticket_repo.update_status(approval.ticket_id, "resolved")
            run.graph_status = "COMPLETED"
            run.ended_at = datetime.now(timezone.utc)
            await self.db.commit()
        elif action_result.get("status") == "UNKNOWN":
            await self.ticket_repo.update_status(approval.ticket_id, "action_reconciliation")
            run.graph_status = "ACTION_RECONCILIATION"
            await self.db.commit()
        elif action_result.get("status") == "FAILED":
            await self.ticket_repo.update_status(approval.ticket_id, "failed")
            run.graph_status = "FAILED"
            run.ended_at = datetime.now(timezone.utc)
            await self.db.commit()

        return {
            "status": "APPROVED",
            "message": action_result.get("message", "Approval resumed through the workflow"),
            "action_result": action_result,
        }
