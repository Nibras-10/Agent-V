from typing import Optional
from app.models.entities import Transaction
from app.schemas.actions import PolicyDecision, RefundProposalPayload


class RefundPolicy:
    @staticmethod
    def evaluate(
        customer_id: str,
        transaction: Optional[Transaction],
        proposal: RefundProposalPayload,
    ) -> PolicyDecision:
        reasons = []

        if not transaction:
            return PolicyDecision(
                allowed=False,
                approval_required=False,
                risk="HIGH",
                reason_codes=["TRANSACTION_NOT_FOUND"],
                details={"error": "Transaction ID does not exist."},
            )

        # 1. Verify customer owns transaction
        if transaction.customer_id != customer_id:
            return PolicyDecision(
                allowed=False,
                approval_required=False,
                risk="HIGH",
                reason_codes=["CUSTOMER_MISMATCH", "UNAUTHORIZED"],
                details={"error": "Transaction does not belong to the authenticated customer."},
            )

        # 2. Transaction must be settled
        if transaction.status != "setted" and transaction.status != "settled":
            reasons.append("TRANSACTION_NOT_SETTLED")

        # 3. Amount > 0
        if proposal.amount_minor <= 0:
            reasons.append("INVALID_REFUND_AMOUNT")

        # 4. Requested amount <= refundable amount
        if proposal.amount_minor > transaction.refundable_minor:
            reasons.append("AMOUNT_EXCEEDS_REFUNDABLE_BALANCE")

        # 5. Currency matches
        if proposal.currency.upper() != transaction.currency.upper():
            reasons.append("CURRENCY_MISMATCH")

        if reasons:
            return PolicyDecision(
                allowed=False,
                approval_required=False,
                risk="HIGH",
                reason_codes=reasons,
                details={
                    "refundable_minor": transaction.refundable_minor,
                    "requested_minor": proposal.amount_minor,
                    "currency": transaction.currency,
                },
            )

        # 6. Policy decision for valid refund
        return PolicyDecision(
            allowed=True,
            approval_required=True,  # High risk: requires human approval by default
            risk="HIGH",
            reason_codes=["ELIGIBLE_FOR_REVIEW"],
            details={
                "transaction_id": transaction.id,
                "amount_minor": proposal.amount_minor,
                "currency": transaction.currency,
                "version": transaction.version,
            },
        )
