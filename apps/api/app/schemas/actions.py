import hashlib
import json
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class RefundProposalPayload(BaseModel):
    transaction_id: str
    customer_id: str
    amount_minor: int = Field(gt=0, description="Refund amount in minor currency units (cents)")
    currency: str = "USD"
    reason: str
    expected_version: Optional[int] = Field(default=None, ge=1)


class CancellationProposalPayload(BaseModel):
    subscription_id: str
    customer_id: str
    reason: str
    cancel_at_period_end: bool = True
    expected_version: Optional[int] = Field(default=None, ge=1)


class ContactUpdatePayload(BaseModel):
    customer_id: str
    display_name: Optional[str] = None
    phone: Optional[str] = None


def compute_proposal_hash(action_type: str, payload: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 canonical hash of the action proposal."""
    canonical_dict = {
        "action_type": action_type,
        "payload": payload,
    }
    canonical_str = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


class PolicyDecision(BaseModel):
    allowed: bool
    approval_required: bool = True
    risk: str = "HIGH"  # LOW, HIGH
    reason_codes: List[str] = []
    details: Dict[str, Any] = {}


class ActionResult(BaseModel):
    success: bool
    action_type: str
    idempotency_key: str
    status: str  # SUCCESS, FAILED, UNKNOWN
    message: str
    data: Dict[str, Any] = {}
