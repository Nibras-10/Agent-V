import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ActionProposal, Approval
from app.repositories.customer_repo import CustomerRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.transaction_repo import TransactionRepository
from app.repositories.approval_repo import ApprovalRepository
from app.repositories.action_repo import ActionRepository
from app.repositories.audit_repo import AuditRepository
from app.repositories.handoff_repo import HandoffRepository
from app.policies.refund_policy import RefundPolicy
from app.policies.cancellation_policy import CancellationPolicy
from app.policies.contact_policy import ContactPolicy
from app.schemas.actions import (
    RefundProposalPayload,
    CancellationProposalPayload,
    ContactUpdatePayload,
    compute_proposal_hash,
    ActionResult,
)
from app.integrations.mock_services import (
    crm_service,
    email_service,
    payment_gateway,
    subscription_gateway,
)
from app.observability.logging import logger


class ActionTools:
    def __init__(
        self,
        db: AsyncSession,
        authenticated_actor_id: str,
        authenticated_customer_id: str,
        ticket_id: str,
        run_id: str,
    ):
        self.db = db
        self.actor_id = authenticated_actor_id
        self.customer_id = authenticated_customer_id
        self.ticket_id = ticket_id
        self.run_id = run_id

        self.customer_repo = CustomerRepository(db)
        self.sub_repo = SubscriptionRepository(db)
        self.txn_repo = TransactionRepository(db)
        self.approval_repo = ApprovalRepository(db)
        self.action_repo = ActionRepository(db)
        self.audit_repo = AuditRepository(db)
        self.handoff_repo = HandoffRepository(db)

    # --- Proposal Tools ---
    async def create_refund_proposal(
        self,
        transaction_id: str,
        amount_minor: int,
        reason: str,
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """Propose a refund. Evaluates deterministic refund policy first."""
        payload = RefundProposalPayload(
            transaction_id=transaction_id,
            customer_id=self.customer_id,
            amount_minor=amount_minor,
            currency=currency,
            reason=reason,
        )

        txn = await self.txn_repo.get_by_id(transaction_id)
        decision = RefundPolicy.evaluate(self.customer_id, txn, payload)

        if not decision.allowed:
            return {
                "success": False,
                "status": "DENIED_BY_POLICY",
                "reason_codes": decision.reason_codes,
                "details": decision.details,
            }

        # Persist action proposal
        proposal = await self.approval_repo.create_proposal(
            run_id=self.run_id,
            action_type="refund",
            payload_json=payload.model_dump(),
            risk_level="HIGH",
        )

        # Create approval record for reviewer UI
        approval = await self.approval_repo.create_approval(
            proposal_id=proposal.id,
            ticket_id=self.ticket_id,
        )

        await self.audit_repo.log_event(
            request_id=str(uuid.uuid4()),
            actor_id=self.actor_id,
            actor_type="agent",
            event_type="PROPOSAL_CREATED",
            resource_type="action_proposal",
            resource_id=proposal.id,
            ticket_id=self.ticket_id,
            metadata={"type": "refund", "amount_minor": amount_minor, "approval_id": approval.id},
        )

        return {
            "success": True,
            "status": "PROPOSED",
            "proposal_id": proposal.id,
            "approval_id": approval.id,
            "proposal_hash": proposal.proposal_hash,
            "approval_required": True,
        }

    async def create_cancellation_proposal(
        self,
        subscription_id: str,
        reason: str,
        cancel_at_period_end: bool = True,
    ) -> Dict[str, Any]:
        payload = CancellationProposalPayload(
            subscription_id=subscription_id,
            customer_id=self.customer_id,
            reason=reason,
            cancel_at_period_end=cancel_at_period_end,
        )

        sub = await self.sub_repo.get_by_id(subscription_id)
        decision = CancellationPolicy.evaluate(self.customer_id, sub, payload)

        if not decision.allowed:
            return {
                "success": False,
                "status": "DENIED_BY_POLICY",
                "reason_codes": decision.reason_codes,
                "details": decision.details,
            }

        proposal = await self.approval_repo.create_proposal(
            run_id=self.run_id,
            action_type="cancellation",
            payload_json=payload.model_dump(),
            risk_level="HIGH",
        )

        approval = await self.approval_repo.create_approval(
            proposal_id=proposal.id,
            ticket_id=self.ticket_id,
        )

        await self.audit_repo.log_event(
            request_id=str(uuid.uuid4()),
            actor_id=self.actor_id,
            actor_type="agent",
            event_type="PROPOSAL_CREATED",
            resource_type="action_proposal",
            resource_id=proposal.id,
            ticket_id=self.ticket_id,
            metadata={"type": "cancellation", "subscription_id": subscription_id, "approval_id": approval.id},
        )

        return {
            "success": True,
            "status": "PROPOSED",
            "proposal_id": proposal.id,
            "approval_id": approval.id,
            "proposal_hash": proposal.proposal_hash,
            "approval_required": True,
        }

    # --- Write / Execution Tools ---
    async def update_contact_details(
        self,
        display_name: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> ActionResult:
        """Low-risk execution tool for allow-listed profile fields."""
        idempotency_key = f"contact-update:{self.customer_id}:{display_name}:{phone}"
        existing_action = await self.action_repo.get_by_idempotency_key(idempotency_key)
        if existing_action:
            return ActionResult(
                success=True,
                action_type="contact_update",
                idempotency_key=idempotency_key,
                status="SUCCESS",
                message="Contact details updated (idempotent replay)",
                data=existing_action.result_json,
            )

        payload = ContactUpdatePayload(customer_id=self.customer_id, display_name=display_name, phone=phone)
        customer = await self.customer_repo.get_by_id(self.customer_id)
        decision = ContactPolicy.evaluate(self.customer_id, customer, payload)

        if not decision.allowed:
            return ActionResult(
                success=False,
                action_type="contact_update",
                idempotency_key=idempotency_key,
                status="FAILED",
                message=f"Denied by policy: {decision.reason_codes}",
            )

        updated = await self.customer_repo.update_contact(self.customer_id, display_name=display_name, phone=phone)
        res_data = {"display_name": updated.display_name, "phone": updated.phone}

        # Log low risk audit
        await self.audit_repo.log_event(
            request_id=str(uuid.uuid4()),
            actor_id=self.actor_id,
            actor_type="agent",
            event_type="CONTACT_UPDATED",
            resource_type="customer",
            resource_id=self.customer_id,
            ticket_id=self.ticket_id,
            metadata=res_data,
        )

        return ActionResult(
            success=True,
            action_type="contact_update",
            idempotency_key=idempotency_key,
            status="SUCCESS",
            message="Contact details updated successfully.",
            data=res_data,
        )

    async def execute_approved_refund(self, approval_id: str) -> ActionResult:
        """Execute high-risk refund after strict verification and version revalidation."""
        approval = await self.approval_repo.get_approval(approval_id)
        if not approval:
            return ActionResult(
                success=False,
                action_type="refund",
                idempotency_key=f"ref-unknown:{approval_id}",
                status="FAILED",
                message="Approval record not found",
            )

        if approval.status != "APPROVED":
            return ActionResult(
                success=False,
                action_type="refund",
                idempotency_key=f"ref-unapproved:{approval_id}",
                status="FAILED",
                message=f"Action not approved. Current status: {approval.status}",
            )

        proposal = approval.proposal
        if not proposal:
            return ActionResult(
                success=False,
                action_type="refund",
                idempotency_key=f"ref-noproposal:{approval_id}",
                status="FAILED",
                message="Associated proposal not found",
            )

        # Re-verify canonical hash to prevent proposal tampering
        expected_hash = compute_proposal_hash("refund", proposal.payload_json)
        if proposal.proposal_hash != expected_hash:
            return ActionResult(
                success=False,
                action_type="refund",
                idempotency_key=f"ref-hash-mismatch:{approval_id}",
                status="FAILED",
                message="Security violation: Proposal hash mismatch",
            )

        idempotency_key = f"refund:{proposal.id}:{proposal.proposal_hash}"
        # Check idempotency
        existing_exec = await self.action_repo.get_by_idempotency_key(idempotency_key)
        if existing_exec:
            return ActionResult(
                success=True,
                action_type="refund",
                idempotency_key=idempotency_key,
                status="SUCCESS",
                message="Refund executed (idempotent result)",
                data=existing_exec.result_json,
            )

        # Revalidate database state & version
        txn_id = proposal.payload_json["transaction_id"]
        amount_minor = proposal.payload_json["amount_minor"]
        currency = proposal.payload_json.get("currency", "USD")

        txn = await self.txn_repo.get_by_id(txn_id)
        if not txn:
            return ActionResult(
                success=False,
                action_type="refund",
                idempotency_key=idempotency_key,
                status="FAILED",
                message="Transaction no longer exists",
            )

        # Execute refund on mock payment gateway
        gateway_res = await payment_gateway.execute_refund(
            transaction_id=txn_id,
            amount_minor=amount_minor,
            currency=currency,
            idempotency_key=idempotency_key,
        )

        # Apply DB update with optimistic lock
        try:
            updated_txn = await self.txn_repo.apply_refund(
                transaction_id=txn_id,
                refund_amount_minor=amount_minor,
                expected_version=txn.version,
            )
        except Exception as e:
            logger.error(f"Error applying refund to DB: {e}")
            return ActionResult(
                success=False,
                action_type="refund",
                idempotency_key=idempotency_key,
                status="UNKNOWN",
                message=f"Payment processed at gateway but DB update failed: {e}",
            )

        proposal.status = "EXECUTED"
        await self.db.commit()

        # Record executed action
        result_json = {
            "gateway_result": gateway_res,
            "refunded_minor": amount_minor,
            "remaining_refundable_minor": updated_txn.refundable_minor,
            "new_version": updated_txn.version,
        }
        await self.action_repo.record_execution(
            proposal_id=proposal.id,
            idempotency_key=idempotency_key,
            result_json=result_json,
            status="SUCCESS",
        )

        # Audit event
        await self.audit_repo.log_event(
            request_id=str(uuid.uuid4()),
            actor_id=approval.reviewer_id or self.actor_id,
            actor_type="reviewer",
            event_type="REFUND_EXECUTED",
            resource_type="transaction",
            resource_id=txn_id,
            ticket_id=self.ticket_id,
            metadata={"amount_minor": amount_minor, "idempotency_key": idempotency_key},
        )

        return ActionResult(
            success=True,
            action_type="refund",
            idempotency_key=idempotency_key,
            status="SUCCESS",
            message=f"Refund of ${amount_minor / 100:.2f} executed successfully.",
            data=result_json,
        )

    async def execute_approved_cancellation(self, approval_id: str) -> ActionResult:
        """Execute high-risk subscription cancellation after verification."""
        approval = await self.approval_repo.get_approval(approval_id)
        if not approval or approval.status != "APPROVED":
            return ActionResult(
                success=False,
                action_type="cancellation",
                idempotency_key=f"cancel-unapproved:{approval_id}",
                status="FAILED",
                message="Cancellation not approved",
            )

        proposal = approval.proposal
        if not proposal:
            return ActionResult(
                success=False,
                action_type="cancellation",
                idempotency_key=f"cancel-noproposal:{approval_id}",
                status="FAILED",
                message="Associated proposal not found",
            )

        expected_hash = compute_proposal_hash("cancellation", proposal.payload_json)
        if proposal.proposal_hash != expected_hash:
            return ActionResult(
                success=False,
                action_type="cancellation",
                idempotency_key=f"cancel-hash-mismatch:{approval_id}",
                status="FAILED",
                message="Security violation: Proposal hash mismatch",
            )

        idempotency_key = f"cancel:{proposal.id}:{proposal.proposal_hash}"
        existing_exec = await self.action_repo.get_by_idempotency_key(idempotency_key)
        if existing_exec:
            return ActionResult(
                success=True,
                action_type="cancellation",
                idempotency_key=idempotency_key,
                status="SUCCESS",
                message="Cancellation executed (idempotent result)",
                data=existing_exec.result_json,
            )

        sub_id = proposal.payload_json["subscription_id"]
        sub = await self.sub_repo.get_by_id(sub_id)
        if not sub or sub.status != "active":
            return ActionResult(
                success=False,
                action_type="cancellation",
                idempotency_key=idempotency_key,
                status="FAILED",
                message="Subscription is no longer active",
            )

        gateway_res = await subscription_gateway.cancel_subscription(
            subscription_id=sub_id,
            cancel_at_period_end=proposal.payload_json.get("cancel_at_period_end", True),
            idempotency_key=idempotency_key,
        )

        updated_sub = await self.sub_repo.cancel_subscription(
            subscription_id=sub_id,
            expected_version=sub.version,
        )

        proposal.status = "EXECUTED"
        await self.db.commit()

        result_json = {"gateway_result": gateway_res, "status": "canceled", "version": updated_sub.version}
        await self.action_repo.record_execution(
            proposal_id=proposal.id,
            idempotency_key=idempotency_key,
            result_json=result_json,
            status="SUCCESS",
        )

        await self.audit_repo.log_event(
            request_id=str(uuid.uuid4()),
            actor_id=approval.reviewer_id or self.actor_id,
            actor_type="reviewer",
            event_type="SUBSCRIPTION_CANCELED",
            resource_type="subscription",
            resource_id=sub_id,
            ticket_id=self.ticket_id,
            metadata={"idempotency_key": idempotency_key},
        )

        return ActionResult(
            success=True,
            action_type="cancellation",
            idempotency_key=idempotency_key,
            status="SUCCESS",
            message="Subscription canceled successfully.",
            data=result_json,
        )

    async def add_crm_note(self, note: str) -> Dict[str, Any]:
        return await crm_service.add_note(self.customer_id, self.ticket_id, note)

    async def send_email(self, to_email: str, template_name: str, vars: Dict[str, Any]) -> Dict[str, Any]:
        # Only allow email to customer's authoritative email
        cust = await self.customer_repo.get_by_id(self.customer_id)
        if not cust or cust.email.lower() != to_email.lower():
            raise ValueError("Email recipient does not match customer's verified email address")
        return await email_service.send_email(to_email, template_name, vars)

    async def enqueue_human_handoff(self, reason_code: str, summary: str) -> Dict[str, Any]:
        item = await self.handoff_repo.enqueue(self.ticket_id, reason_code, summary)
        await self.audit_repo.log_event(
            request_id=str(uuid.uuid4()),
            actor_id=self.actor_id,
            actor_type="system",
            event_type="HANDOFF_ENQUEUED",
            resource_type="human_queue",
            resource_id=item.id,
            ticket_id=self.ticket_id,
            metadata={"reason_code": reason_code, "summary": summary},
        )
        return {"id": item.id, "reason_code": reason_code, "status": "QUEUED"}
