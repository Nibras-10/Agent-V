from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    id: str
    request_id: str
    actor_id: str
    actor_type: str
    event_type: str
    resource_type: str
    resource_id: str
    ticket_id: str | None = None
    metadata_redacted: dict[str, Any]
    created_at: datetime
