from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class HumanQueueResponse(BaseModel):
    id: str
    ticket_id: str
    reason_code: str
    summary: str
    status: str
    assigned_to: Optional[str] = None
    created_at: datetime
