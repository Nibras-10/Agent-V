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
 )
from app.observability.logging import logger
from app.core.config import settings
from app.integrations.action_gateway import payment_gateway, subscription_gateway


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
        if txn:
            payload.expected_version = txn.version
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
        if sub:
            payload.expected_version = sub.version
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
        content_hash = compute_proposal_hash("contact_update", {"display_name": display_name, "phone": phone})
        idempotency_key = f"contact-update:{self.customer_id}:{content_hash}"
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
        """Reserve intent before provider call; commit DB result and execution record atomically."""
        approval = await self.approval_repo.get_approval(approval_id)
        if not approval or approval.status != "APPROVED":
            return ActionResult(success=False, action_type="refund", idempotency_key=f"refund-unapproved:{approval_id}", status="FAILED", message="Refund is not approved")
        proposal = approval.proposal
        if not proposal or proposal.type != "refund":
            return ActionResult(success=False, action_type="refund", idempotency_key=f"refund-no-proposal:{approval_id}", status="FAILED", message="Refund proposal is unavailable")
        if proposal.proposal_hash != compute_proposal_hash("refund", proposal.payload_json):
            return ActionResult(success=False, action_type="refund", idempotency_key=f"refund-tampered:{approval_id}", status="FAILED", message="Proposal integrity check failed")

        payload = RefundProposalPayload.model_validate(proposal.payload_json)
        if payload.customer_id != self.customer_id or payload.amount_minor <= 0:
            return ActionResult(success=False, action_type="refund", idempotency_key=f"refund-scope:{approval_id}", status="FAILED", message="Proposal customer or amount is invalid")
        idempotency_key = f"refund:{proposal.id}:{proposal.proposal_hash}"
        execution = await self.action_repo.get_by_proposal_id(proposal.id)
        if execution and execution.status == "SUCCESS":
            return ActionResult(success=True, action_type="refund", idempotency_key=idempotency_key, status="SUCCESS", message="Refund completed (recovered idempotent result)", data=execution.result_json)
        if execution and execution.status == "FAILED":
            return ActionResult(success=False, action_type="refund", idempotency_key=idempotency_key, status="FAILED", message="Refund execution was previously rejected")
        execution = execution or await self.action_repo.reserve_execution(proposal.id, idempotency_key)

        txn = await self.txn_repo.get_by_id(payload.transaction_id, for_update=True)
        if not txn or txn.customer_id != payload.customer_id or txn.customer_id != self.customer_id:
            return ActionResult(success=False, action_type="refund", idempotency_key=idempotency_key, status="FAILED", message="Transaction is unavailable for this customer")
        if txn.refundable_minor < payload.amount_minor or txn.currency.lower() != payload.currency.lower():
            return ActionResult(success=False, action_type="refund", idempotency_key=idempotency_key, status="FAILED", message="Refund amount or currency is no longer valid")
        if payload.expected_version is not None and txn.version != payload.expected_version:
            return ActionResult(success=False, action_type="refund", idempotency_key=idempotency_key, status="FAILED", message="Transaction changed after approval was requested")

        if settings.is_production and not txn.provider_ref:
            return ActionResult(success=False, action_type="refund", idempotency_key=idempotency_key, status="FAILED", message="Transaction is missing its payment processor reference")
        try:
            gateway_result = await payment_gateway.execute_refund(
                transaction_id=txn.provider_ref or payload.transaction_id,
                amount_minor=payload.amount_minor,
                currency=payload.currency,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            logger.error("Refund gateway outcome is uncertain", extra={"approval_id": approval_id, "error_type": type(exc).__name__})
            return ActionResult(success=False, action_type="refund", idempotency_key=idempotency_key, status="UNKNOWN", message="Refund result is being reconciled; retrying is safe.")

        try:
            updated = await self.txn_repo.apply_refund(
                transaction_id=payload.transaction_id,
                refund_amount_minor=payload.amount_minor,
                expected_version=payload.expected_version if payload.expected_version is not None else txn.version,
                commit=False,
            )
            if not updated:
                raise RuntimeError("Transaction disappeared during refund")
            provider_result = {key: gateway_result[key] for key in ("id", "refund_id", "status") if key in gateway_result}
            result_json = {"gateway_result": provider_result, "refunded_minor": payload.amount_minor, "remaining_refundable_minor": updated.refundable_minor, "new_version": updated.version}
            proposal.status = "EXECUTED"
            await self.action_repo.complete_execution(execution, result_json, "SUCCESS")
            await self.audit_repo.log_event(
                request_id=str(uuid.uuid4()), actor_id=approval.reviewer_id or self.actor_id,
                actor_type="reviewer", event_type="REFUND_EXECUTED",
                resource_type="transaction", resource_id=payload.transaction_id,
                ticket_id=approval.ticket_id,
                metadata={"amount_minor": payload.amount_minor, "idempotency_key": idempotency_key},
            )
        except Exception as exc:
            await self.db.rollback()
            logger.error("Refund database reconciliation failed", extra={"approval_id": approval_id, "error_type": type(exc).__name__})
            return ActionResult(success=False, action_type="refund", idempotency_key=idempotency_key, status="UNKNOWN", message="Refund result is being reconciled; retrying is safe.")

        return ActionResult(success=True, action_type="refund", idempotency_key=idempotency_key, status="SUCCESS", message=f"Refund of {payload.amount_minor / 100:.2f} USD executed successfully.", data=result_json)

    async def execute_approved_cancellation(self, approval_id: str) -> ActionResult:
        """Reserve intent before provider call; commit DB result and execution record atomically."""
        approval = await self.approval_repo.get_approval(approval_id)
        if not approval or approval.status != "APPROVED":
            return ActionResult(success=False, action_type="cancellation", idempotency_key=f"cancel-unapproved:{approval_id}", status="FAILED", message="Cancellation is not approved")
        proposal = approval.proposal
        if not proposal or proposal.type != "cancellation":
            return ActionResult(success=False, action_type="cancellation", idempotency_key=f"cancel-no-proposal:{approval_id}", status="FAILED", message="Cancellation proposal is unavailable")
        if proposal.proposal_hash != compute_proposal_hash("cancellation", proposal.payload_json):
            return ActionResult(success=False, action_type="cancellation", idempotency_key=f"cancel-tampered:{approval_id}", status="FAILED", message="Proposal integrity check failed")

        payload = CancellationProposalPayload.model_validate(proposal.payload_json)
        if payload.customer_id != self.customer_id:
            return ActionResult(success=False, action_type="cancellation", idempotency_key=f"cancel-scope:{approval_id}", status="FAILED", message="Proposal customer is invalid")
        idempotency_key = f"cancel:{proposal.id}:{proposal.proposal_hash}"
        execution = await self.action_repo.get_by_proposal_id(proposal.id)
        if execution and execution.status == "SUCCESS":
            return ActionResult(success=True, action_type="cancellation", idempotency_key=idempotency_key, status="SUCCESS", message="Cancellation completed (recovered idempotent result)", data=execution.result_json)
        if execution and execution.status == "FAILED":
            return ActionResult(success=False, action_type="cancellation", idempotency_key=idempotency_key, status="FAILED", message="Cancellation execution was previously rejected")
        execution = execution or await self.action_repo.reserve_execution(proposal.id, idempotency_key)

        sub = await self.sub_repo.get_by_id(payload.subscription_id, for_update=True)
        if not sub or sub.customer_id != payload.customer_id or sub.customer_id != self.customer_id or sub.status != "active":
            return ActionResult(success=False, action_type="cancellation", idempotency_key=idempotency_key, status="FAILED", message="Subscription is no longer eligible for cancellation")
        if payload.expected_version is not None and sub.version != payload.expected_version:
            return ActionResult(success=False, action_type="cancellation", idempotency_key=idempotency_key, status="FAILED", message="Subscription changed after approval was requested")

        if settings.is_production and not sub.provider_ref:
            return ActionResult(success=False, action_type="cancellation", idempotency_key=idempotency_key, status="FAILED", message="Subscription is missing its upstream processor reference")
        try:
            gateway_result = await subscription_gateway.cancel_subscription(
                subscription_id=sub.provider_ref or payload.subscription_id,
                cancel_at_period_end=payload.cancel_at_period_end,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            logger.error("Cancellation gateway outcome is uncertain", extra={"approval_id": approval_id, "error_type": type(exc).__name__})
            return ActionResult(success=False, action_type="cancellation", idempotency_key=idempotency_key, status="UNKNOWN", message="Cancellation result is being reconciled; retrying is safe.")

        try:
            updated = await self.sub_repo.cancel_subscription(
                subscription_id=payload.subscription_id,
                expected_version=payload.expected_version if payload.expected_version is not None else sub.version,
                commit=False,
            )
            if not updated:
                raise RuntimeError("Subscription disappeared during cancellation")
            provider_result = {key: gateway_result[key] for key in ("id", "cancellation_id", "status") if key in gateway_result}
            result_json = {"gateway_result": provider_result, "status": "canceled", "version": updated.version}
            proposal.status = "EXECUTED"
            await self.action_repo.complete_execution(execution, result_json, "SUCCESS")
            await self.audit_repo.log_event(
                request_id=str(uuid.uuid4()), actor_id=approval.reviewer_id or self.actor_id,
                actor_type="reviewer", event_type="SUBSCRIPTION_CANCELED",
                resource_type="subscription", resource_id=payload.subscription_id,
                ticket_id=approval.ticket_id, metadata={"idempotency_key": idempotency_key},
            )
        except Exception as exc:
            await self.db.rollback()
            logger.error("Cancellation database reconciliation failed", extra={"approval_id": approval_id, "error_type": type(exc).__name__})
            return ActionResult(success=False, action_type="cancellation", idempotency_key=idempotency_key, status="UNKNOWN", message="Cancellation result is being reconciled; retrying is safe.")

        return ActionResult(success=True, action_type="cancellation", idempotency_key=idempotency_key, status="SUCCESS", message="Subscription canceled successfully.", data=result_json)

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
