from typing import Optional
from app.models.entities import Customer
from app.schemas.actions import PolicyDecision, ContactUpdatePayload


class ContactPolicy:
    @staticmethod
    def evaluate(
        customer_id: str,
        customer: Optional[Customer],
        payload: ContactUpdatePayload,
    ) -> PolicyDecision:
        if not customer:
            return PolicyDecision(
                allowed=False,
                approval_required=False,
                risk="LOW",
                reason_codes=["CUSTOMER_NOT_FOUND"],
            )

        if customer.id != customer_id:
            return PolicyDecision(
                allowed=False,
                approval_required=False,
                risk="HIGH",
                reason_codes=["CUSTOMER_MISMATCH", "UNAUTHORIZED"],
            )

        # Allow-listed fields only: display_name, phone.
        # Email and billing sensitive fields cannot be updated here!
        if payload.display_name is None and payload.phone is None:
            return PolicyDecision(
                allowed=False,
                approval_required=False,
                risk="LOW",
                reason_codes=["NO_UPDATE_FIELDS_PROVIDED"],
            )

        return PolicyDecision(
            allowed=True,
            approval_required=False,  # Low-risk allow-listed update does not require human reviewer approval
            risk="LOW",
            reason_codes=["ALLOWLISTED_UPDATE_PERMITTED"],
            details={"display_name": payload.display_name, "phone": payload.phone},
        )
