from typing import Optional
from app.models.entities import Subscription
from app.schemas.actions import PolicyDecision, CancellationProposalPayload


class CancellationPolicy:
    @staticmethod
    def evaluate(
        customer_id: str,
        subscription: Optional[Subscription],
        proposal: CancellationProposalPayload,
    ) -> PolicyDecision:
        if not subscription:
            return PolicyDecision(
                allowed=False,
                approval_required=False,
                risk="HIGH",
                reason_codes=["SUBSCRIPTION_NOT_FOUND"],
                details={"error": "Subscription ID does not exist."},
            )

        if subscription.customer_id != customer_id:
            return PolicyDecision(
                allowed=False,
                approval_required=False,
                risk="HIGH",
                reason_codes=["CUSTOMER_MISMATCH", "UNAUTHORIZED"],
                details={"error": "Subscription does not belong to the authenticated customer."},
            )

        if subscription.status != "active":
            return PolicyDecision(
                allowed=False,
                approval_required=False,
                risk="HIGH",
                reason_codes=["SUBSCRIPTION_NOT_ACTIVE"],
                details={"status": subscription.status},
            )

        return PolicyDecision(
            allowed=True,
            approval_required=True,  # Cancellations are high-risk: human approval required
            risk="HIGH",
            reason_codes=["ELIGIBLE_FOR_CANCELLATION_REVIEW"],
            details={
                "subscription_id": subscription.id,
                "plan": subscription.plan,
                "version": subscription.version,
            },
        )
