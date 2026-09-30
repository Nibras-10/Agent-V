from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    actor_type: str
    actor_id: Optional[str] = None
    content: str
    created_at: datetime
    workflow_status: Optional[str] = None
    intent: Optional[str] = None
    approval_id: Optional[str] = None
    recommended_action: Optional[dict] = None


class ConversationCreate(BaseModel):
    ticket_id: Optional[str] = None
    subject: Optional[str] = "Customer Support Inquiry"
    initial_message: Optional[str] = None


class ConversationResponse(BaseModel):
    id: str
    ticket_id: str
    channel: str
    created_at: datetime
    messages: List[MessageResponse] = []


class SupportTicketResponse(BaseModel):
    id: str
    customer_id: str
    status: str
    priority: str
    subject: str
    created_at: datetime
    updated_at: datetime
    conversations: List[ConversationResponse] = []
