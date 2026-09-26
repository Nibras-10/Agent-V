import uuid
from typing import Dict, Any, Optional
from app.observability.logging import logger


class MockCRMService:
    def __init__(self):
        self.notes: list[dict[str, Any]] = []

    async def add_note(self, customer_id: str, ticket_id: str, note: str) -> Dict[str, Any]:
        entry = {
            "id": f"crm-note-{uuid.uuid4().hex[:8]}",
            "customer_id": customer_id,
            "ticket_id": ticket_id,
            "note": note,
            "status": "SAVED",
        }
        self.notes.append(entry)
        logger.info(f"Mock CRM note added for ticket {ticket_id}")
        return entry


class MockEmailService:
    def __init__(self):
        self.sent_emails: list[dict[str, Any]] = []

    async def send_email(
        self,
        to_email: str,
        template_name: str,
        template_vars: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Strict security: enforce email format and allowlist template
        if template_name not in ["refund_confirmation", "cancellation_notice", "support_update"]:
            raise ValueError(f"Invalid email template: {template_name}")

        record = {
            "email_id": f"email-{uuid.uuid4().hex[:8]}",
            "to": to_email,
            "template": template_name,
            "vars": template_vars,
            "status": "SENT",
        }
        self.sent_emails.append(record)
        logger.info(f"Mock email sent to {to_email} using {template_name}")
        return record


class MockPaymentGateway:
    def __init__(self):
        self.refunds: list[dict[str, Any]] = []

    async def execute_refund(
        self,
        transaction_id: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        # Gateway simulation
        record = {
            "refund_id": f"ref_{uuid.uuid4().hex[:12]}",
            "transaction_id": transaction_id,
            "amount_minor": amount_minor,
            "currency": currency,
            "idempotency_key": idempotency_key,
            "status": "SUCCEEDED",
        }
        self.refunds.append(record)
        logger.info(f"Mock Payment Gateway processed refund: {record['refund_id']}")
        return record


class MockSubscriptionGateway:
    def __init__(self):
        self.cancellations: list[dict[str, Any]] = []

    async def cancel_subscription(
        self,
        subscription_id: str,
        cancel_at_period_end: bool,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        record = {
            "cancellation_id": f"sub_cancel_{uuid.uuid4().hex[:10]}",
            "subscription_id": subscription_id,
            "cancel_at_period_end": cancel_at_period_end,
            "idempotency_key": idempotency_key,
            "status": "PROCESSED",
        }
        self.cancellations.append(record)
        logger.info(f"Mock Subscription Gateway processed cancellation: {record['cancellation_id']}")
        return record


# Global instances for in-memory testing & dev
crm_service = MockCRMService()
email_service = MockEmailService()
payment_gateway = MockPaymentGateway()
subscription_gateway = MockSubscriptionGateway()
