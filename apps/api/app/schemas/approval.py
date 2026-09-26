from datetime import datetime
from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, Field


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    comment: Optional[str] = Field(None, max_length=1000)


class ActionProposalResponse(BaseModel):
    id: str
    run_id: str
    type: str
    payload_json: Dict[str, Any]
    risk_level: str
    proposal_hash: str
    status: str


class ApprovalResponse(BaseModel):
    id: str
    proposal_id: str
    ticket_id: str
    action_type: str
    proposal_payload: Dict[str, Any]
    proposal_hash: str
    requested_by_run_id: str
    status: str
    reviewer_id: Optional[str] = None
    reviewer_comment: Optional[str] = None
    created_at: datetime
    decided_at: Optional[datetime] = None
    expires_at: datetime
