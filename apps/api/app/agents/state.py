from typing import TypedDict, Optional, List, Dict, Any, Literal
from datetime import datetime, timezone


class SupportState(TypedDict, total=False):
    run_id: str
    conversation_id: str
    ticket_id: str
    authenticated_actor_id: str
    customer_id: str
    messages: List[Dict[str, Any]]
    intent: Optional[str]  # e.g., "account_question", "refund_request", "cancel_subscription", "contact_update", "ambiguous"
    confidence: float
    retrieved_context: Dict[str, Any]
    proposed_action: Optional[Dict[str, Any]]
    approval_id: Optional[str]
    approval_decision: Optional[str]
    approval_reviewer_id: Optional[str]
    action_result: Optional[Dict[str, Any]]
    risk_level: str  # "LOW", "HIGH"
    retry_count: int
    tool_call_count: int
    llm_call_count: int
    status: Literal["RUNNING", "WAITING_FOR_USER", "WAITING_FOR_APPROVAL", "COMPLETED", "HANDED_OFF", "FAILED"]
    last_error_code: Optional[str]
    token_usage: Dict[str, int]
    created_at: str
    updated_at: str
    final_response: Optional[str]
    clarification_question: Optional[str]
